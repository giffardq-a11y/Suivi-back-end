from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services.common import now_utc, is_same_day
from ..services.savings import compute_savings
from ..services.rewards import compute_reward_budget

router = APIRouter(tags=["goals"])

# Catalogue de récompenses — statique, comme mockData.js (state.rewards).
# Pas de CRUD côté app pour créer ses propres récompenses actuellement, donc
# pas de table dédiée : seul l'historique d'achat (RewardPurchase, déjà
# existant) a besoin d'être en base.
REWARDS_CATALOG = [
    {"id": "reward-1", "label": "Un resto", "cost": 40},
    {"id": "reward-2", "label": "Une place de cinéma", "cost": 15},
    {"id": "reward-3", "label": "Nouvelle tenue de sport", "cost": 80},
    {"id": "reward-4", "label": "Week-end détente", "cost": 250},
]


class GoalCreate(BaseModel):
    label: str
    weight: int = 1
    linkedType: str | None = None
    targetValue: float
    linkedHabitId: str | None = None
    linkedExerciseName: str | None = None


def _habit_streak_days(db: Session, habit_id: str, now) -> int:
    """Jours consécutifs jusqu'à aujourd'hui où l'habitude a été loggée —
    même logique que buildHabitsStats côté mock, s'arrête au 1er jour manqué."""
    logs = db.query(models.HabitLog).filter(models.HabitLog.habit_id == habit_id).all()
    streak = 0
    cursor = now
    while any(is_same_day(l.occurred_at, cursor) for l in logs) and streak < 3650:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _linked_goal_progress(db: Session, user: models.User, goal: models.Goal, now) -> dict | None:
    if not goal.linked_type:
        return None

    if goal.linked_type == "habit_streak" and goal.linked_habit_id:
        streak = _habit_streak_days(db, goal.linked_habit_id, now)
        return {"current_value": streak, "target_value": goal.target_value}

    if goal.linked_type == "weight_target":
        entries = (
            db.query(models.WeightEntry)
            .filter(models.WeightEntry.user_id == user.id)
            .order_by(models.WeightEntry.occurred_at.asc())
            .all()
        )
        if not entries:
            return {"current_value": 0, "target_value": goal.target_value, "percent_override": 0}
        current = entries[-1].weight_kg
        start = entries[0].weight_kg
        total_distance = abs(goal.target_value - start)
        traveled = abs(current - start)
        percent = min(100, round((traveled / total_distance) * 100)) if total_distance > 0 else 100
        return {"current_value": current, "target_value": goal.target_value, "percent_override": percent}

    if goal.linked_type == "body_fat_target":
        entries = (
            db.query(models.BodyFatEntry)
            .filter(models.BodyFatEntry.user_id == user.id)
            .order_by(models.BodyFatEntry.occurred_at.asc())
            .all()
        )
        if not entries:
            return {"current_value": 0, "target_value": goal.target_value, "percent_override": 0}
        current = entries[-1].percent
        start = entries[0].percent
        total_distance = abs(goal.target_value - start)
        traveled = abs(current - start)
        percent = min(100, round((traveled / total_distance) * 100)) if total_distance > 0 else 100
        return {"current_value": current, "target_value": goal.target_value, "percent_override": percent}

    if goal.linked_type == "strength_pr" and goal.linked_exercise_name:
        sessions = db.query(models.StrengthSession).filter(models.StrengthSession.user_id == user.id).all()
        max_weight = 0
        for s in sessions:
            for ex in (s.exercises or []):
                if ex.get("name") == goal.linked_exercise_name:
                    for st in ex.get("sets", []):
                        if st.get("done") and (st.get("weight") or 0) > max_weight:
                            max_weight = st["weight"]
        return {"current_value": max_weight, "target_value": goal.target_value}

    return None


def _serialize_goal(db: Session, user: models.User, goal: models.Goal, now) -> dict:
    linked = _linked_goal_progress(db, user, goal, now)
    current_value = linked["current_value"] if linked else goal.current_value
    target_value = linked["target_value"] if linked else goal.target_value
    if linked and linked.get("percent_override") is not None:
        percent = linked["percent_override"]
    else:
        percent = min(100, round((100 * current_value) / target_value)) if target_value else 0
    return {
        "id": goal.id,
        "label": goal.label,
        "percent": percent,
        "current_value": current_value,
        "target_value": target_value,
        "weight": goal.weight,
        "completed": goal.completed_at is not None or percent >= 100,
        "linked_type": goal.linked_type,
    }


