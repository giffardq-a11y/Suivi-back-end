"""plan genere : semaines, recettes, portions et nombre de personnes

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.schema_rattrapage import ajouter_colonnes


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ajouter_colonnes plutôt que op.add_column : la migration doit pouvoir se
    # rejouer sur une base déjà rattrapée par create_all (voir
    # app/schema_rattrapage.py).
    ajouter_colonnes('meal_plan_entries', [
        # 0 pour un plan d'une semaine, 0..3 pour un plan d'un mois.
        sa.Column('week_index', sa.Integer(), nullable=False, server_default='0'),
        # Recette du catalogue d'où vient le repas, quand il en vient une :
        # sans elle, pas d'ingrédients donc pas de liste de courses.
        sa.Column('recipe_id', sa.String(), nullable=True),
        sa.Column('portions', sa.Float(), nullable=False, server_default='1'),
    ])
    ajouter_colonnes('profiles', [
        sa.Column('plan_start_date', sa.String(), nullable=True),
        sa.Column('plan_persons', sa.Integer(), nullable=False, server_default='1'),
    ])


def downgrade() -> None:
    for colonne in ('portions', 'recipe_id', 'week_index'):
        op.drop_column('meal_plan_entries', colonne)
    for colonne in ('plan_persons', 'plan_start_date'):
        op.drop_column('profiles', colonne)
