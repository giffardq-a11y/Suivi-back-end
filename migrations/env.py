"""Environnement Alembic : la base visée est celle de l'app
(app.database.DATABASE_URL, donc la variable DATABASE_URL), jamais une URL
écrite dans alembic.ini."""
from logging.config import fileConfig

from alembic import context

from app.database import Base, engine, IS_SQLITE
from app import models  # noqa: F401 — enregistre toutes les tables dans Base.metadata

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=str(engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=IS_SQLITE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite ne sait pas modifier une colonne en place : Alembic
            # recrée la table ("batch") pour les futures migrations.
            render_as_batch=IS_SQLITE,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
