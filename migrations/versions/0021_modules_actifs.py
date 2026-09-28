"""modules actifs par utilisateur (users.enabled_modules)

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-27

Les comptes existants reçoivent explicitement tous les modules existants à
cette date : rien ne leur est retiré, et un module ajouté plus tard (ex.
Personnage) ne s'activera pas tout seul chez eux.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.schema_rattrapage import ajouter_colonnes


# revision identifiers, used by Alembic.
revision: str = '0021'
down_revision: Union[str, None] = '0020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MODULES_AU_27_09_2026 = ["addictions", "habitudes", "sport", "nutrition", "cycle", "langues",
                         "hydratation", "sommeil", "humeur", "budget"]


def upgrade() -> None:
    ajouter_colonnes('users', [sa.Column('enabled_modules', sa.JSON(), nullable=True)])
    op.execute(
        sa.text("UPDATE users SET enabled_modules = :v WHERE enabled_modules IS NULL")
        .bindparams(sa.bindparam("v", value=MODULES_AU_27_09_2026, type_=sa.JSON))
    )


def downgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.drop_column('enabled_modules')
