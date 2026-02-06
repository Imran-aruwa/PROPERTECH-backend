"""Create inspection tables

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-02-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, None] = 'f6g7h8i9j0k1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Inspections table
    op.create_table(
        'inspections',
        sa.Column('id', sa.Uuid(), nullable=False, default=sa.text('gen_random_uuid()')),
        sa.Column('client_uuid', sa.Uuid(), nullable=False),
        sa.Column('property_id', sa.Uuid(), nullable=False),
        sa.Column('unit_id', sa.Uuid(), nullable=False),
        sa.Column('performed_by_id', sa.Uuid(), nullable=False),
        sa.Column('performed_by_role', sa.String(20), nullable=False),
        sa.Column('inspection_type', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='submitted'),
        sa.Column('inspection_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('gps_lat', sa.Numeric(10, 8), nullable=True),
        sa.Column('gps_lng', sa.Numeric(11, 8), nullable=True),
        sa.Column('device_id', sa.String(255), nullable=True),
        sa.Column('offline_created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('client_uuid'),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id']),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id']),
        sa.ForeignKeyConstraint(['performed_by_id'], ['users.id']),
        sa.CheckConstraint("performed_by_role IN ('owner', 'agent', 'caretaker')", name='ck_inspections_role'),
        sa.CheckConstraint("inspection_type IN ('routine', 'move_in', 'move_out', 'meter')", name='ck_inspections_type'),
        sa.CheckConstraint("status IN ('submitted', 'reviewed', 'locked')", name='ck_inspections_status'),
    )
    op.create_index('idx_inspections_property', 'inspections', ['property_id'])
    op.create_index('idx_inspections_performed_by', 'inspections', ['performed_by_id'])
    op.create_index('idx_inspections_status', 'inspections', ['status'])

    # Inspection items table
    op.create_table(
        'inspection_items',
        sa.Column('id', sa.Uuid(), nullable=False, default=sa.text('gen_random_uuid()')),
        sa.Column('inspection_id', sa.Uuid(), nullable=False),
        sa.Column('client_uuid', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('category', sa.String(20), nullable=False),
        sa.Column('condition', sa.String(10), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('client_uuid'),
        sa.ForeignKeyConstraint(['inspection_id'], ['inspections.id'], ondelete='CASCADE'),
        sa.CheckConstraint("category IN ('plumbing', 'electrical', 'structure', 'cleanliness')", name='ck_items_category'),
        sa.CheckConstraint("condition IN ('good', 'fair', 'poor')", name='ck_items_condition'),
    )
    op.create_index('idx_inspection_items_inspection', 'inspection_items', ['inspection_id'])

    # Inspection media table
    op.create_table(
        'inspection_media',
        sa.Column('id', sa.Uuid(), nullable=False, default=sa.text('gen_random_uuid()')),
        sa.Column('inspection_id', sa.Uuid(), nullable=False),
        sa.Column('client_uuid', sa.Uuid(), nullable=False),
        sa.Column('file_url', sa.String(500), nullable=False),
        sa.Column('file_type', sa.String(10), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('client_uuid'),
        sa.ForeignKeyConstraint(['inspection_id'], ['inspections.id'], ondelete='CASCADE'),
        sa.CheckConstraint("file_type IN ('photo', 'video')", name='ck_media_file_type'),
    )
    op.create_index('idx_inspection_media_inspection', 'inspection_media', ['inspection_id'])

    # Inspection meter readings table
    op.create_table(
        'inspection_meter_readings',
        sa.Column('id', sa.Uuid(), nullable=False, default=sa.text('gen_random_uuid()')),
        sa.Column('inspection_id', sa.Uuid(), nullable=True),
        sa.Column('client_uuid', sa.Uuid(), nullable=False),
        sa.Column('unit_id', sa.Uuid(), nullable=False),
        sa.Column('meter_type', sa.String(20), nullable=False),
        sa.Column('previous_reading', sa.Numeric(10, 2), nullable=False),
        sa.Column('current_reading', sa.Numeric(10, 2), nullable=False),
        sa.Column('reading_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('client_uuid'),
        sa.ForeignKeyConstraint(['inspection_id'], ['inspections.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id']),
        sa.CheckConstraint("meter_type IN ('water', 'electricity')", name='ck_meter_type'),
    )
    op.create_index('idx_meter_readings_unit', 'inspection_meter_readings', ['unit_id'])


def downgrade() -> None:
    op.drop_table('inspection_meter_readings')
    op.drop_table('inspection_media')
    op.drop_table('inspection_items')
    op.drop_table('inspections')
