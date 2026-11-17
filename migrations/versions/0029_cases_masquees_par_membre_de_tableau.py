"""cases masquées par membre de tableau (board_members.hidden_categories)

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-16

Chaque membre accepté d'un tableau choisit lesquelles de ses cases s'affichent
sur l'écran : liste JSON des clés masquées, NULL ou [] = rien de masqué. Colonne
nouvelle et nullable : rien ne change pour l'existant.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from app.schema_rattrapage import ajouter_colonnes


# revision identifiers, used by Alembic.
revision: str = '0029'
down_revision: Union[str, None] = '0028'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ajouter_colonnes plutôt que batch_op.add_column : voir app/schema_rattrapage.py.
    ajouter_colonnes('board_members', [sa.Column('hidden_categories', sa.JSON(), nullable=True)])


def downgrade() -> None:
    from alembic import op
    with op.batch_alter_table('board_members', schema=None) as batch_op:
        batch_op.drop_column('hidden_categories')
