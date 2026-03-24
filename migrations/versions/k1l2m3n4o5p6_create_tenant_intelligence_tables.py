"""Create tenant intelligence tables

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-03-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'k1l2m3n4o5p6'
down_revision = 'j0k1l2m3n4o5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── tenant_profiles ──────────────────────────────────────────────────────
    op.create_table(
        'tenant_profiles',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('owner_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('unit_id', sa.Uuid(), sa.ForeignKey('units.id', ondelete='SET NULL'), nullable=True),
        sa.Column('property_id', sa.Uuid(), sa.ForeignKey('properties.id', ondelete='SET NULL'), nullable=True),
        sa.Column('health_score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('health_grade', sa.String(2), nullable=True),
        sa.Column('payment_score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('maintenance_score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('compliance_score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('communication_score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('risk_level', sa.String(20), nullable=False, server_default='medium'),
        sa.Column('risk_flags', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('profile_summary', sa.Text(), nullable=True),
        sa.Column('last_computed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('total_payments_made', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_payments_on_time', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_payments_late', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_payments_missed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_days_late', sa.Numeric(5, 2), nullable=False, server_default='0'),
        sa.Column('total_maintenance_requests', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('maintenance_nuisance_score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('lease_violations', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('inspection_issues_caused', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('months_tenanted', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'owner_id', name='uq_tenant_profile_tenant_owner'),
    )
    op.create_index('idx_tenant_profiles_tenant', 'tenant_profiles', ['tenant_id'])
    op.create_index('idx_tenant_profiles_owner', 'tenant_profiles', ['owner_id'])
    op.create_index('idx_tenant_profiles_risk', 'tenant_profiles', ['owner_id', 'risk_level'])
    op.create_index('idx_tenant_profiles_score', 'tenant_profiles', ['owner_id', 'health_score'])

    # ── tenant_events ────────────────────────────────────────────────────────
    op.create_table(
        'tenant_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('owner_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('event_data', postgresql.JSONB(), nullable=True),
        sa.Column('impact_score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_tenant_events_tenant', 'tenant_events', ['tenant_id'])
    op.create_index('idx_tenant_events_owner', 'tenant_events', ['owner_id'])
    op.create_index('idx_tenant_events_type', 'tenant_events', ['tenant_id', 'event_type'])
    op.create_index('idx_tenant_events_date', 'tenant_events', ['tenant_id', 'event_date'])

    # ── tenant_references ────────────────────────────────────────────────────
    op.create_table(
        'tenant_references',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('owner_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('property_id', sa.Uuid(), sa.ForeignKey('properties.id', ondelete='SET NULL'), nullable=True),
        sa.Column('unit_id', sa.Uuid(), sa.ForeignKey('units.id', ondelete='SET NULL'), nullable=True),
        sa.Column('tenancy_start', sa.Date(), nullable=False),
        sa.Column('tenancy_end', sa.Date(), nullable=True),
        sa.Column('overall_rating', sa.Integer(), nullable=False),
        sa.Column('payment_rating', sa.Integer(), nullable=False),
        sa.Column('maintenance_rating', sa.Integer(), nullable=False),
        sa.Column('would_rent_again', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('reference_notes', sa.Text(), nullable=True),
        sa.Column('is_public', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('verification_code', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_tenant_references_tenant', 'tenant_references', ['tenant_id'])
    op.create_index('idx_tenant_references_owner', 'tenant_references', ['owner_id'])

    # ── portfolio_risk_summary ────────────────────────────────────────────────
    op.create_table(
        'portfolio_risk_summary',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('total_tenants', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('low_risk_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('medium_risk_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('high_risk_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('critical_risk_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_health_score', sa.Numeric(5, 2), nullable=False, server_default='0'),
        sa.Column('tenants_flagged_for_review', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('estimated_churn_risk_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_computed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_id', name='uq_portfolio_risk_owner'),
    )
    op.create_index('idx_portfolio_risk_owner', 'portfolio_risk_summary', ['owner_id'])


def downgrade() -> None:
    op.drop_table('portfolio_risk_summary')
    op.drop_table('tenant_references')
    op.drop_table('tenant_events')
    op.drop_table('tenant_profiles')