@router.get("/goals")
def get_goals(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    now = now_utc()
    total_savings, _delta = compute_savings(db, user, now=now)
    multiplier, reward_budget, available_balance = compute_reward_budget(db, user, total_savings, now=now)

    goals = db.query(models.Goal).filter(models.Goal.user_id == user.id).all()
    perso = (
        db.query(models.Reward)
        .filter(models.Reward.user_id == user.id)
        .order_by(models.Reward.created_at)
        .all()
    )
    rewards = [
        {**r, "unlocked": r["cost"] <= available_balance, "own": False}
        for r in REWARDS_CATALOG
    ] + [
        {
            "id": r.id, "label": r.label, "cost": r.cost, "own": True,
            # Sans prix, rien à débloquer : l'app affiche « prix à définir ».
            "unlocked": r.cost is not None and r.cost <= available_balance,
        }
        for r in perso
    ]

    return {
        "reward_budget": {
            "multiplier": multiplier,
            "reward_budget": reward_budget,
            "available_balance": available_balance,
        },
        "savings_total": total_savings,
        "goals": [_serialize_goal(db, user, g, now) for g in goals],
        "rewards": rewards,
    }


@router.post("/goals", status_code=201)
def create_goal(
    payload: GoalCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    # linked_* stockés sur des colonnes non normalisées côté modèle actuel
    # (Goal n'a pas encore linked_type/linked_habit_id/linked_exercise_name
    # — ajoutés ci-dessous via _ensure_goal_columns dans main.py).
    goal = models.Goal(
        user_id=user.id,
        label=payload.label,
        target_value=payload.targetValue,
        current_value=0,
        weight=payload.weight,
        linked_type=payload.linkedType,
        linked_habit_id=payload.linkedHabitId,
        linked_exercise_name=payload.linkedExerciseName,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return {"ok": True, "id": goal.id}


class RewardIn(BaseModel):
    label: str
    cost: float | None = None


@router.get("/rewards")
def list_rewards(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    perso = db.query(models.Reward).filter(models.Reward.user_id == user.id).order_by(models.Reward.created_at).all()
    return {
        "catalogue": REWARDS_CATALOG,
        "miennes": [{"id": r.id, "label": r.label, "cost": r.cost} for r in perso],
    }


@router.post("/rewards", status_code=201)
def add_reward(
    payload: RewardIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    reward = models.Reward(user_id=user.id, label=payload.label.strip(), cost=payload.cost)
    db.add(reward)
    db.commit()
    db.refresh(reward)
    return {"ok": True, "id": reward.id}


@router.put("/rewards/{reward_id}")
def update_reward(
    reward_id: str,
    payload: RewardIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    reward = (
        db.query(models.Reward)
        .filter(models.Reward.id == reward_id, models.Reward.user_id == user.id)
        .first()
    )
    if not reward:
        raise HTTPException(status_code=404, detail="Récompense introuvable")
    reward.label = payload.label.strip()
    reward.cost = payload.cost
    db.commit()
    return {"ok": True}


@router.delete("/rewards/{reward_id}", status_code=204)
def delete_reward(
    reward_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    reward = (
        db.query(models.Reward)
        .filter(models.Reward.id == reward_id, models.Reward.user_id == user.id)
        .first()
    )
    if not reward:
        raise HTTPException(status_code=404, detail="Récompense introuvable (le catalogue fourni ne se supprime pas)")
    db.delete(reward)
    db.commit()


@router.post("/rewards/{reward_id}/purchase")
def purchase_reward(
    reward_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    reward = next((r for r in REWARDS_CATALOG if r["id"] == reward_id), None)
    if reward:
        label, cost = reward["label"], reward["cost"]
    else:
        perso = (
            db.query(models.Reward)
            .filter(models.Reward.id == reward_id, models.Reward.user_id == user.id)
            .first()
        )
        if not perso:
            raise HTTPException(status_code=404, detail="Récompense introuvable")
        if perso.cost is None:
            raise HTTPException(status_code=400, detail="Fixe d'abord un prix pour cette récompense.")
        label, cost = perso.label, perso.cost

    db.add(models.RewardPurchase(user_id=user.id, reward_item_label=label, cost_at_purchase=cost))
    db.commit()
    return {"ok": True}


BENEFIT_MILESTONES_HOURS = [
    ("24h", "24 h", 24, "Le corps commence déjà à récupérer."),
    ("72h", "72 h", 72, "Sommeil plus profond, meilleure récupération générale."),
    ("2sem", "2 sem.", 24 * 14, "Amélioration nette du bien-être général."),
    ("1mois", "1 mois", 24 * 30, "Progrès nettement visibles sur la routine installée."),
    ("3mois", "3 mois", 24 * 90, "Bénéfices durablement installés."),
]

HABIT_BENEFITS_BY_KEY = {
    "sport": "Renforce le cœur, réduit le stress et améliore la qualité du sommeil.",
    "meditation": "Diminue l’anxiété et aide à mieux gérer les envies dans les moments difficiles.",
    "hydratation": "Aide le corps à éliminer les toxines et réduit les maux de tête.",
    "sommeil": "Un sommeil régulier renforce la volonté et stabilise l’humeur.",
}


@router.get("/benefits")
def get_benefits(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    now = now_utc()
    substances_out = []
    for sub in user.substances:
        last = sub.entries and max(
            (e.occurred_at for e in sub.entries if e.type == models.EntryType.CONSUMPTION),
            default=None,
        )
        reference = last or sub.user.created_at
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        elapsed_hours = (now - reference).total_seconds() / 3600
        milestones = [
            {
                "key": key, "label": label, "desc": desc,
                "reached": elapsed_hours >= hours,
                "remaining_days": 0 if elapsed_hours >= hours else -(-(hours - elapsed_hours) // 24),
            }
            for key, label, hours, desc in BENEFIT_MILESTONES_HOURS
        ]
        substances_out.append({"key": sub.category.value, "label": sub.label, "milestones": milestones})

    habits_out = [
        {
            "id": h.id, "label": h.label,
            "benefit": HABIT_BENEFITS_BY_KEY.get(h.key, "Contribue à construire une routine plus saine au quotidien."),
        }
        for h in user.habits
    ]

    return {"substances": substances_out, "habits": habits_out}
