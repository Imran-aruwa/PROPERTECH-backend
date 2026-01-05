"""Add servant quarters and additional fields to units

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-01-05 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to units table
    op.add_column('units', sa.Column('toilets', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('units', sa.Column('has_master_bedroom', sa.Boolean(), nullable=True, server_default='0'))
    op.add_column('units', sa.Column('has_servant_quarters', sa.Boolean(), nullable=True, server_default='0'))
    op.add_column('units', sa.Column('sq_bathrooms', sa.Integer(), nullable=True, server_default='0'))


def downgrade() -> None:
    # Remove columns from units table
    op.drop_column('units', 'sq_bathrooms')
    op.drop_column('units', 'has_servant_quarters')
    op.drop_column('units', 'has_master_bedroom')
    op.drop_column('units', 'toilets')
