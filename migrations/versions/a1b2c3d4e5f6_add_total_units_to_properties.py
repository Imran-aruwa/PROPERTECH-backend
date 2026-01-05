"""Add total_units column to properties

Revision ID: a1b2c3d4e5f6
Revises: 74f20387d61b
Create Date: 2026-01-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '74f20387d61b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add total_units column to properties table
    op.add_column('properties', sa.Column('total_units', sa.Integer(), nullable=True, server_default='0'))


def downgrade() -> None:
    # Remove total_units column from properties table
    op.drop_column('properties', 'total_units')
