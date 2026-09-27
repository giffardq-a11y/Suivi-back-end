"""jetons de rafraichissement revocables (rotation, deconnexion)

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-27

Le chiffrement des jetons OAuth (external_integrations) ne demande pas de
changement de schéma : colonnes texte inchangées, valeurs chiffrées au
démarrage par main._chiffrer_jetons_oauth.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.schema_rattrapage import creer_table


# revision identifiers, used by Alembic.
revision: str = '0012'
down_revision: Union[str, None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # creer_table plutôt que op.create_table : voir app/schema_rattrapage.py.
    creer_table('refresh_tokens',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('replaced_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('refresh_tokens')
