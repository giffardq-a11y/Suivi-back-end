"""tableaux communs (tables boards et board_members)

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-12

Un tableau commun a un nom, un créateur, des membres (invités puis acceptés)
et son propre lien d'écran. Les anciens liens (board_shares, un par compte)
sont repris en tableaux « Mon tableau » avec le même jeton, et le proche lié
qui avait lui aussi un lien y devient membre : voir
app/services/reprise_tableaux.py. board_shares est laissée en place.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.schema_rattrapage import creer_table


# revision identifiers, used by Alembic.
revision: str = '0028'
down_revision: Union[str, None] = '0027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # creer_table plutôt que op.create_table : voir app/schema_rattrapage.py.
    creer_table('boards',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('owner_id', sa.String(), nullable=False),
    sa.Column('token_hash', sa.String(), nullable=True),
    sa.Column('link_created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('legacy_share_id', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash'),
    sa.UniqueConstraint('legacy_share_id')
    )
    creer_table('board_members',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('board_id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('invited_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['board_id'], ['boards.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['invited_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('board_id', 'user_id', name='uq_board_members_board_user')
    )
    # Hors de creer_table : la reprise doit aussi passer sur une base où les
    # tables existaient déjà (elle est rejouable).
    from app.services.reprise_tableaux import reprendre
    reprendre(op.get_bind())


def downgrade() -> None:
    op.drop_table('board_members')
    op.drop_table('boards')
