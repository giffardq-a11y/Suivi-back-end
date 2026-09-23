"""plan d'alimentation (semaine type) et macros sur les repas

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.schema_rattrapage import ajouter_colonnes, creer_table


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # creer_table / ajouter_colonnes plutôt que op.* : la migration doit
    # pouvoir se rejouer sur une base déjà rattrapée par create_all (voir
    # app/schema_rattrapage.py).
    creer_table(
        'meal_plan_entries',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('plan_name', sa.String(), nullable=False),
        sa.Column('day_index', sa.Integer(), nullable=False),
        sa.Column('meal_type', sa.String(), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('calories', sa.Integer(), nullable=False),
        sa.Column('proteines', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('glucides', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('lipides', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    # Les repas déjà journalisés n'ont pas de macros : 0 plutôt que NULL, pour
    # que les cumuls du jour restent une simple somme sans cas particulier.
    ajouter_colonnes('meals', [
        sa.Column(nom, sa.Integer(), nullable=False, server_default='0')
        for nom in ('proteines', 'glucides', 'lipides')
    ])


def downgrade() -> None:
    for colonne in ('lipides', 'glucides', 'proteines'):
        op.drop_column('meals', colonne)
    op.drop_table('meal_plan_entries')
