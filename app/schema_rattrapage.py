"""Rendre les migrations rejouables sur une base déjà « rattrapée ».

Une base créée AVANT Alembic (Base.metadata.create_all + ALTER au démarrage,
jusqu'au 15/09/2026) est remise à niveau par app/migrate.py avec un
create_all() — qui crée **toutes** les tables du modèle actuel, pas seulement
celles de la révision 0001 sur laquelle elle est ensuite tamponnée. Les
migrations suivantes rejouent alors la création de tables déjà présentes et
plantent au démarrage sur « table flash_cards already exists » (constaté le
23/09/2026 sur la base de dev suivi.db, restée bloquée en 0002).

D'où ces deux helpers : une migration qui les utilise crée ce qui manque et
ignore ce qui existe déjà. Sur une base neuve, le comportement est
rigoureusement le même qu'un op.create_table / op.add_column direct.

Rangé dans app/ et pas dans migrations/ : les fichiers de migration sont
chargés isolément par Alembic, et `app` est le seul paquet dont l'import est
garanti à ce moment-là (migrations/env.py importe déjà app.database).
"""
import sqlalchemy as sa
from alembic import op


def _inspecteur():
    return sa.inspect(op.get_bind())


def table_existe(nom: str) -> bool:
    return nom in _inspecteur().get_table_names()


def creer_table(nom: str, *definition, **kwargs) -> None:
    """op.create_table, sauf si la table est déjà là."""
    if table_existe(nom):
        return
    op.create_table(nom, *definition, **kwargs)


def ajouter_colonnes(table: str, colonnes: list) -> None:
    """Ajoute les colonnes absentes de `table` (liste de sa.Column).

    Ne fait rien si la table n'existe pas : elle sera créée avec ses colonnes
    par la migration qui la crée. Passe par batch_alter_table, indispensable
    sur SQLite pour les contraintes."""
    if not table_existe(table):
        return
    existantes = {c["name"] for c in _inspecteur().get_columns(table)}
    manquantes = [c for c in colonnes if c.name not in existantes]
    if not manquantes:
        return
    with op.batch_alter_table(table, schema=None) as batch_op:
        for colonne in manquantes:
            batch_op.add_column(colonne)
