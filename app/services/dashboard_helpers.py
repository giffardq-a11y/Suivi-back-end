"""Extrait de routers/dashboard.py — factorisé pour être réutilisable par
GET /report (settings.py), qui a besoin du même calcul de streaks/économies/
habitudes du jour pour construire le message récap."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models
from .streaks import current_streak_days, personal_best_days
from .savings import compute_savings
from .rewards import compute_reward_budget
from .habit_progress import effective_habit_target

THOUGHTS = [
    "Un jour à la fois.",
    "Chaque non compte autant que chaque oui.",
    "Ton corps se souvient déjà de ce que tu lui offres.",
    "Le progrès n’est pas linéaire, il est cumulatif.",
    "Tu n’as pas besoin d’être parfait, juste présent aujourd’hui.",
    "La discipline d’aujourd’hui est la liberté de demain.",
    "Compte les jours, pas les manques.",
]


def build_dashboard_dict(db: Session, user: models.User) -> dict:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    streaks = [
        {
            "substance_id": s.id, "label": s.label, "category": s.category.value,
            "days": current_streak_days(db, s, now=now),
            "personal_best_days": personal_best_days(db, s, now=now),
        }
        for s in user.substances
    ]

    total_savings, delta_week = compute_savings(db, user, now=now)

    habits_today = []
    for habit in user.habits:
        if not habit.active:
            continue
        done_today = any(log.occurred_at >= today_start for log in habit.logs)
        habits_today.append({
            "id": habit.id, "label": habit.label,
            "target": effective_habit_target(habit, now), "done_today": done_today,
        })

    active_goals = [g for g in user.goals if g.completed_at is None]
    top_goal = max(active_goals, key=lambda g: (g.current_value / g.target_value if g.target_value else 0), default=None)
    goals_summary = {
        "active_count": len(active_goals),
        "top_goal_label": top_goal.label if top_goal else None,
        "top_goal_percent": round(100 * top_goal.current_value / top_goal.target_value, 1) if top_goal and top_goal.target_value else None,
    }

    multiplier, reward_budget, available_balance = compute_reward_budget(db, user, total_savings, now=now)

    return {
        "display_name": user.display_name,
        "date": now.date().isoformat(),
        "streaks": streaks,
        "savings": {"total": total_savings, "delta_week": delta_week, "currency": "EUR"},
        "habits_today": habits_today,
        "goals_summary": goals_summary,
        "reward_budget": {"multiplier": multiplier, "reward_budget": reward_budget, "available_balance": available_balance},
        "thought_of_the_day": THOUGHTS[now.timetuple().tm_yday % len(THOUGHTS)],
    }
