"""Réinitialisation de compte : deux niveaux, jamais le compte lui-même
(ni sa session) — voir services/compte.py pour la suppression complète.

Niveau 1 (remettre_progression_a_zero) : efface l'historique et les gains
(entrées, séances, coffres, XP...) mais garde la configuration (habitudes,
substances, objectifs, réglages). Une configuration qui porte elle-même de
la progression est remise à son point de départ plutôt que supprimée :
quit_date d'une substance (sinon le streak retomberait sur une ancienne
date de départ au lieu de repartir de zéro), current_value/completed_at
d'un objectif, niveau/XP/éclats du personnage (son identité — univers,
classe, apparence — reste).

Niveau 2 (tout_effacer) : reprend le graphe de clés étrangères de
supprimer_utilisateur (compte.py), en épargnant users, refresh_tokens et
account_tokens — le compte et la session en cours restent valides.
"""
from datetime import date

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .. import models
from ..database import Base
from .compte import _condition

TABLES_PROGRESSION = {
    "consumption_entries", "cravings", "habit_logs", "habit_reschedules", "habit_skip_reasons",
    "meals", "meal_plan_entries", "cooking_logs",
    "runs", "other_sport_logs", "flexibility_sessions", "strength_sessions", "daily_steps",
    "sleep_logs", "water_logs",
    "mood_entries", "craving_entries", "gratitude_entries",
    "cycle_logs", "cycle_flow_entries",
    "weight_entries", "body_fat_entries",
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

    aujourdhui = date.today().isoformat()
    for substance in db.query(models.Substance).filter(models.Substance.user_id == user_id).all():
        substance.quit_date = aujourdhui

    for goal in db.query(models.Goal).filter(models.Goal.user_id == user_id).all():
        goal.current_value = 0
        goal.completed_at = None

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
    db.commit()
    return compte
