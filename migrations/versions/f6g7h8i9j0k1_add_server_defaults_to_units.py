"""Add server defaults to unit columns and fix existing NULLs

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-02-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6g7h8i9j0k1'
down_revision: Union[str, None] = 'e5f6g7h8i9j0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Two-part fix:
    1. Update all existing NULL values to sensible defaults
    2. Add server_default to columns so future inserts can never be NULL
    """

    # Part 1: Fix existing NULL data
    op.execute("UPDATE units SET bedrooms = 1 WHERE bedrooms IS NULL")
    op.execute("UPDATE units SET bathrooms = 1 WHERE bathrooms IS NULL")
    op.execute("UPDATE units SET toilets = 1 WHERE toilets IS NULL")
    op.execute("UPDATE units SET square_feet = 500 WHERE square_feet IS NULL")
    op.execute("UPDATE units SET monthly_rent = 0 WHERE monthly_rent IS NULL")
    op.execute("UPDATE units SET status = 'vacant' WHERE status IS NULL")
    op.execute("UPDATE units SET has_master_bedroom = false WHERE has_master_bedroom IS NULL")
    op.execute("UPDATE units SET has_servant_quarters = false WHERE has_servant_quarters IS NULL")
    op.execute("UPDATE units SET sq_bathrooms = 0 WHERE sq_bathrooms IS NULL")

    # Part 2: Add server_default so the database itself enforces defaults
    op.alter_column('units', 'bedrooms', server_default='1')
    op.alter_column('units', 'bathrooms', server_default='1')
    op.alter_column('units', 'toilets', server_default='1')
    op.alter_column('units', 'square_feet', server_default='500')
    op.alter_column('units', 'monthly_rent', server_default='0')
    op.alter_column('units', 'status', server_default='vacant')
    op.alter_column('units', 'has_master_bedroom', server_default='false')
    op.alter_column('units', 'has_servant_quarters', server_default='false')
    op.alter_column('units', 'sq_bathrooms', server_default='0')


def downgrade() -> None:
    """Remove server defaults (data changes are not reverted)"""
    op.alter_column('units', 'bedrooms', server_default=None)
    op.alter_column('units', 'bathrooms', server_default=None)
    op.alter_column('units', 'toilets', server_default=None)
    op.alter_column('units', 'square_feet', server_default=None)
    op.alter_column('units', 'monthly_rent', server_default=None)
    op.alter_column('units', 'status', server_default=None)
    op.alter_column('units', 'has_master_bedroom', server_default=None)
    op.alter_column('units', 'has_servant_quarters', server_default=None)
    op.alter_column('units', 'sq_bathrooms', server_default=None)
