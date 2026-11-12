"""balance connectée et montre : masse grasse, composition, phases du sommeil, fréquence cardiaque

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-11

Import Health Connect étendu : `body_fat_entries` gagne source et external_id
(anti-doublon), `sleep_logs` les minutes par phase de sommeil, et deux tables
nouvelles reçoivent la composition corporelle (`body_composition_entries`) et
la fréquence cardiaque journalière (`daily_heart_rates`). Colonnes toutes
facultatives : rien ne change pour l'existant.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from app.schema_rattrapage import ajouter_colonnes, creer_table


# revision identifiers, used by Alembic.
revision: str = '0027'
down_revision: Union[str, None] = '0026'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    ajouter_colonnes('body_fat_entries', [
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('external_id', sa.String(), nullable=True),
    ])
    ajouter_colonnes('sleep_logs', [
        sa.Column('awake_min', sa.Float(), nullable=True),
        sa.Column('light_min', sa.Float(), nullable=True),
        sa.Column('deep_min', sa.Float(), nullable=True),
        sa.Column('rem_min', sa.Float(), nullable=True),
    ])
    creer_table('body_composition_entries',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('lean_mass_kg', sa.Float(), nullable=True),
    sa.Column('bone_mass_kg', sa.Float(), nullable=True),
    sa.Column('bmr_kcal', sa.Float(), nullable=True),
    sa.Column('source', sa.String(), nullable=True),
    sa.Column('external_id', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    creer_table('daily_heart_rates',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('date_key', sa.String(), nullable=False),
    sa.Column('resting_bpm', sa.Integer(), nullable=True),
    sa.Column('avg_bpm', sa.Integer(), nullable=True),
    sa.Column('min_bpm', sa.Integer(), nullable=True),
    sa.Column('max_bpm', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    from alembic import op
    op.drop_table('daily_heart_rates')
    op.drop_table('body_composition_entries')
    with op.batch_alter_table('sleep_logs', schema=None) as batch_op:
        batch_op.drop_column('rem_min')
        batch_op.drop_column('deep_min')
        batch_op.drop_column('light_min')
        batch_op.drop_column('awake_min')
    with op.batch_alter_table('body_fat_entries', schema=None) as batch_op:
        batch_op.drop_column('external_id')
        batch_op.drop_column('source')
