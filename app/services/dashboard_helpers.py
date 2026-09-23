"""Extrait de routers/dashboard.py — factorisé pour être réutilisable par
GET /report (settings.py), qui a besoin du même calcul de streaks/économies/
habitudes du jour pour construire le message récap."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models
from .streaks import current_streak_days, personal_best_days
from .savings import compute_savings
from .rewards import compute_reward_budget
from .common import start_of_week, is_same_day
from .habit_progress import effective_habit_target, jours_actifs
from .sport import calories_burned_on

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
    semaine_debut = start_of_week(now)
    for habit in user.habits:
        if not habit.active:
            continue
        # occurred_at revient naif depuis SQLite (DateTime(timezone=True) n'y
        # est pas vraiment tz-aware, contrairement a Postgres/TIMESTAMPTZ en
        # prod) -- meme garde que _days_between() dans services/streaks.py.
        done_today = any(
            (log.occurred_at if log.occurred_at.tzinfo else log.occurred_at.replace(tzinfo=timezone.utc)) >= today_start
            for log in habit.logs
        )
        # Une habitude n'apparaît à l'Accueil que les jours où elle
        # s'applique : sinon une natation du mardi traîne dans la liste du
        # jour toute la semaine et compte comme ratée six jours sur sept.
        jours = jours_actifs(habit)
        if jours is not None and now.weekday() not in jours:
            continue

        # Progression de la semaine : une habitude visée 2 fois par semaine ne
        # se lit pas en « fait / pas fait aujourd'hui ».
        faites = sum(
            1 for log in habit.logs
            if (log.occurred_at if log.occurred_at.tzinfo else log.occurred_at.replace(tzinfo=timezone.utc)) >= semaine_debut
        )
        cible = habit.weekly_target or 7
        habits_today.append({
            "id": habit.id, "label": habit.label,
            "target": effective_habit_target(habit, now), "done_today": done_today,
            "done_this_week": faites, "weekly_target": cible, "weekly": cible < 7,
            "days_of_week": habit.days_of_week,
        })

    # Séances de musculation programmées : elles n'apparaissaient que dans le
    # fil, alors qu'une séance à heure fixe est un rendez-vous du jour au même
    # titre qu'une habitude.
    planned_workouts = []
    modeles = (
        db.query(models.WorkoutTemplate)
        .filter(models.WorkoutTemplate.user_id == user.id,
                models.WorkoutTemplate.scheduled_time.isnot(None))
        .all()
    )
    for modele in modeles:
        faite = (
            db.query(models.StrengthSession)
            .filter(models.StrengthSession.user_id == user.id,
                    models.StrengthSession.template_id == modele.id)
            .all()
        )
        planned_workouts.append({
            "id": modele.id,
            "label": modele.name,
            "scheduled_time": modele.scheduled_time,
            "done_today": any(is_same_day(s.occurred_at, now) for s in faite),
        })
    planned_workouts.sort(key=lambda w: w["scheduled_time"] or "")

    # Bilan calorique du jour, repris du fil : mangé, dépensé en sport, net et
    # reste à manger selon le budget du profil.
    profil = next((p for p in [getattr(user, "profile", None)] if p), None)
    if profil is None:
        profil = db.query(models.Profile).filter(models.Profile.user_id == user.id).first()
    budget = profil.daily_calorie_budget if profil else 2000
    repas_du_jour = [
        m for m in db.query(models.Meal).filter(models.Meal.user_id == user.id).all()
        if is_same_day(m.occurred_at, now)
    ]
    consomme = sum(m.calories for m in repas_du_jour)
    depense = calories_burned_on(db, user.id, now)
    calorie_balance = {
        "budget": budget,
        "consumed": consomme,
        "burned": depense,
        "net": consomme - depense,
        "remaining": budget - (consomme - depense),
        "meals_logged": len(repas_du_jour),
    }

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
        "planned_workouts": planned_workouts,
        "calorie_balance": calorie_balance,
        "goals_summary": goals_summary,
        "reward_budget": {"multiplier": multiplier, "reward_budget": reward_budget, "available_balance": available_balance},
        "thought_of_the_day": THOUGHTS[now.timetuple().tm_yday % len(THOUGHTS)],
    }
