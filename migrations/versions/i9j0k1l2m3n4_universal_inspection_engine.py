"""Universal Inspection Engine - templates, scoring, signatures, external inspections

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-02-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'i9j0k1l2m3n4'
down_revision = 'h8i9j0k1l2m3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # === 1. Create inspection_templates table ===
    op.create_table(
        'inspection_templates',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('inspection_type', sa.String(30), nullable=False),
        sa.Column('is_external', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('categories', sa.JSON(), nullable=True),
        sa.Column('default_items', sa.JSON(), nullable=True),
        sa.Column('scoring_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('pass_threshold', sa.Float(), nullable=True, server_default='3.0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_templates_owner', 'inspection_templates', ['owner_id'])
    op.create_index('idx_templates_type', 'inspection_templates', ['inspection_type'])

    # === 2. Add new columns to inspections ===
    op.add_column('inspections', sa.Column('is_external', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('inspections', sa.Column('template_id', sa.Uuid(), nullable=True))
    op.add_column('inspections', sa.Column('overall_score', sa.Float(), nullable=True))
    op.add_column('inspections', sa.Column('pass_fail', sa.String(10), nullable=True))
    op.add_column('inspections', sa.Column('inspector_name', sa.String(255), nullable=True))
    op.add_column('inspections', sa.Column('inspector_credentials', sa.String(500), nullable=True))
    op.add_column('inspections', sa.Column('inspector_company', sa.String(255), nullable=True))
    op.add_column('inspections', sa.Column('report_url', sa.String(500), nullable=True))

    # FK for template_id
    op.create_foreign_key(
        'fk_inspections_template_id', 'inspections', 'inspection_templates',
        ['template_id'], ['id']
    )
    op.create_index('idx_inspections_is_external', 'inspections', ['is_external'])

    # === 3. Add new columns to inspection_items ===
    op.add_column('inspection_items', sa.Column('score', sa.Integer(), nullable=True))
    op.add_column('inspection_items', sa.Column('severity', sa.String(10), nullable=True))
    op.add_column('inspection_items', sa.Column('pass_fail', sa.String(10), nullable=True))
    op.add_column('inspection_items', sa.Column('requires_followup', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('inspection_items', sa.Column('photo_required', sa.Boolean(), nullable=True, server_default='false'))

    # === 4. Create inspection_signatures table ===
    op.create_table(
        'inspection_signatures',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('inspection_id', sa.Uuid(), sa.ForeignKey('inspections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('signer_id', sa.Uuid(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('signer_name', sa.String(255), nullable=False),
        sa.Column('signer_role', sa.String(50), nullable=False),
        sa.Column('signature_type', sa.String(20), nullable=False),
        sa.Column('signature_data', sa.Text(), nullable=False),
        sa.Column('signed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('device_fingerprint', sa.String(255), nullable=True),
        sa.Column('gps_lat', sa.Numeric(10, 8), nullable=True),
        sa.Column('gps_lng', sa.Numeric(11, 8), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_signatures_inspection', 'inspection_signatures', ['inspection_id'])


def downgrade() -> None:
    op.drop_table('inspection_signatures')

    op.drop_column('inspection_items', 'photo_required')
    op.drop_column('inspection_items', 'requires_followup')
    op.drop_column('inspection_items', 'pass_fail')
    op.drop_column('inspection_items', 'severity')
    op.drop_column('inspection_items', 'score')

    op.drop_constraint('fk_inspections_template_id', 'inspections', type_='foreignkey')
    op.drop_index('idx_inspections_is_external', 'inspections')
    op.drop_column('inspections', 'report_url')
    op.drop_column('inspections', 'inspector_company')
    op.drop_column('inspections', 'inspector_credentials')
    op.drop_column('inspections', 'inspector_name')
    op.drop_column('inspections', 'pass_fail')
    op.drop_column('inspections', 'overall_score')
    op.drop_column('inspections', 'template_id')
    op.drop_column('inspections', 'is_external')

    op.drop_table('inspection_templates')
