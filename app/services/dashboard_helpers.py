"""Extrait de routers/dashboard.py — factorisé pour être réutilisable par
GET /report (settings.py), qui a besoin du même calcul de streaks/économies/
habitudes du jour pour construire le message récap."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models
from ..modules import est_actif, modules_actifs
from .streaks import current_streak_days, personal_best_days
from .savings import compute_savings
from .rewards import compute_reward_budget
from .common import start_of_week, is_same_day
from .habit_progress import (
    effective_habit_target, jours_actifs, jours_valides, bande_semaine,
    serie_jours, serie_semaines, semaine_du_plan,
)
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

    # Un module désactivé masque ses sections (les données restent en base,
    # voir modules.py) : chaque bloc ci-dessous est gardé par est_actif().
    modules_utilisateur = modules_actifs(user)

    streaks = []
    total_savings, delta_week = 0.0, 0.0
    if est_actif(user, "addictions"):
        streaks = [
            {
                "substance_id": s.id, "label": s.label, "category": s.category.value,
                "days": current_streak_days(db, s, now=now),
                "personal_best_days": personal_best_days(db, s, now=now),
                # Consommé aujourd'hui (somme des quantités) : affiché sur le
                # bouton « +1 » de l'Accueil, mis à jour en optimiste côté app.
                # Filtre de date en Python : SQLite rend des dates naïves
                # (même garde que pour les habitudes plus bas).
                "today_count": round(sum(
                    (e.quantity or 1) for e in db.query(models.ConsumptionEntry).filter(
                        models.ConsumptionEntry.substance_id == s.id,
                        models.ConsumptionEntry.type == models.EntryType.CONSUMPTION,
                    ).all()
                    if (e.occurred_at if e.occurred_at.tzinfo else e.occurred_at.replace(tzinfo=timezone.utc)) >= today_start
                ), 1),
            }
            for s in user.substances
        ]
        total_savings, delta_week = compute_savings(db, user, now=now)

    habits_today = []
    if est_actif(user, "habitudes"):
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
            # se lit pas en « fait / pas fait aujourd'hui ». Une habitude en mode
            # 'volume' (ex. 20 km/semaine) porte sa cible dans weekly_volume_target,
            # pas weekly_target -- AddHabitScreen.js envoie explicitement
            # weekly_target=null (donc 7 par défaut côté serveur, voir client.js)
            # pour ce mode. Sans ce branchement, cible restait à 7, weekly valait
            # toujours False et ces habitudes n'affichaient jamais le compteur sur
            # l'Accueil, alors qu'il apparaît bien dans l'onglet Habitudes (même
            # logique que _serialize() dans routers/habits.py).
            logs_semaine = [
                log for log in habit.logs
                if (log.occurred_at if log.occurred_at.tzinfo else log.occurred_at.replace(tzinfo=timezone.utc)) >= semaine_debut
            ]
            if habit.tracking_mode == "volume" and habit.weekly_volume_target:
                faites = round(sum(
                    (log.quantity if log.quantity is not None else (habit.session_quantity or 0))
                    for log in logs_semaine
                ), 1)
                cible = habit.weekly_volume_target
                weekly = True
            else:
                faites = len(logs_semaine)
                cible = habit.weekly_target or 7
                weekly = cible < 7
            # Carte d'habitude : bande des 7 jours, série (en jours pour une
            # habitude quotidienne, en semaines atteintes sinon) et semaine du
            # plan pour une habitude progressive à durée explicite.
            faits = jours_valides(habit.logs)
            semaine_plan, semaines_plan = semaine_du_plan(habit, now)
            habits_today.append({
                "id": habit.id, "label": habit.label,
                "target": effective_habit_target(habit, now), "done_today": done_today,
                "done_this_week": faites, "weekly_target": cible, "weekly": weekly,
                "days_of_week": habit.days_of_week,
                "unit": habit.unit if habit.tracking_mode == "volume" else None,
                "week_days": bande_semaine(habit, faits, now, hebdo=weekly),
                "streak": serie_semaines(habit.logs, habit, now) if weekly else serie_jours(habit, faits, now),
                "streak_unit": "weeks" if weekly else "days",
                "plan_week": semaine_plan, "plan_weeks": semaines_plan,
            })

    # Séances de musculation programmées : elles n'apparaissaient que dans le
    # fil, alors qu'une séance à heure fixe est un rendez-vous du jour au même
    # titre qu'une habitude.
    planned_workouts = []
    if est_actif(user, "sport"):
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
    # reste à manger selon le budget du profil. Section rattachée à la
    # nutrition (repas) : sans ce module, pas de bilan à afficher.
    calorie_balance = None
    if est_actif(user, "nutrition"):
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
        "enabled_modules": modules_utilisateur,
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
