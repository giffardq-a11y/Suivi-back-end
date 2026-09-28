"""module Personnage : personnage, événements de stats, paliers de santé

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-28

Première version du moteur (étapes a à c du cahier
mobile/docs/tanren-rpg/PROMPT-module-personnage.md). Pas de table cache
character_stat : la somme des stat_events suffit. Boutique, inventaire,
équipement, coffres et quêtes du jour : migrations suivantes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.schema_rattrapage import creer_table


# revision identifiers, used by Alembic.
revision: str = '0022'
down_revision: Union[str, None] = '0021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # creer_table plutôt que op.create_table : voir app/schema_rattrapage.py.
    creer_table('characters',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('universe', sa.String(), nullable=False),
    sa.Column('class_key', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('appearance', sa.JSON(), nullable=True),
    sa.Column('level', sa.Integer(), server_default='1', nullable=False),
    sa.Column('total_xp', sa.Integer(), server_default='0', nullable=False),
    sa.Column('shards', sa.Integer(), server_default='0', nullable=False),
    sa.Column('xp_avance', sa.Integer(), server_default='0', nullable=False),
    sa.Column('class_changed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('universe_changed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    creer_table('stat_events',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('source_id', sa.String(), nullable=False),
    sa.Column('stat', sa.String(), nullable=False),
    sa.Column('base_points', sa.Float(), nullable=False),
    sa.Column('class_mult', sa.Float(), nullable=False),
    sa.Column('bonus_pct', sa.Float(), nullable=False),
    sa.Column('points', sa.Float(), nullable=False),
    sa.Column('xp', sa.Integer(), nullable=False),
    sa.Column('date_key', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'source', 'source_id', 'stat', name='uq_stat_events_source')
    )
    creer_table('health_milestones',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('substance', sa.String(), nullable=False),
    sa.Column('milestone_key', sa.String(), nullable=False),
    sa.Column('quit_date', sa.String(), nullable=False),
    sa.Column('earned_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('ratio', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('health_milestones')
    op.drop_table('stat_events')
    op.drop_table('characters')
