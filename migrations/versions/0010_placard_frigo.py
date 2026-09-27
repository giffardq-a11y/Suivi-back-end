"""placard / frigo : articles en stock et recettes cuisinees

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.schema_rattrapage import creer_table


# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # creer_table plutôt que op.create_table : voir app/schema_rattrapage.py.
    creer_table('pantry_items',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('ingredient_key', sa.String(), nullable=True),
    sa.Column('label', sa.String(), nullable=False),
    sa.Column('location', sa.String(), nullable=False),
    sa.Column('level', sa.String(), nullable=True),
    sa.Column('packages', sa.Integer(), server_default='1', nullable=False),
    sa.Column('quantity_g', sa.Float(), nullable=True),
    sa.Column('source', sa.String(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    creer_table('cooking_logs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('recipe_id', sa.String(), nullable=False),
    sa.Column('recipe_name', sa.String(), nullable=True),
    sa.Column('portions', sa.Float(), nullable=False),
    sa.Column('changes', sa.JSON(), nullable=False),
    sa.Column('undone', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('cooking_logs')
    op.drop_table('pantry_items')
