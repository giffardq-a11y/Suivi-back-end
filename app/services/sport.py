"""Logique partagée entre Entraînement (training.py) et Diète (diet.py) —
toute séance de sport enregistrée (course, muscu, autre sport) alimente à la
fois le bilan calorique du jour ET les objectifs/habitudes liés au sport.
Traduction directe de caloriesBurnedOn / incrementSessionGoals /
markSportHabitsDoneToday côté mockData.js.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from .. import models
from .common import is_same_day, now_utc

# Estimation grossière (façon MET) des calories dépensées — mêmes taux que
# KCAL_PER_MIN côté mock, pas une valeur médicale précise.
KCAL_PER_MIN_RUNNING = 10
KCAL_PER_MIN_STRENGTH = {"live": 6, "quick_detailed": 6, "quick_duration": 5}
KCAL_PER_MIN_SPORT_INTENSITY = {"faible": 4, "moyenne": 7, "forte": 10}
KCAL_PER_MIN_SPORT_DEFAULT = 8


def estimate_run_calories(duration_min: float) -> int:
    return round(duration_min * KCAL_PER_MIN_RUNNING)


def estimate_strength_calories(mode: str, duration_min: float) -> int:
    rate = KCAL_PER_MIN_STRENGTH.get(mode, KCAL_PER_MIN_STRENGTH["quick_duration"])
    return round(duration_min * rate)


def estimate_other_sport_calories(duration_min: float, intensity: str | None) -> int:
    rate = KCAL_PER_MIN_SPORT_INTENSITY.get(intensity, KCAL_PER_MIN_SPORT_DEFAULT) if intensity else KCAL_PER_MIN_SPORT_DEFAULT
    return round(duration_min * rate)


def calories_burned_on(db: Session, user_id: str, date_dt: datetime) -> int:
    runs = db.query(models.Run).filter(models.Run.user_id == user_id).all()
    strength = db.query(models.StrengthSession).filter(models.StrengthSession.user_id == user_id).all()
    other = db.query(models.OtherSportLog).filter(models.OtherSportLog.user_id == user_id).all()

    total = 0
    for r in runs:
        if is_same_day(r.occurred_at, date_dt):
            total += r.calories_burned or 0
    for s in strength:
        if is_same_day(s.occurred_at, date_dt):
            total += s.calories_burned or 0
    for o in other:
        if is_same_day(o.occurred_at, date_dt):
            total += o.calories_burned or 0
    return total


def increment_session_goals(db: Session, user: models.User) -> None:
    goals = (
        db.query(models.Goal)
        .filter(models.Goal.user_id == user.id, models.Goal.linked_metric == "sport_sessions", models.Goal.completed_at.is_(None))
        .all()
    )
    for g in goals:
        g.current_value = min(g.target_value, g.current_value + 1)
        if g.current_value >= g.target_value:
            g.completed_at = now_utc()
    db.commit()


def mark_sport_habits_done_today(db: Session, user: models.User) -> None:
    now = now_utc()
    habits = (
        db.query(models.Habit)
        .filter(models.Habit.user_id == user.id, models.Habit.linked_activity == "sport_session")
        .all()
    )
    for h in habits:
        already_done = any(is_same_day(l.occurred_at, now) for l in h.logs)
        if not already_done:
            db.add(models.HabitLog(habit_id=h.id, occurred_at=now))
    db.commit()
