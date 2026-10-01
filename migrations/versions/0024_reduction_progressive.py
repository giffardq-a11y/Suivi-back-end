"""réduction progressive des consommations (substances.reduction_*)

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-01

Limite de départ par jour, baisse par semaine et date de départ. La limite du
jour n'est pas stockée : recalculée à la lecture (app/services/
substance_progress.py). Colonnes nullables : rien ne change pour les
consommations existantes, sans réduction configurée.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.schema_rattrapage import ajouter_colonnes


# revision identifiers, used by Alembic.
revision: str = '0024'
down_revision: Union[str, None] = '0023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    ajouter_colonnes('substances', [
        sa.Column('reduction_start_value', sa.Float(), nullable=True),
        sa.Column('reduction_step_per_week', sa.Float(), nullable=True),
        sa.Column('reduction_start_date', sa.Date(), nullable=True),
    ])


def downgrade() -> None:
    with op.batch_alter_table('substances') as batch:
        batch.drop_column('reduction_start_date')
        batch.drop_column('reduction_step_per_week')
        batch.drop_column('reduction_start_value')
