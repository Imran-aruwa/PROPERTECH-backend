"""Populate NULL values with sensible defaults

This migration populates NULL values in various tables with sensible defaults
to ensure the frontend can display meaningful data.

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-02-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from datetime import datetime


# revision identifiers, used by Alembic.
revision: str = 'e5f6g7h8i9j0'
down_revision: Union[str, None] = 'd4e5f6g7h8i9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Populate NULL values with sensible defaults"""

    # Get database dialect to handle PostgreSQL vs SQLite differences
    bind = op.get_bind()
    dialect = bind.dialect.name

    # =====================================================
    # PAYMENTS TABLE
    # =====================================================

    # Set payment_type to 'subscription' for NULL values (if not already done)
    if dialect == 'postgresql':
        op.execute("""
            UPDATE payments
            SET payment_type = 'subscription'
            WHERE payment_type IS NULL
        """)
    else:
        op.execute("""
            UPDATE payments
            SET payment_type = 'subscription'
            WHERE payment_type IS NULL
        """)

    # Set payment_date to paid_at for completed payments, or created_at otherwise
    if dialect == 'postgresql':
        op.execute("""
            UPDATE payments
            SET payment_date = COALESCE(paid_at, created_at)
            WHERE payment_date IS NULL
        """)
    else:
        op.execute("""
            UPDATE payments
            SET payment_date = COALESCE(paid_at, created_at)
            WHERE payment_date IS NULL
        """)

    # Set due_date to created_at + 30 days for payments without due_date
    if dialect == 'postgresql':
        op.execute("""
            UPDATE payments
            SET due_date = created_at + INTERVAL '30 days'
            WHERE due_date IS NULL
        """)
    else:
        op.execute("""
            UPDATE payments
            SET due_date = datetime(created_at, '+30 days')
            WHERE due_date IS NULL
        """)

    # Set description for payments without description
    op.execute("""
        UPDATE payments
        SET description = 'Subscription payment'
        WHERE description IS NULL
    """)

    # =====================================================
    # UNITS TABLE
    # =====================================================

    # Set default bedrooms
    op.execute("""
        UPDATE units
        SET bedrooms = 1
        WHERE bedrooms IS NULL
    """)

    # Set default bathrooms
    op.execute("""
        UPDATE units
        SET bathrooms = 1
        WHERE bathrooms IS NULL
    """)

    # Set default square_feet
    op.execute("""
        UPDATE units
        SET square_feet = 500
        WHERE square_feet IS NULL
    """)

    # Set default monthly_rent (15000 KES is common in Kenya)
    op.execute("""
        UPDATE units
        SET monthly_rent = 15000
        WHERE monthly_rent IS NULL
    """)

    # Set default status to 'vacant' if NULL
    op.execute("""
        UPDATE units
        SET status = 'vacant'
        WHERE status IS NULL
    """)

    # Set default toilets
    op.execute("""
        UPDATE units
        SET toilets = 1
        WHERE toilets IS NULL OR toilets = 0
    """)

    # =====================================================
    # PROPERTIES TABLE
    # =====================================================

    # Set default country to Kenya
    op.execute("""
        UPDATE properties
        SET country = 'Kenya'
        WHERE country IS NULL
    """)

    # Set default city to Nairobi (most common in Kenya)
    op.execute("""
        UPDATE properties
        SET city = 'Nairobi'
        WHERE city IS NULL
    """)

    # Set default property_type to 'residential'
    op.execute("""
        UPDATE properties
        SET property_type = 'residential'
        WHERE property_type IS NULL
    """)

    # =====================================================
    # TENANTS TABLE
    # =====================================================

    # Set default deposit_amount to rent_amount if NULL or 0
    op.execute("""
        UPDATE tenants
        SET deposit_amount = rent_amount
        WHERE (deposit_amount IS NULL OR deposit_amount = 0)
        AND rent_amount IS NOT NULL
    """)

    # Set move_in_date to lease_start if NULL
    op.execute("""
        UPDATE tenants
        SET move_in_date = lease_start
        WHERE move_in_date IS NULL AND lease_start IS NOT NULL
    """)

    # Set balance_due to 0 if NULL
    op.execute("""
        UPDATE tenants
        SET balance_due = 0
        WHERE balance_due IS NULL
    """)

    # Set lease_duration_months to 12 if NULL
    op.execute("""
        UPDATE tenants
        SET lease_duration_months = 12
        WHERE lease_duration_months IS NULL
    """)

    # Calculate lease_end from lease_start + lease_duration_months if NULL
    if dialect == 'postgresql':
        op.execute("""
            UPDATE tenants
            SET lease_end = lease_start + (lease_duration_months || ' months')::INTERVAL
            WHERE lease_end IS NULL
            AND lease_start IS NOT NULL
            AND lease_duration_months IS NOT NULL
        """)
    else:
        op.execute("""
            UPDATE tenants
            SET lease_end = datetime(lease_start, '+' || lease_duration_months || ' months')
            WHERE lease_end IS NULL
            AND lease_start IS NOT NULL
            AND lease_duration_months IS NOT NULL
        """)

    # =====================================================
    # USERS TABLE
    # =====================================================

    # Set default preferred_currency to KES if NULL
    op.execute("""
        UPDATE users
        SET preferred_currency = 'KES'
        WHERE preferred_currency IS NULL
    """)

    # Set default status to 'active' if NULL
    op.execute("""
        UPDATE users
        SET status = 'active'
        WHERE status IS NULL
    """)

    # Set default country to 'KE' if NULL
    op.execute("""
        UPDATE users
        SET country = 'KE'
        WHERE country IS NULL
    """)

    # =====================================================
    # SUBSCRIPTIONS TABLE
    # =====================================================

    # Set next_billing_date to start_date + 30 days if NULL
    if dialect == 'postgresql':
        op.execute("""
            UPDATE subscriptions
            SET next_billing_date = start_date + INTERVAL '30 days'
            WHERE next_billing_date IS NULL AND start_date IS NOT NULL
        """)
    else:
        op.execute("""
            UPDATE subscriptions
            SET next_billing_date = datetime(start_date, '+30 days')
            WHERE next_billing_date IS NULL AND start_date IS NOT NULL
        """)

    # Set default currency to KES if NULL
    op.execute("""
        UPDATE subscriptions
        SET currency = 'KES'
        WHERE currency IS NULL
    """)

    # =====================================================
    # INVOICES TABLE
    # =====================================================

    # Set due_date to issue_date + 7 days if NULL
    if dialect == 'postgresql':
        op.execute("""
            UPDATE invoices
            SET due_date = issue_date + INTERVAL '7 days'
            WHERE due_date IS NULL AND issue_date IS NOT NULL
        """)
    else:
        op.execute("""
            UPDATE invoices
            SET due_date = datetime(issue_date, '+7 days')
            WHERE due_date IS NULL AND issue_date IS NOT NULL
        """)

    # =====================================================
    # ATTENDANCE TABLE
    # =====================================================

    # Set default status to 'present' if NULL
    op.execute("""
        UPDATE attendance
        SET status = 'present'
        WHERE status IS NULL
    """)

    # Set default hours_worked to 8 if NULL
    op.execute("""
        UPDATE attendance
        SET hours_worked = 8
        WHERE hours_worked IS NULL OR hours_worked = 0
    """)

    # =====================================================
    # EQUIPMENT TABLE
    # =====================================================

    # Set default status to 'working' if NULL
    op.execute("""
        UPDATE equipment
        SET status = 'working'
        WHERE status IS NULL
    """)

    # =====================================================
    # LEADS TABLE
    # =====================================================

    # Set default status to 'new' if NULL
    op.execute("""
        UPDATE leads
        SET status = 'new'
        WHERE status IS NULL
    """)

    # =====================================================
    # VIEWINGS TABLE
    # =====================================================

    # Set default status to 'scheduled' if NULL
    op.execute("""
        UPDATE viewings
        SET status = 'scheduled'
        WHERE status IS NULL
    """)

    # =====================================================
    # MAINTENANCE_REQUESTS TABLE
    # =====================================================

    # Set default status to 'pending' if NULL
    op.execute("""
        UPDATE maintenance_requests
        SET status = 'pending'
        WHERE status IS NULL
    """)

    # Set default priority to 'medium' if NULL
    op.execute("""
        UPDATE maintenance_requests
        SET priority = 'medium'
        WHERE priority IS NULL
    """)

    # =====================================================
    # LEAVE_REQUESTS TABLE
    # =====================================================

    # Set default status to 'pending' if NULL
    op.execute("""
        UPDATE leave_requests
        SET status = 'pending'
        WHERE status IS NULL
    """)


def downgrade() -> None:
    """
    Note: Downgrade does not revert the NULL values since we don't know
    which values were originally NULL. This is intentional - data population
    is typically a one-way migration.
    """
    # No downgrade for data population migrations
    pass
