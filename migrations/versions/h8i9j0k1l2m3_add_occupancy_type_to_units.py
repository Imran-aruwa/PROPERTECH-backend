"""Add occupancy_type column to units

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-02-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h8i9j0k1l2m3'
down_revision: Union[str, None] = 'g7h8i9j0k1l2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add occupancy_type column to units table
    op.add_column('units', sa.Column('occupancy_type', sa.String(), server_default='available', nullable=True))


def downgrade() -> None:
    # Remove occupancy_type column from units table
    op.drop_column('units', 'occupancy_type')
