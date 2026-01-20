"""Add missing payment columns (payment_type, tenant_id, payment_date, due_date)

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-01-21 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6g7h8i9'
down_revision: Union[str, None] = 'c3d4e5f6g7h8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the PaymentType enum first
    payment_type_enum = sa.Enum(
        'rent', 'water', 'electricity', 'garbage', 'deposit',
        'maintenance', 'penalty', 'subscription', 'one_off',
        name='paymenttype'
    )
    payment_type_enum.create(op.get_bind(), checkfirst=True)

    # Add missing columns to payments table
    op.add_column('payments', sa.Column('payment_type',
        sa.Enum('rent', 'water', 'electricity', 'garbage', 'deposit',
                'maintenance', 'penalty', 'subscription', 'one_off',
                name='paymenttype'),
        nullable=True))

    op.add_column('payments', sa.Column('tenant_id', sa.Uuid(), nullable=True))
    op.add_column('payments', sa.Column('payment_date', sa.DateTime(), nullable=True))
    op.add_column('payments', sa.Column('due_date', sa.DateTime(), nullable=True))

    # Set default payment_type for existing rows
    op.execute("UPDATE payments SET payment_type = 'subscription' WHERE payment_type IS NULL")


def downgrade() -> None:
    # Remove columns
    op.drop_column('payments', 'due_date')
    op.drop_column('payments', 'payment_date')
    op.drop_column('payments', 'tenant_id')
    op.drop_column('payments', 'payment_type')

    # Drop the enum type
    sa.Enum(name='paymenttype').drop(op.get_bind(), checkfirst=True)
