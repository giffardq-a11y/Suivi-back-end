"""modules supplementaires : hydratation, sommeil, humeur et journal, budget

Revision ID: 0020
Revises: 0011
Create Date: 2026-09-27

Numérotée 0020 et non 0012 : un chantier parallèle (sécurité) ajoute 0012 sur
main. La chaîne sera recâblée à la fusion (down_revision de celle qui passe
en second).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.schema_rattrapage import ajouter_colonnes, creer_table


# revision identifiers, used by Alembic.
revision: str = '0020'
down_revision: Union[str, None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # creer_table / ajouter_colonnes plutôt que op.create_table / op.add_column :
    # voir app/schema_rattrapage.py (base déjà rattrapée par create_all).

    # --- Hydratation ---
    creer_table('water_logs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('amount_ml', sa.Integer(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    creer_table('hydration_settings',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('daily_goal_ml', sa.Integer(), nullable=True),
    sa.Column('glass_sizes', sa.JSON(), nullable=False),
    sa.Column('reminders_enabled', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('reminder_start', sa.String(), nullable=True),
    sa.Column('reminder_end', sa.String(), nullable=True),
    sa.Column('reminder_interval_min', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )


def downgrade() -> None:
    op.drop_table('hydration_settings')
    op.drop_table('water_logs')
