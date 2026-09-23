"""Mise à jour du schéma au démarrage via Alembic (migrations/).

Lancé depuis main.py plutôt qu'en commande séparée : le plan gratuit de
Render n'a ni shell ni "pre-deploy command", et une seule instance tourne.

Cas particulier : une base créée AVANT Alembic (Base.metadata.create_all +
ALTER TABLE au démarrage, jusqu'au 15/09/2026 — ex. suivi.db en local) a déjà
les tables mais pas de table alembic_version. On lui applique les derniers
ALTER de l'ancien système pour la mettre au niveau de la révision 0001, puis
on la marque comme telle ("stamp") au lieu de recréer les tables.

Le create_all ci-dessous crée TOUTES les tables du modèle actuel, alors que le
tampon posé est 0001 : les migrations suivantes rejoueraient donc des
créations déjà faites. C'est ce qui avait bloqué la base de dev au démarrage
(« table flash_cards already exists », 23/09/2026). Elles passent depuis par
les helpers de app/schema_rattrapage.py, qui ignorent ce qui existe déjà.
"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from .database import engine

BACKEND_DIR = Path(__file__).resolve().parent.parent
BASELINE_REVISION = "0001"

# Colonnes ajoutées après coup sous l'ancien système — chaque ALTER échoue
# sans conséquence si la colonne existe déjà.
_LEGACY_ALTERS = [
    "ALTER TABLE habits ADD COLUMN weekly_target INTEGER DEFAULT 7",
    "ALTER TABLE habits ADD COLUMN linked_activity VARCHAR",
    "ALTER TABLE habits ADD COLUMN scheduled_time VARCHAR",
    "ALTER TABLE habits ADD COLUMN notifications_enabled BOOLEAN DEFAULT false",
    "ALTER TABLE habits ADD COLUMN note VARCHAR",
    "ALTER TABLE habits ADD COLUMN habit_type VARCHAR",
    "ALTER TABLE habits ADD COLUMN progressive_rhythm VARCHAR",
    "ALTER TABLE habits ADD COLUMN progressive_start_value FLOAT",
    "ALTER TABLE habits ADD COLUMN progressive_target_value FLOAT",
    "ALTER TABLE habits ADD COLUMN progressive_start_date TIMESTAMPTZ",
    "ALTER TABLE substances ADD COLUMN unit VARCHAR",
    "ALTER TABLE substances ADD COLUMN note VARCHAR",
    "ALTER TABLE goals ADD COLUMN linked_type VARCHAR",
    "ALTER TABLE goals ADD COLUMN linked_habit_id VARCHAR",
    "ALTER TABLE goals ADD COLUMN linked_exercise_name VARCHAR",
    "ALTER TABLE goals ADD COLUMN linked_metric VARCHAR",
    "ALTER TABLE consumption_entries ADD COLUMN price FLOAT",
    "ALTER TABLE habit_logs ADD COLUMN note VARCHAR",
]


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # Garde la config de logs d'uvicorn intacte quand on migre au démarrage.
    cfg.attributes["configure_logger"] = False
    return cfg


def _bring_legacy_database_to_baseline() -> None:
    from .database import Base
    from . import models  # noqa: F401

    # Tables apparues sous l'ancien système mais absentes de cette base.
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        for stmt in _LEGACY_ALTERS:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                conn.rollback()


def run_migrations() -> None:
    cfg = _alembic_config()
    tables = set(inspect(engine).get_table_names())
    if "users" in tables and "alembic_version" not in tables:
        _bring_legacy_database_to_baseline()
        command.stamp(cfg, BASELINE_REVISION)
    command.upgrade(cfg, "head")
