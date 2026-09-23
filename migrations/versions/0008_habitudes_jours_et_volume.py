"""habitudes : jours d'application, suivi en volume, date d'arret des consommations

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.schema_rattrapage import ajouter_colonnes


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ajouter_colonnes plutôt que op.add_column : la migration doit pouvoir se
    # rejouer sur une base déjà rattrapée par create_all (voir
    # app/schema_rattrapage.py).
    ajouter_colonnes('habits', [
        # "0,3" = lundi et jeudi ; NULL = tous les jours.
        sa.Column('days_of_week', sa.String(), nullable=True),
        sa.Column('tracking_mode', sa.String(), nullable=False, server_default='sessions'),
        sa.Column('session_quantity', sa.Float(), nullable=True),
        sa.Column('weekly_volume_target', sa.Float(), nullable=True),
        sa.Column('unit', sa.String(), nullable=True),
    ])
    ajouter_colonnes('habit_logs', [
        sa.Column('quantity', sa.Float(), nullable=True),
    ])
    ajouter_colonnes('substances', [
        sa.Column('quit_date', sa.String(), nullable=True),
    ])


def downgrade() -> None:
    op.drop_column('substances', 'quit_date')
    op.drop_column('habit_logs', 'quantity')
    for colonne in ('unit', 'weekly_volume_target', 'session_quantity', 'tracking_mode', 'days_of_week'):
        op.drop_column('habits', colonne)
