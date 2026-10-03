"""sessions d'aide au craving (table cravings) + substances.reason

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-03

Table `cravings` : une session par envie (minuteur de report, issue
déclarée : résisté / cédé / abandonné). Les statistiques ne sont pas
stockées : calculées à la lecture (app/services/cravings.py).
Colonne `substances.reason` (« Pourquoi je réduis »), rappelée sur l'écran
d'aide. Tout est nouveau ou nullable : rien ne change pour l'existant.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.schema_rattrapage import ajouter_colonnes, creer_table, table_existe


# revision identifiers, used by Alembic.
revision: str = '0025'
down_revision: Union[str, None] = '0024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    ajouter_colonnes('substances', [
        sa.Column('reason', sa.String(), nullable=True),
    ])
    # creer_table plutôt que op.create_table : voir app/schema_rattrapage.py.
    creer_table('cravings',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('substance_id', sa.String(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('planned_seconds', sa.Integer(), nullable=False),
    sa.Column('intensity_start', sa.Integer(), nullable=False),
    sa.Column('intensity_end', sa.Integer(), nullable=True),
    sa.Column('trigger_label', sa.String(), nullable=True),
    sa.Column('outcome', sa.String(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('entry_id', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['entry_id'], ['consumption_entries.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['substance_id'], ['substances.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    if table_existe('cravings'):
        index = {i['name'] for i in sa.inspect(op.get_bind()).get_indexes('cravings')}
        if op.f('ix_cravings_user_id') not in index:
            op.create_index(op.f('ix_cravings_user_id'), 'cravings', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_cravings_user_id'), table_name='cravings')
    op.drop_table('cravings')
    with op.batch_alter_table('substances') as batch:
        batch.drop_column('reason')
