"""détail des habitudes sur le tableau, au choix de chaque membre

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-17

board_members.show_habit_details : le membre montre, sur l'écran de ce
tableau, le nom de ses habitudes du jour, faites ou non, et leur progression.
Faux par défaut, y compris pour les membres déjà acceptés : ils n'ont accepté
que le résumé « Habitudes x / y ».
"""
from typing import Sequence, Union

import sqlalchemy as sa

from app.schema_rattrapage import ajouter_colonnes


# revision identifiers, used by Alembic.
revision: str = '0031'
down_revision: Union[str, None] = '0030'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ajouter_colonnes plutôt que batch_op.add_column : voir app/schema_rattrapage.py.
    ajouter_colonnes('board_members', [
        sa.Column('show_habit_details', sa.Boolean(), nullable=False, server_default=sa.false()),
    ])


def downgrade() -> None:
    from alembic import op
    with op.batch_alter_table('board_members', schema=None) as batch_op:
        batch_op.drop_column('show_habit_details')
