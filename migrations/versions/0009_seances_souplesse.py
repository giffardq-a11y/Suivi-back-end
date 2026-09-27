"""seances de souplesse (etirements / yoga)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.schema_rattrapage import creer_table


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # creer_table plutôt que op.create_table : voir app/schema_rattrapage.py.
    creer_table('flexibility_sessions',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('activity', sa.String(), nullable=False),
    sa.Column('zone', sa.String(), nullable=True),
    sa.Column('yoga_type', sa.String(), nullable=True),
    sa.Column('mode', sa.String(), nullable=False),
    sa.Column('planned_duration_min', sa.Float(), nullable=False),
    sa.Column('duration_min', sa.Float(), nullable=False),
    sa.Column('calories_burned', sa.Integer(), nullable=False),
    sa.Column('video_ids', sa.JSON(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('flexibility_sessions')
