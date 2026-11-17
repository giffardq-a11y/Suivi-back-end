"""début du suivi (users.progress_reset_at)

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-17

Date de la dernière remise à zéro de la progression. Avec la création du
compte, elle donne le début du suivi (services/common.debut_suivi) : les
séries, le calendrier et les bénéfices ne remontent pas avant. Colonne nouvelle
et nullable : rien ne change pour l'existant.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from app.schema_rattrapage import ajouter_colonnes


# revision identifiers, used by Alembic.
revision: str = '0030'
down_revision: Union[str, None] = '0029'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ajouter_colonnes plutôt que batch_op.add_column : voir app/schema_rattrapage.py.
    ajouter_colonnes('users', [sa.Column('progress_reset_at', sa.DateTime(timezone=True), nullable=True)])


def downgrade() -> None:
    from alembic import op
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('progress_reset_at')
