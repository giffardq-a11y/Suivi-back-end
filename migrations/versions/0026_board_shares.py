"""lien de partage du tableau (table board_shares)

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-11

Table `board_shares` : au plus un lien de lecture seule par compte, pour
afficher le tableau (cases du jour, points, pesées) sur un écran sans
connexion. Seul le hachage du jeton est stocké. Table nouvelle : rien ne
change pour l'existant.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from app.schema_rattrapage import creer_table


# revision identifiers, used by Alembic.
revision: str = '0026'
down_revision: Union[str, None] = '0025'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # creer_table plutôt que op.create_table : voir app/schema_rattrapage.py.
    creer_table('board_shares',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('token_hash', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('last_read_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id'),
    sa.UniqueConstraint('token_hash')
    )


def downgrade() -> None:
    from alembic import op
    op.drop_table('board_shares')
