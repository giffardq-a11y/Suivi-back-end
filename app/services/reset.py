"""Réinitialisation de compte : deux niveaux, jamais le compte lui-même
(ni sa session) — voir services/compte.py pour la suppression complète.
Les deux niveaux notent le début du suivi ; « tout effacer » recrée en plus
le contenu par défaut d'un compte neuf (services/defauts_compte.py).

Niveau 1 (remettre_progression_a_zero) : efface l'historique et les gains
(entrées, séances, coffres, XP...) mais garde la configuration (habitudes,
substances, objectifs, réglages). Une configuration qui porte elle-même de
la progression est remise à son point de départ plutôt que supprimée :
quit_date d'une substance (sinon le streak retomberait sur une ancienne
date de départ au lieu de repartir de zéro) et départ de sa réduction
progressive, départ des habitudes progressives (retour à leur valeur de
départ), current_value/completed_at d'un objectif, total et réussite des
cagnottes, dernière occurrence des habitudes à perdre, niveau/XP/éclats du
personnage (son identité — univers, classe, apparence — reste). Le compte
note aussi le début du suivi (users.progress_reset_at, voir
common.debut_suivi) : les calculs qui repartaient de sa création ne
remontent plus avant.

Niveau 2 (tout_effacer) : reprend le graphe de clés étrangères de
supprimer_utilisateur (compte.py), en épargnant users, refresh_tokens et
account_tokens — le compte et la session en cours restent valides.
"""
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .. import models
from ..database import Base
from .common import jour_du_compte, now_utc
from .compte import _condition
from .defauts_compte import creer_defauts
from .habit_progress import effective_habit_target, is_progressive
from .substance_progress import reduction_configuree

TABLES_PROGRESSION = {
    "consumption_entries", "cravings", "habit_logs", "habit_reschedules", "habit_skip_reasons",
    "meals", "meal_plan_entries", "cooking_logs",
    "runs", "other_sport_logs", "flexibility_sessions", "strength_sessions", "daily_steps",
    "sleep_logs", "water_logs",
    "mood_entries", "craving_entries", "gratitude_entries",
    "cycle_logs", "cycle_flow_entries",
    "weight_entries", "body_fat_entries", "body_composition_entries", "daily_heart_rates",
    "expenses", "savings_transfers",
    "flash_card_reviews", "flash_card_events",
    "reward_purchases",
    "stat_events", "health_milestones", "inventory_items", "equipped_items", "chests", "daily_quests",
}

# Le compte doit rester utilisable après un « tout effacer » : session et
# connexion préservées.
TABLES_EPARGNEES_TOUT_EFFACER = {"users", "refresh_tokens", "account_tokens"}


def _supprimer(db: Session, user_id: str, noms_tables: set[str]) -> dict[str, int]:
    # Les conditions se calculent sur TOUTES les tables (même celles qu'on ne
    # supprime pas) : une table du périmètre peut dépendre par clé étrangère
    # d'une table hors périmètre (ex. habit_logs -> habits) — voir le
    # docstring de _condition dans compte.py.
    conditions: dict = {}
    toutes = [t for t in Base.metadata.sorted_tables if t.name != "users"]
    for table in toutes:
        _condition(table, user_id, conditions)

    compte: dict[str, int] = {}
    for table in reversed(toutes):
        if table.name not in noms_tables:
            continue
        condition = conditions.get(table.name)
        if condition is None:
            continue
        n = db.execute(delete(table).where(condition)).rowcount
        if n:
            compte[table.name] = n
    return compte


def remettre_progression_a_zero(db: Session, user_id: str) -> dict[str, int]:
    compte = _supprimer(db, user_id, TABLES_PROGRESSION)

    maintenant = now_utc()
    # Les jours se découpent comme partout dans le compte (jour_du_compte, UTC).
    aujourdhui = jour_du_compte(maintenant)

    # Début du suivi : tout calcul qui repartait de la création du compte
    # (calendrier, record, bénéfices...) repart d'ici.
    user = db.get(models.User, user_id)
    if user:
        user.progress_reset_at = maintenant

    for substance in db.query(models.Substance).filter(models.Substance.user_id == user_id).all():
        substance.quit_date = aujourdhui.isoformat()
        # Réduction progressive : retour au palier 1 (limite = valeur de départ).
        if reduction_configuree(substance):
            substance.reduction_start_date = aujourdhui

    for habit in db.query(models.Habit).filter(models.Habit.user_id == user_id).all():
        # Habitude progressive : retour à sa valeur de départ (semaine 1), avec
        # le même calcul qu'à la création (routers/habits.py::create_habit).
        if is_progressive(habit):
            habit.progressive_start_date = maintenant
            habit.target = effective_habit_target(habit, maintenant)

    for goal in db.query(models.Goal).filter(models.Goal.user_id == user_id).all():
        goal.current_value = 0
        goal.completed_at = None

    # Cagnottes : les versements sont effacés (savings_transfers), le total
    # qu'ils alimentaient aussi.
    for cagnotte in db.query(models.SavingsPot).filter(models.SavingsPot.user_id == user_id).all():
        cagnotte.current_amount = 0
        cagnotte.achieved_at = None

    # Habitudes à perdre : le compteur de jours repart de zéro, comme quit_date
    # pour les substances.
    for mauvaise in db.query(models.BadHabit).filter(models.BadHabit.user_id == user_id).all():
        mauvaise.last_occurrence_at = maintenant

    character = db.query(models.Character).filter(models.Character.user_id == user_id).first()
    if character:
        character.level = 1
        character.total_xp = 0
        character.shards = 0
        character.xp_avance = 0

    db.commit()
    return compte


def tout_effacer(db: Session, user_id: str) -> dict[str, int]:
    toutes_sauf_epargnees = {
        t.name for t in Base.metadata.sorted_tables
        if t.name not in TABLES_EPARGNEES_TOUT_EFFACER and t.name != "users"
    }
    compte = _supprimer(db, user_id, toutes_sauf_epargnees)
    db.expire_all()

    user = db.get(models.User, user_id)
    if user:
        user.progress_reset_at = now_utc()
        # Les consommations suivies ont été supprimées : on recrée celles d'un
        # compte neuf, sinon l'Accueil ne pourrait plus rien enregistrer.
        creer_defauts(db, user)
    db.commit()
    return compte
