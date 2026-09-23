"""Journal / Stats / Historique / Calendrier — endpoints en lecture qui
agrègent plusieurs tables (entries, habits, meals, sport...). Traduction de
buildJournal / buildStats / buildHistoryMonth / buildHistoryDetail /
buildWeekOverview / buildDayDetail / buildJournalOverview / buildHabitsStats
/ buildOverviewStats côté mockData.js.
"""
import random
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..services.common import now_utc, to_ms, from_ms, relative_time, is_same_day, start_of_week, aware
from ..services.savings import compute_savings
from ..services.streaks import current_streak_days
from ..services.sport import calories_burned_on
from ..services.habit_progress import effective_habit_target, jours_actifs
from .diet import _meals_calories_on

router = APIRouter(tags=["journal-stats"])

THOUGHTS = [
    "Un jour à la fois.",
    "Chaque non compte autant que chaque oui.",
    "Ton corps se souvient déjà de ce que tu lui offres.",
    "Le progrès n’est pas linéaire, il est cumulatif.",
    "Tu n’as pas besoin d’être parfait, juste présent aujourd’hui.",
]


def _serialize_entry(e: models.ConsumptionEntry) -> dict:
    if e.type == models.EntryType.CRAVING_RESISTED:
        label, detail = "Envie résistée", "Craving résisté"
    elif e.substance:
        label, detail = e.substance.label, (e.substance.unit or "")
    else:
        label, detail = "Autre", ""
    return {
        "id": e.id,
        "substanceKey": e.substance.category.value if e.substance else None,
        "label": label,
        "detail": detail,
        "note": e.context,
        "quantity": e.quantity,
        "price": e.price,
        "occurredAt": to_ms(e.occurred_at),
        "relativeTime": relative_time(e.occurred_at),
    }


