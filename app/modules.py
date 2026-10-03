"""Registre des modules activables (côté serveur).

L'utilisateur choisit ses modules à l'inscription ; seuls ceux-là apparaissent
dans l'app (registre miroir côté mobile : mobile/src/modules/registre.js).
Désactiver un module le masque et garde ses données ; « supprimer les données
du module » les efface (important pour les données de santé : cycle, humeur,
sommeil, consommations).

Chaque table appartient soit à un module, soit au SOCLE (toujours actif) :
tests/test_modules.py vérifie qu'aucune table n'est oubliée, pour qu'une table
ajoutée plus tard ne passe pas à travers la suppression par module.
"""
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .database import Base

MODULES: dict[str, dict] = {
    "addictions": {"label": "Alcool et tabac",
                   "tables": ["substances", "consumption_entries", "bad_habits", "cravings"]},
    "habitudes": {"label": "Habitudes",
                  "tables": ["habits", "habit_logs", "habit_reschedules", "habit_skip_reasons"]},
    "sport": {"label": "Sport",
              "tables": ["runs", "strength_sessions", "other_sport_logs", "flexibility_sessions",
                         "workout_templates", "daily_steps"]},
    "nutrition": {"label": "Nutrition",
                  "tables": ["meals", "meal_plan_entries", "pantry_items", "cooking_logs"]},
    "cycle": {"label": "Cycle",
              "tables": ["cycle_settings", "cycle_logs", "cycle_flow_entries"]},
    "langues": {"label": "Langues",
                "tables": ["flash_cards", "flash_card_reviews", "flash_card_events"]},
    "hydratation": {"label": "Hydratation", "tables": ["water_logs", "hydration_settings"]},
    "sommeil": {"label": "Sommeil", "tables": ["sleep_logs", "sleep_settings"]},
    "humeur": {"label": "Humeur et journal",
               "tables": ["mood_entries", "craving_entries", "gratitude_entries"]},
    "budget": {"label": "Budget",
               "tables": ["expenses", "budget_categories", "savings_pots", "savings_transfers"]},
    # Supprimer ses données efface le personnage, ses points, ses paliers de
    # santé, son inventaire, son équipement, ses coffres et ses quêtes ; les
    # actions d'origine (séances, habitudes...) restent.
    "personnage": {"label": "Personnage",
                   "tables": ["characters", "stat_events", "health_milestones", "inventory_items",
                              "equipped_items", "chests", "daily_quests"]},
}

# Toujours actif, jamais supprimé par module (seulement avec le compte).
SOCLE = {
    "users", "profiles", "weight_entries", "body_fat_entries", "goals", "rewards", "reward_purchases",
    "partner_links", "partner_reminders", "report_settings", "external_integrations",
    "account_tokens", "refresh_tokens",
}

TOUS = list(MODULES)


def modules_actifs(user) -> list[str]:
    """NULL (compte créé avant les modules) = tout actif : on ne retire rien
    à un utilisateur existant. Les clés inconnues sont ignorées."""
    actifs = user.enabled_modules
    if actifs is None:
        return list(TOUS)
    return [m for m in actifs if m in MODULES]


def est_actif(user, module: str) -> bool:
    return module in modules_actifs(user)


def supprimer_donnees(db: Session, user_id: str, module: str) -> dict[str, int]:
    """Efface les lignes de l'utilisateur dans les tables du module, des
    tables filles vers les tables mères. Les lignes partagées sans
    propriétaire (modèles de séance et deck livrés avec l'app, user_id NULL)
    ne sont pas touchées."""
    from .services.compte import _condition

    noms = set(MODULES[module]["tables"])
    tables = [t for t in Base.metadata.sorted_tables if t.name in noms]
    conditions: dict = {}
    for t in Base.metadata.sorted_tables:
        if t.name != "users":
            _condition(t, user_id, conditions)
    compte = {}
    for table in reversed(tables):
        condition = conditions.get(table.name)
        if condition is None:
            continue
        n = db.execute(delete(table).where(condition)).rowcount
        if n:
            compte[table.name] = n
    db.commit()
    return compte
