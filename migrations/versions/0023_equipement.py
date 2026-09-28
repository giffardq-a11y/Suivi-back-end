"""module Personnage : inventaire, équipement, coffres, quêtes du jour

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-28

Suite du module Personnage (§5-6 du cahier
mobile/docs/tanren-rpg/PROMPT-module-personnage.md). Le catalogue d'objets
n'est pas en base : app/data/personnage/catalogue_equipement.json.
chests.ref (absent du cahier) rend la création des coffres idempotente.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.schema_rattrapage import creer_table


# revision identifiers, used by Alembic.
revision: str = '0023'
down_revision: Union[str, None] = '0022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # creer_table plutôt que op.create_table : voir app/schema_rattrapage.py.
    creer_table('inventory_items',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('universe', sa.String(), nullable=False),
    sa.Column('item_key', sa.String(), nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('acquired_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'universe', 'item_key', name='uq_inventory_items_objet')
    )
    creer_table('equipped_items',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('universe', sa.String(), nullable=False),
    sa.Column('slot', sa.String(), nullable=False),
    sa.Column('item_key', sa.String(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'universe', 'slot', name='uq_equipped_items_slot')
    )
    creer_table('chests',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('ref', sa.String(), nullable=False),
    sa.Column('earned_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('contents', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'kind', 'ref', name='uq_chests_ref')
    )
    creer_table('daily_quests',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('date_key', sa.String(), nullable=False),
    sa.Column('quest_key', sa.String(), nullable=False),
    sa.Column('xp', sa.Integer(), nullable=False),
    sa.Column('done_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'date_key', 'quest_key', name='uq_daily_quests_jour')
    )


def downgrade() -> None:
    op.drop_table('daily_quests')
    op.drop_table('chests')
    op.drop_table('equipped_items')
    op.drop_table('inventory_items')