@router.get("/journal")
def get_journal(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    entries = (
        db.query(models.ConsumptionEntry)
        .filter(models.ConsumptionEntry.user_id == user.id)
        .order_by(models.ConsumptionEntry.occurred_at.desc())
        .limit(20)
        .all()
    )
    return {"recent": [_serialize_entry(e) for e in entries]}


@router.get("/random-thought")
def get_random_thought(current: str | None = Query(None, alias="currentThought")):
    options = [t for t in THOUGHTS if t != current] or THOUGHTS
    return {"thought": random.choice(options)}


@router.get("/stats")
def get_stats(period: str = "week", db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    now = now_utc()
    is_month = period == "month"

    alcohol = next((s for s in user.substances if s.category == models.SubstanceCategory.ALCOHOL), None)
    tobacco = next((s for s in user.substances if s.category == models.SubstanceCategory.TOBACCO), None)

    total_savings, _delta = compute_savings(db, user, now=now)

    craving_entries = (
        db.query(models.ConsumptionEntry)
        .filter(models.ConsumptionEntry.user_id == user.id, models.ConsumptionEntry.type == models.EntryType.CRAVING_RESISTED)
        .all()
    )

    if is_month:
        craving_bars = [0, 0, 0, 0]
        craving_labels = ["S-3", "S-2", "S-1", "Cette sem."]
        for e in craving_entries:
            weeks_ago = (now - e.occurred_at).days // 7
            idx = 3 - weeks_ago
            if 0 <= idx < 4:
                craving_bars[idx] += 1
    else:
        craving_bars = [0] * 7
        craving_labels = ["L", "M", "M", "J", "V", "S", "D"]
        for e in craving_entries:
            day_index = 6 - (now - e.occurred_at).days
            if 0 <= day_index < 7:
                craving_bars[day_index] += 1

    def variation_percent(substance) -> float:
        """Variation du nombre de consommations sur la période vs la
        période équivalente précédente — approximation raisonnable de
        l'évolution, faute d'historique de référence explicite (le mock
        se contente d'une constante -35/-42, pas calculée du tout)."""
        if not substance:
            return 0
        window_days = 30 if is_month else 7
        cutoff = now - timedelta(days=window_days)
        prev_cutoff = now - timedelta(days=window_days * 2)
        current_count = sum(
            1 for e in substance.entries
            if e.type == models.EntryType.CONSUMPTION and aware(e.occurred_at) >= cutoff
        )
        prev_count = sum(
            1 for e in substance.entries
            if e.type == models.EntryType.CONSUMPTION and prev_cutoff <= aware(e.occurred_at) < cutoff
        )
        if prev_count == 0:
            return -100 if current_count == 0 else 0
        return round(((current_count - prev_count) / prev_count) * 100)

    alcohol_days = current_streak_days(db, alcohol, now=now) if alcohol else 0
    tobacco_days = current_streak_days(db, tobacco, now=now) if tobacco else 0

    by_substance = [
        {"label": "Alcool", "variation_percent": variation_percent(alcohol)},
        {"label": "Tabac", "variation_percent": variation_percent(tobacco)},
    ]

    return {
        "period": period,
        "comparison_label": "vs mois précédent" if is_month else "vs semaine précédente",
        "alcohol_variation_percent": variation_percent(alcohol),
        "tobacco_smoke_free_days_month": tobacco_days,
        "savings": {
            "total": total_savings,
            "alcohol_progress": min(1, alcohol_days / 90),
            "tobacco_progress": min(1, tobacco_days / 90),
            "monthly_projection": round(total_savings * (30 / max(1, alcohol_days))) if alcohol_days else total_savings,
        },
        "craving_bars": craving_bars,
        "craving_labels": craving_labels,
        "by_substance": by_substance,
    }


@router.get("/history")
def get_history(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    year, month = now.year, now.month
    first_of_month = datetime(year, month, 1, tzinfo=timezone.utc)
    days_in_month = (
        (datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc))
        - first_of_month
    ).days
    first_weekday = first_of_month.weekday()

    entries = (
        db.query(models.ConsumptionEntry)
        .filter(models.ConsumptionEntry.user_id == user.id)
        .all()
    )
    entries_by_day: dict[int, int] = {}
    for e in entries:
        if e.occurred_at.year == year and e.occurred_at.month == month:
            entries_by_day[e.occurred_at.day] = entries_by_day.get(e.occurred_at.day, 0) + 1

    days = [None] * first_weekday
    for d in range(1, days_in_month + 1):
        is_future = d > now.day
        status = "none" if is_future else ("partial" if entries_by_day.get(d) else "clean")
        days.append({"day": d, "status": status})

    recent = (
        db.query(models.ConsumptionEntry)
        .filter(models.ConsumptionEntry.user_id == user.id)
        .order_by(models.ConsumptionEntry.occurred_at.desc())
        .limit(20)
        .all()
    )
    return {"days": days, "recent": [_serialize_entry(e) for e in recent]}


@router.get("/history/detail")
def get_history_detail(
    period: str = "last_week",
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    now = now_utc()
    if period == "today":
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "last_month":
        cutoff = now - timedelta(days=30)
    else:
        cutoff = now - timedelta(days=7)

    entries = (
        db.query(models.ConsumptionEntry)
        .filter(models.ConsumptionEntry.user_id == user.id, models.ConsumptionEntry.occurred_at >= cutoff)
        .order_by(models.ConsumptionEntry.occurred_at.desc())
        .all()
    )
    return [_serialize_entry(e) for e in entries]


@router.get("/week-overview")
def get_week_overview(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    now = now_utc()
    week_start = start_of_week(now)

    habits_out = []
    for h in user.habits:
        if not h.active:
            continue
        done = sum(1 for l in h.logs if aware(l.occurred_at) >= week_start)
        habits_out.append({
            "id": h.id, "label": h.label, "target": effective_habit_target(h, now),
            "weeklyTarget": h.weekly_target or 7, "done_this_week": done,
        })

    goals_out = [
        {"id": g.id, "label": g.label, "percent": min(100, round((100 * g.current_value) / g.target_value)) if g.target_value else 0}
        for g in user.goals if g.completed_at is None
    ]
    return {"habits": habits_out, "goals": goals_out}


@router.get("/day-detail")
def get_day_detail(dateMs: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    date_dt = from_ms(dateMs)
    entries = (
        db.query(models.ConsumptionEntry)
        .filter(models.ConsumptionEntry.user_id == user.id)
        .all()
    )
    entries_that_day = [e for e in entries if is_same_day(e.occurred_at, date_dt)]

    habits_out = []
    for h in user.habits:
        if not h.active:
            continue
        jours = jours_actifs(h)
        if jours is not None and date_dt.weekday() not in jours:
            continue
        done = any(is_same_day(l.occurred_at, date_dt) for l in h.logs)
        habits_out.append({"id": h.id, "label": h.label, "done": done})

    return {"entries": [_serialize_entry(e) for e in entries_that_day], "habits": habits_out}


@router.get("/journal-overview")
def get_journal_overview(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    now = now_utc()

    planned = []
    semaine_debut = start_of_week(now)
    for h in user.habits:
        if not h.active:
            continue
        # Une habitude n'est proposée que les jours où elle s'applique : sans
        # ce filtre, une natation du mardi encombre le fil tous les jours.
        jours = jours_actifs(h)
        if jours is not None and now.weekday() not in jours:
            continue
        done = any(is_same_day(l.occurred_at, now) for l in h.logs)
        faites = sum(1 for l in h.logs if aware(l.occurred_at) >= semaine_debut)
        cible = h.weekly_target or 7
        # Avant, seules les habitudes ayant un horaire entraient dans le fil :
        # une habitude hebdomadaire sans heure n'y apparaissait jamais.
        planned.append({
            "type": "habit", "id": h.id, "label": h.label,
            "scheduledTime": h.scheduled_time, "done": done,
            "done_this_week": faites, "weekly_target": cible,
            "weekly": cible < 7,
            "days_of_week": h.days_of_week,
        })

    templates = (
        db.query(models.WorkoutTemplate)
        .filter(models.WorkoutTemplate.user_id == user.id, models.WorkoutTemplate.scheduled_time.isnot(None))
        .all()
    )
    planned_template_ids = {t.id for t in templates}
    for t in templates:
        done = (
            db.query(models.StrengthSession)
            .filter(models.StrengthSession.user_id == user.id, models.StrengthSession.template_id == t.id)
            .all()
        )
        done_today = any(is_same_day(s.occurred_at, now) for s in done)
        planned.append({"type": "workout", "id": t.id, "label": t.name, "scheduledTime": t.scheduled_time, "done": done_today})

    planned.sort(key=lambda p: p.get("scheduledTime") or "")

    unplanned = []
    for h in user.habits:
        if h.active and not h.scheduled_time and any(is_same_day(l.occurred_at, now) for l in h.logs):
            unplanned.append({"type": "habit", "label": h.label, "detail": "Habitude complétée"})

    strength_today = (
        db.query(models.StrengthSession)
        .filter(models.StrengthSession.user_id == user.id)
        .all()
    )
    for s in strength_today:
        if is_same_day(s.occurred_at, now) and not (s.template_id and s.template_id in planned_template_ids):
            unplanned.append({"type": "sport", "label": s.template_name or "Séance libre", "detail": f"{s.duration_min} min"})

    runs_today = db.query(models.Run).filter(models.Run.user_id == user.id).all()
    for r in runs_today:
        if is_same_day(r.occurred_at, now):
            unplanned.append({"type": "sport", "label": "Course à pied", "detail": f"{r.distance_km} km"})

    other_today = db.query(models.OtherSportLog).filter(models.OtherSportLog.user_id == user.id).all()
    for s in other_today:
        if is_same_day(s.occurred_at, now):
            unplanned.append({"type": "sport", "label": s.sport_label, "detail": f"{s.duration_min} min"})

    consumed = _meals_calories_on(db, user.id, now)
    burned = calories_burned_on(db, user.id, now)
    profile = db.query(models.Profile).filter(models.Profile.user_id == user.id).first()
    budget = profile.daily_calorie_budget if profile else 2000

    return {
        "planned": planned,
        "unplanned": unplanned,
        "calorie_balance": {
            "consumed": round(consumed), "burned": round(burned),
            "net": round(consumed - burned), "budget": budget,
        },
    }


@router.get("/stats/habits")
def get_habits_stats(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    now = now_utc()
    week_start = start_of_week(now)

    habits_data = []
    for h in user.habits:
        if not h.active:
            continue
        done_this_week = sum(1 for l in h.logs if aware(l.occurred_at) >= week_start)
        streak = 0
        cursor = now
        while any(is_same_day(l.occurred_at, cursor) for l in h.logs) and streak < 365:
            streak += 1
            cursor -= timedelta(days=1)
        habits_data.append({
            "id": h.id, "label": h.label, "done_this_week": done_this_week,
            "weekly_target": h.weekly_target or 7, "streak_days": streak,
        })

    avg_completion = (
        round(sum(min(1, hd["done_this_week"] / (hd["weekly_target"] or 7)) for hd in habits_data) / len(habits_data) * 100)
        if habits_data else 0
    )
    return {"weekly_completion_percent": avg_completion, "habits": habits_data}


@router.get("/stats/overview")
def get_overview_stats(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    consumption = get_stats(period="week", db=db, user=user)
    sport = _sport_stats_snapshot(db, user)
    habits = get_habits_stats(db=db, user=user)

    weight_entry = (
        db.query(models.WeightEntry)
        .filter(models.WeightEntry.user_id == user.id)
        .order_by(models.WeightEntry.occurred_at.asc())
        .all()
    )
    profile = db.query(models.Profile).filter(models.Profile.user_id == user.id).first()
    current_kg = weight_entry[-1].weight_kg if weight_entry else None
    start_kg = weight_entry[0].weight_kg if weight_entry else None
    total_delta = round((current_kg - start_kg) * 10) / 10 if current_kg is not None and start_kg is not None else 0

    return {
        "consumption": {
            "alcohol_variation_percent": consumption["alcohol_variation_percent"],
            "tobacco_smoke_free_days_month": consumption["tobacco_smoke_free_days_month"],
            "savings_total": consumption["savings"]["total"],
        },
        "sport": {
            "sessions_this_week": sport["sessions_this_week"],
            "calories_this_week": sport["calories_this_week"],
            "distance_week_km": sport["distance_week_km"],
        },
        "habits": {
            "weekly_completion_percent": habits["weekly_completion_percent"],
            "active_count": len(habits["habits"]),
        },
        "weight": {
            "current_kg": current_kg, "total_delta": total_delta,
            "goal_kg": profile.weight_goal_kg if profile else None,
        },
    }


def _sport_stats_snapshot(db: Session, user: models.User) -> dict:
    # Réutilise le même calcul que GET /stats/sport (training.py) sans
    # dupliquer la logique — importé en différé pour éviter un import
    # circulaire (training.py n'a pas besoin de journal_stats.py).
    from .training import get_sport_stats
    return get_sport_stats(db=db, user=user)
