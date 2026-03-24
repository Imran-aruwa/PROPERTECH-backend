"""Add performance indexes on frequently queried foreign key and status columns

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-03-23
"""
from alembic import op

revision = 'm3n4o5p6q7r8'
down_revision = 'l2m3n4o5p6q7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_units_property_id        ON units(property_id);
        CREATE INDEX IF NOT EXISTS idx_tenants_unit_id          ON tenants(unit_id);
        CREATE INDEX IF NOT EXISTS idx_tenants_property_id      ON tenants(property_id);
        CREATE INDEX IF NOT EXISTS idx_tenants_is_active        ON tenants(status);
        CREATE INDEX IF NOT EXISTS idx_payments_user_id         ON payments(user_id);
        CREATE INDEX IF NOT EXISTS idx_payments_status          ON payments(status);
        CREATE INDEX IF NOT EXISTS idx_payments_tenant_id       ON payments(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id    ON subscriptions(user_id);
        CREATE INDEX IF NOT EXISTS idx_subscriptions_status     ON subscriptions(status);
        CREATE INDEX IF NOT EXISTS idx_maintenance_property_id  ON maintenance_requests(property_id);
        CREATE INDEX IF NOT EXISTS idx_maintenance_status       ON maintenance_requests(status);
        CREATE INDEX IF NOT EXISTS idx_properties_user_id       ON properties(user_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS idx_units_property_id;
        DROP INDEX IF EXISTS idx_tenants_unit_id;
        DROP INDEX IF EXISTS idx_tenants_property_id;
        DROP INDEX IF EXISTS idx_tenants_is_active;
        DROP INDEX IF EXISTS idx_payments_user_id;
        DROP INDEX IF EXISTS idx_payments_status;
        DROP INDEX IF EXISTS idx_payments_tenant_id;
        DROP INDEX IF EXISTS idx_subscriptions_user_id;
        DROP INDEX IF EXISTS idx_subscriptions_status;
        DROP INDEX IF EXISTS idx_maintenance_property_id;
        DROP INDEX IF EXISTS idx_maintenance_status;
        DROP INDEX IF EXISTS idx_properties_user_id;
    """)
