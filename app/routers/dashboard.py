from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..services.streaks import current_streak_days, personal_best_days
from ..services.savings import compute_savings
from ..services.rewards import compute_reward_budget

router = APIRouter(tags=["dashboard"])

THOUGHTS = [
    "Un jour à la fois.",
    "Chaque non compte autant que chaque oui.",
    "Ton corps se souvient déjà de ce que tu lui offres.",
    "Le progrès n'est pas linéaire, il est cumulatif.",
    "Tu n'as pas besoin d'être parfait, juste présent aujourd'hui.",
    "La discipline d'aujourd'hui est la liberté de demain.",
    "Compte les jours, pas les manques.",
]


@router.get("/me/dashboard", response_model=schemas.DashboardOut)
def get_dashboard(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # --- Streaks (une carte par substance suivie) ---
    streaks = [
        schemas.StreakOut(
            substance_id=s.id,
            label=s.label,
            category=s.category.value,
            days=current_streak_days(db, s, now=now),
            personal_best_days=personal_best_days(db, s, now=now),
        )
        for s in user.substances
    ]

    # --- Économies ---
    total_savings, delta_week = compute_savings(db, user, now=now)

    # --- Habitudes du jour ---
    habits_today = []
    for habit in user.habits:
        if not habit.active:
            continue
        done_today = any(log.occurred_at >= today_start for log in habit.logs)
        habits_today.append(
            schemas.HabitTodayOut(id=habit.id, label=habit.label, target=habit.target, done_today=done_today)
        )

    # --- Objectifs (résumé pour le bandeau) ---
    active_goals = [g for g in user.goals if g.completed_at is None]
    top_goal = max(active_goals, key=lambda g: (g.current_value / g.target_value if g.target_value else 0), default=None)
    goals_summary = schemas.GoalSummaryOut(
        active_count=len(active_goals),
        top_goal_label=top_goal.label if top_goal else None,
        top_goal_percent=round(100 * top_goal.current_value / top_goal.target_value, 1) if top_goal and top_goal.target_value else None,
    )

    # --- Budget récompense ---
    multiplier, reward_budget, available_balance = compute_reward_budget(db, user, total_savings, now=now)

    return schemas.DashboardOut(
        display_name=user.display_name,
        date=now.date().isoformat(),
        streaks=streaks,
        savings=schemas.SavingsOut(total=total_savings, delta_week=delta_week),
        habits_today=habits_today,
        goals_summary=goals_summary,
        reward_budget=schemas.RewardBudgetOut(
            multiplier=multiplier, reward_budget=reward_budget, available_balance=available_balance
        ),
        thought_of_the_day=THOUGHTS[now.timetuple().tm_yday % len(THOUGHTS)],
    )
