"""Convert Integer columns to UUID for staff, attendance, incidents, tasks, equipment, meter_readings, maintenance_requests

Revision ID: d8a2b3c4d5e6
Revises: c635203c8238
Create Date: 2025-12-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd8a2b3c4d5e6'
down_revision: Union[str, None] = 'c635203c8238'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Convert Integer primary keys and foreign keys to UUID for:
    - staff (id, user_id, property_id, supervisor_id)
    - attendance (id, staff_id)
    - attendance_summary (id, staff_id)
    - leave_requests (id, staff_id)
    - incidents (id, staff_id, property_id) + add unit_id
    - tasks (id, assigned_to, property_id) + add unit_id
    - equipment (id, property_id) + add unit_id
    - meter_readings (id, unit_id) + add property_id
    - maintenance_requests (id, tenant_id) + add property_id, unit_id
    """

    # Get the current database dialect
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'postgresql':
        _upgrade_postgresql()
    else:
        # SQLite: Drop and recreate tables (SQLite doesn't support ALTER COLUMN)
        _upgrade_sqlite()


def _upgrade_postgresql() -> None:
    """PostgreSQL upgrade - alter column types in place"""

    # ===========================================
    # Step 1: Drop all foreign key constraints
    # ===========================================

    # attendance -> staff
    op.drop_constraint('attendance_staff_id_fkey', 'attendance', type_='foreignkey')

    # attendance_summary -> staff
    op.drop_constraint('attendance_summary_staff_id_fkey', 'attendance_summary', type_='foreignkey')

    # leave_requests -> staff
    op.drop_constraint('leave_requests_staff_id_fkey', 'leave_requests', type_='foreignkey')

    # incidents -> staff, properties
    op.drop_constraint('incidents_staff_id_fkey', 'incidents', type_='foreignkey')
    op.drop_constraint('incidents_property_id_fkey', 'incidents', type_='foreignkey')

    # tasks -> staff, properties
    op.drop_constraint('tasks_assigned_to_fkey', 'tasks', type_='foreignkey')
    op.drop_constraint('tasks_property_id_fkey', 'tasks', type_='foreignkey')

    # equipment -> properties
    op.drop_constraint('equipment_property_id_fkey', 'equipment', type_='foreignkey')

    # meter_readings -> units
    op.drop_constraint('meter_readings_unit_id_fkey', 'meter_readings', type_='foreignkey')

    # maintenance_requests -> tenants
    op.drop_constraint('maintenance_requests_tenant_id_fkey', 'maintenance_requests', type_='foreignkey')

    # staff -> users, properties, staff (self-referential)
    op.drop_constraint('staff_user_id_fkey', 'staff', type_='foreignkey')
    op.drop_constraint('staff_property_id_fkey', 'staff', type_='foreignkey')
    op.drop_constraint('staff_supervisor_id_fkey', 'staff', type_='foreignkey')

    # ===========================================
    # Step 2: Drop indexes on columns being altered
    # ===========================================
    op.drop_index('ix_staff_id', table_name='staff')
    op.drop_index('ix_attendance_id', table_name='attendance')
    op.drop_index('ix_attendance_staff_id', table_name='attendance')
    op.drop_index('ix_attendance_summary_id', table_name='attendance_summary')
    op.drop_index('ix_attendance_summary_staff_id', table_name='attendance_summary')
    op.drop_index('ix_leave_requests_id', table_name='leave_requests')
    op.drop_index('ix_leave_requests_staff_id', table_name='leave_requests')
    op.drop_index('ix_incidents_id', table_name='incidents')
    op.drop_index('ix_tasks_id', table_name='tasks')
    op.drop_index('ix_equipment_id', table_name='equipment')
    op.drop_index('ix_meter_readings_id', table_name='meter_readings')
    op.drop_index('ix_maintenance_requests_id', table_name='maintenance_requests')

    # ===========================================
    # Step 3: Alter column types to UUID
    # ===========================================

    # STAFF table
    op.alter_column('staff', 'id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    op.alter_column('staff', 'user_id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    op.alter_column('staff', 'property_id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    op.alter_column('staff', 'supervisor_id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=True,
        postgresql_using='CASE WHEN supervisor_id IS NOT NULL THEN gen_random_uuid() ELSE NULL END')

    # ATTENDANCE table
    op.alter_column('attendance', 'id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    op.alter_column('attendance', 'staff_id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')

    # ATTENDANCE_SUMMARY table
    op.alter_column('attendance_summary', 'id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    op.alter_column('attendance_summary', 'staff_id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')

    # LEAVE_REQUESTS table
    op.alter_column('leave_requests', 'id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    op.alter_column('leave_requests', 'staff_id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')

    # INCIDENTS table
    op.alter_column('incidents', 'id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    op.alter_column('incidents', 'staff_id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    op.alter_column('incidents', 'property_id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    # Add unit_id column
    op.add_column('incidents', sa.Column('unit_id', sa.Uuid(), nullable=True))

    # TASKS table
    op.alter_column('tasks', 'id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    op.alter_column('tasks', 'assigned_to',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    op.alter_column('tasks', 'property_id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    # Add unit_id column
    op.add_column('tasks', sa.Column('unit_id', sa.Uuid(), nullable=True))

    # EQUIPMENT table
    op.alter_column('equipment', 'id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    op.alter_column('equipment', 'property_id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    # Add unit_id column
    op.add_column('equipment', sa.Column('unit_id', sa.Uuid(), nullable=True))

    # METER_READINGS table
    op.alter_column('meter_readings', 'id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    op.alter_column('meter_readings', 'unit_id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    # Add property_id column
    op.add_column('meter_readings', sa.Column('property_id', sa.Uuid(), nullable=True))

    # MAINTENANCE_REQUESTS table
    op.alter_column('maintenance_requests', 'id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    op.alter_column('maintenance_requests', 'tenant_id',
        existing_type=sa.Integer(),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using='gen_random_uuid()')
    # Add property_id and unit_id columns
    op.add_column('maintenance_requests', sa.Column('property_id', sa.Uuid(), nullable=True))
    op.add_column('maintenance_requests', sa.Column('unit_id', sa.Uuid(), nullable=True))

    # ===========================================
    # Step 4: Recreate indexes
    # ===========================================
    op.create_index('ix_staff_id', 'staff', ['id'], unique=False)
    op.create_index('ix_attendance_id', 'attendance', ['id'], unique=False)
    op.create_index('ix_attendance_staff_id', 'attendance', ['staff_id'], unique=False)
    op.create_index('ix_attendance_summary_id', 'attendance_summary', ['id'], unique=False)
    op.create_index('ix_attendance_summary_staff_id', 'attendance_summary', ['staff_id'], unique=False)
    op.create_index('ix_leave_requests_id', 'leave_requests', ['id'], unique=False)
    op.create_index('ix_leave_requests_staff_id', 'leave_requests', ['staff_id'], unique=False)
    op.create_index('ix_incidents_id', 'incidents', ['id'], unique=False)
    op.create_index('ix_tasks_id', 'tasks', ['id'], unique=False)
    op.create_index('ix_equipment_id', 'equipment', ['id'], unique=False)
    op.create_index('ix_meter_readings_id', 'meter_readings', ['id'], unique=False)
    op.create_index('ix_maintenance_requests_id', 'maintenance_requests', ['id'], unique=False)

    # ===========================================
    # Step 5: Recreate foreign key constraints
    # ===========================================

    # staff -> users, properties, staff (self-referential)
    op.create_foreign_key('staff_user_id_fkey', 'staff', 'users', ['user_id'], ['id'])
    op.create_foreign_key('staff_property_id_fkey', 'staff', 'properties', ['property_id'], ['id'])
    op.create_foreign_key('staff_supervisor_id_fkey', 'staff', 'staff', ['supervisor_id'], ['id'])

    # attendance -> staff
    op.create_foreign_key('attendance_staff_id_fkey', 'attendance', 'staff', ['staff_id'], ['id'])

    # attendance_summary -> staff
    op.create_foreign_key('attendance_summary_staff_id_fkey', 'attendance_summary', 'staff', ['staff_id'], ['id'])

    # leave_requests -> staff
    op.create_foreign_key('leave_requests_staff_id_fkey', 'leave_requests', 'staff', ['staff_id'], ['id'])

    # incidents -> staff, properties, units
    op.create_foreign_key('incidents_staff_id_fkey', 'incidents', 'staff', ['staff_id'], ['id'])
    op.create_foreign_key('incidents_property_id_fkey', 'incidents', 'properties', ['property_id'], ['id'])
    op.create_foreign_key('incidents_unit_id_fkey', 'incidents', 'units', ['unit_id'], ['id'])

    # tasks -> staff, properties, units
    op.create_foreign_key('tasks_assigned_to_fkey', 'tasks', 'staff', ['assigned_to'], ['id'])
    op.create_foreign_key('tasks_property_id_fkey', 'tasks', 'properties', ['property_id'], ['id'])
    op.create_foreign_key('tasks_unit_id_fkey', 'tasks', 'units', ['unit_id'], ['id'])

    # equipment -> properties, units
    op.create_foreign_key('equipment_property_id_fkey', 'equipment', 'properties', ['property_id'], ['id'])
    op.create_foreign_key('equipment_unit_id_fkey', 'equipment', 'units', ['unit_id'], ['id'])

    # meter_readings -> units, properties
    op.create_foreign_key('meter_readings_unit_id_fkey', 'meter_readings', 'units', ['unit_id'], ['id'])
    op.create_foreign_key('meter_readings_property_id_fkey', 'meter_readings', 'properties', ['property_id'], ['id'])

    # maintenance_requests -> tenants, properties, units
    op.create_foreign_key('maintenance_requests_tenant_id_fkey', 'maintenance_requests', 'tenants', ['tenant_id'], ['id'])
    op.create_foreign_key('maintenance_requests_property_id_fkey', 'maintenance_requests', 'properties', ['property_id'], ['id'])
    op.create_foreign_key('maintenance_requests_unit_id_fkey', 'maintenance_requests', 'units', ['unit_id'], ['id'])


def _upgrade_sqlite() -> None:
    """SQLite upgrade - drop and recreate tables (SQLite doesn't support ALTER COLUMN TYPE)"""

    # Drop tables in reverse dependency order
    op.drop_table('tasks')
    op.drop_table('incidents')
    op.drop_table('leave_requests')
    op.drop_table('attendance_summary')
    op.drop_table('attendance')
    op.drop_table('meter_readings')
    op.drop_table('maintenance_requests')
    op.drop_table('equipment')
    op.drop_table('staff')

    # Recreate staff table with UUID columns
    op.create_table('staff',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('property_id', sa.Uuid(), nullable=False),
        sa.Column('supervisor_id', sa.Uuid(), nullable=True),
        sa.Column('department', sa.Enum('SECURITY', 'GARDENING', 'MAINTENANCE', name='staffdepartment'), nullable=False),
        sa.Column('position', sa.String(length=100), nullable=False),
        sa.Column('salary', sa.Float(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
        sa.ForeignKeyConstraint(['supervisor_id'], ['staff.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_staff_id', 'staff', ['id'], unique=False)

    # Recreate equipment table
    op.create_table('equipment',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('property_id', sa.Uuid(), nullable=False),
        sa.Column('unit_id', sa.Uuid(), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('type', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('last_maintenance', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_equipment_id', 'equipment', ['id'], unique=False)

    # Recreate maintenance_requests table
    op.create_table('maintenance_requests',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('property_id', sa.Uuid(), nullable=True),
        sa.Column('unit_id', sa.Uuid(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('priority', sa.Enum('LOW', 'MEDIUM', 'HIGH', 'EMERGENCY', name='maintenancepriority'), nullable=True),
        sa.Column('status', sa.Enum('PENDING', 'IN_PROGRESS', 'COMPLETED', 'REJECTED', name='maintenancestatus'), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_maintenance_requests_id', 'maintenance_requests', ['id'], unique=False)

    # Recreate meter_readings table
    op.create_table('meter_readings',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('unit_id', sa.Uuid(), nullable=False),
        sa.Column('property_id', sa.Uuid(), nullable=True),
        sa.Column('reading_date', sa.DateTime(), nullable=False),
        sa.Column('water_reading', sa.Float(), nullable=True),
        sa.Column('electricity_reading', sa.Float(), nullable=True),
        sa.Column('recorded_by', sa.String(length=255), nullable=False),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_meter_readings_id', 'meter_readings', ['id'], unique=False)

    # Recreate attendance table
    op.create_table('attendance',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('staff_id', sa.Uuid(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('check_in_time', sa.DateTime(), nullable=True),
        sa.Column('check_out_time', sa.DateTime(), nullable=True),
        sa.Column('hours_worked', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.Column('verified_by', sa.String(length=255), nullable=True),
        sa.Column('is_verified', sa.Boolean(), nullable=True),
        sa.Column('check_in_location', sa.String(length=255), nullable=True),
        sa.Column('check_out_location', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['staff_id'], ['staff.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_attendance_date', 'attendance', ['date'], unique=False)
    op.create_index('ix_attendance_id', 'attendance', ['id'], unique=False)
    op.create_index('ix_attendance_staff_id', 'attendance', ['staff_id'], unique=False)

    # Recreate attendance_summary table
    op.create_table('attendance_summary',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('staff_id', sa.Uuid(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('total_days', sa.Integer(), nullable=False),
        sa.Column('days_present', sa.Integer(), nullable=False),
        sa.Column('days_absent', sa.Integer(), nullable=False),
        sa.Column('days_on_leave', sa.Integer(), nullable=False),
        sa.Column('days_sick', sa.Integer(), nullable=False),
        sa.Column('total_hours_worked', sa.Float(), nullable=False),
        sa.Column('total_overtime_hours', sa.Float(), nullable=False),
        sa.Column('late_arrivals', sa.Integer(), nullable=False),
        sa.Column('total_late_minutes', sa.Integer(), nullable=False),
        sa.Column('attendance_rate', sa.Float(), nullable=True),
        sa.Column('punctuality_rate', sa.Float(), nullable=True),
        sa.Column('performance_score', sa.Float(), nullable=True),
        sa.Column('performance_notes', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['staff_id'], ['staff.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_attendance_summary_id', 'attendance_summary', ['id'], unique=False)
    op.create_index('ix_attendance_summary_staff_id', 'attendance_summary', ['staff_id'], unique=False)

    # Recreate leave_requests table
    op.create_table('leave_requests',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('staff_id', sa.Uuid(), nullable=False),
        sa.Column('leave_type', sa.String(length=50), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('number_of_days', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('approved_by', sa.String(length=255), nullable=True),
        sa.Column('approval_date', sa.DateTime(), nullable=True),
        sa.Column('rejection_reason', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['staff_id'], ['staff.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_leave_requests_id', 'leave_requests', ['id'], unique=False)
    op.create_index('ix_leave_requests_staff_id', 'leave_requests', ['staff_id'], unique=False)

    # Recreate incidents table
    op.create_table('incidents',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('staff_id', sa.Uuid(), nullable=False),
        sa.Column('property_id', sa.Uuid(), nullable=False),
        sa.Column('unit_id', sa.Uuid(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('severity', sa.Enum('LOW', 'MEDIUM', 'HIGH', 'CRITICAL', name='incidentseverity'), nullable=True),
        sa.Column('reported_at', sa.DateTime(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
        sa.ForeignKeyConstraint(['staff_id'], ['staff.id'], ),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_incidents_id', 'incidents', ['id'], unique=False)

    # Recreate tasks table
    op.create_table('tasks',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('assigned_to', sa.Uuid(), nullable=False),
        sa.Column('property_id', sa.Uuid(), nullable=False),
        sa.Column('unit_id', sa.Uuid(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.Enum('PENDING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', name='taskstatus'), nullable=True),
        sa.Column('due_date', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['assigned_to'], ['staff.id'], ),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tasks_id', 'tasks', ['id'], unique=False)


def downgrade() -> None:
    """
    Revert UUID columns back to Integer.
    WARNING: This will lose data if there are existing UUID values that cannot be converted.
    """
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'postgresql':
        _downgrade_postgresql()
    else:
        _downgrade_sqlite()


def _downgrade_postgresql() -> None:
    """PostgreSQL downgrade - revert to Integer types"""

    # Drop new columns
    op.drop_column('incidents', 'unit_id')
    op.drop_column('tasks', 'unit_id')
    op.drop_column('equipment', 'unit_id')
    op.drop_column('meter_readings', 'property_id')
    op.drop_column('maintenance_requests', 'property_id')
    op.drop_column('maintenance_requests', 'unit_id')

    # Drop foreign keys
    op.drop_constraint('staff_user_id_fkey', 'staff', type_='foreignkey')
    op.drop_constraint('staff_property_id_fkey', 'staff', type_='foreignkey')
    op.drop_constraint('staff_supervisor_id_fkey', 'staff', type_='foreignkey')
    op.drop_constraint('attendance_staff_id_fkey', 'attendance', type_='foreignkey')
    op.drop_constraint('attendance_summary_staff_id_fkey', 'attendance_summary', type_='foreignkey')
    op.drop_constraint('leave_requests_staff_id_fkey', 'leave_requests', type_='foreignkey')
    op.drop_constraint('incidents_staff_id_fkey', 'incidents', type_='foreignkey')
    op.drop_constraint('incidents_property_id_fkey', 'incidents', type_='foreignkey')
    op.drop_constraint('tasks_assigned_to_fkey', 'tasks', type_='foreignkey')
    op.drop_constraint('tasks_property_id_fkey', 'tasks', type_='foreignkey')
    op.drop_constraint('equipment_property_id_fkey', 'equipment', type_='foreignkey')
    op.drop_constraint('meter_readings_unit_id_fkey', 'meter_readings', type_='foreignkey')
    op.drop_constraint('maintenance_requests_tenant_id_fkey', 'maintenance_requests', type_='foreignkey')

    # Drop indexes
    op.drop_index('ix_staff_id', table_name='staff')
    op.drop_index('ix_attendance_id', table_name='attendance')
    op.drop_index('ix_attendance_staff_id', table_name='attendance')
    op.drop_index('ix_attendance_summary_id', table_name='attendance_summary')
    op.drop_index('ix_attendance_summary_staff_id', table_name='attendance_summary')
    op.drop_index('ix_leave_requests_id', table_name='leave_requests')
    op.drop_index('ix_leave_requests_staff_id', table_name='leave_requests')
    op.drop_index('ix_incidents_id', table_name='incidents')
    op.drop_index('ix_tasks_id', table_name='tasks')
    op.drop_index('ix_equipment_id', table_name='equipment')
    op.drop_index('ix_meter_readings_id', table_name='meter_readings')
    op.drop_index('ix_maintenance_requests_id', table_name='maintenance_requests')

    # Alter columns back to Integer (will fail if data exists)
    # Note: This is a lossy operation
    op.execute("TRUNCATE staff, attendance, attendance_summary, leave_requests, incidents, tasks, equipment, meter_readings, maintenance_requests CASCADE")

    # Staff
    op.alter_column('staff', 'id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False, autoincrement=True)
    op.alter_column('staff', 'user_id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False)
    op.alter_column('staff', 'property_id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False)
    op.alter_column('staff', 'supervisor_id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=True)

    # Attendance
    op.alter_column('attendance', 'id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False, autoincrement=True)
    op.alter_column('attendance', 'staff_id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False)

    # Attendance Summary
    op.alter_column('attendance_summary', 'id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False, autoincrement=True)
    op.alter_column('attendance_summary', 'staff_id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False)

    # Leave Requests
    op.alter_column('leave_requests', 'id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False, autoincrement=True)
    op.alter_column('leave_requests', 'staff_id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False)

    # Incidents
    op.alter_column('incidents', 'id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False, autoincrement=True)
    op.alter_column('incidents', 'staff_id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False)
    op.alter_column('incidents', 'property_id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False)

    # Tasks
    op.alter_column('tasks', 'id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False, autoincrement=True)
    op.alter_column('tasks', 'assigned_to', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False)
    op.alter_column('tasks', 'property_id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False)

    # Equipment
    op.alter_column('equipment', 'id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False, autoincrement=True)
    op.alter_column('equipment', 'property_id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False)

    # Meter Readings
    op.alter_column('meter_readings', 'id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False, autoincrement=True)
    op.alter_column('meter_readings', 'unit_id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False)

    # Maintenance Requests
    op.alter_column('maintenance_requests', 'id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False, autoincrement=True)
    op.alter_column('maintenance_requests', 'tenant_id', existing_type=sa.Uuid(), type_=sa.Integer(), existing_nullable=False)

    # Recreate indexes
    op.create_index('ix_staff_id', 'staff', ['id'], unique=False)
    op.create_index('ix_attendance_id', 'attendance', ['id'], unique=False)
    op.create_index('ix_attendance_staff_id', 'attendance', ['staff_id'], unique=False)
    op.create_index('ix_attendance_summary_id', 'attendance_summary', ['id'], unique=False)
    op.create_index('ix_attendance_summary_staff_id', 'attendance_summary', ['staff_id'], unique=False)
    op.create_index('ix_leave_requests_id', 'leave_requests', ['id'], unique=False)
    op.create_index('ix_leave_requests_staff_id', 'leave_requests', ['staff_id'], unique=False)
    op.create_index('ix_incidents_id', 'incidents', ['id'], unique=False)
    op.create_index('ix_tasks_id', 'tasks', ['id'], unique=False)
    op.create_index('ix_equipment_id', 'equipment', ['id'], unique=False)
    op.create_index('ix_meter_readings_id', 'meter_readings', ['id'], unique=False)
    op.create_index('ix_maintenance_requests_id', 'maintenance_requests', ['id'], unique=False)

    # Recreate foreign keys
    op.create_foreign_key('staff_user_id_fkey', 'staff', 'users', ['user_id'], ['id'])
    op.create_foreign_key('staff_property_id_fkey', 'staff', 'properties', ['property_id'], ['id'])
    op.create_foreign_key('staff_supervisor_id_fkey', 'staff', 'staff', ['supervisor_id'], ['id'])
    op.create_foreign_key('attendance_staff_id_fkey', 'attendance', 'staff', ['staff_id'], ['id'])
    op.create_foreign_key('attendance_summary_staff_id_fkey', 'attendance_summary', 'staff', ['staff_id'], ['id'])
    op.create_foreign_key('leave_requests_staff_id_fkey', 'leave_requests', 'staff', ['staff_id'], ['id'])
    op.create_foreign_key('incidents_staff_id_fkey', 'incidents', 'staff', ['staff_id'], ['id'])
    op.create_foreign_key('incidents_property_id_fkey', 'incidents', 'properties', ['property_id'], ['id'])
    op.create_foreign_key('tasks_assigned_to_fkey', 'tasks', 'staff', ['assigned_to'], ['id'])
    op.create_foreign_key('tasks_property_id_fkey', 'tasks', 'properties', ['property_id'], ['id'])
    op.create_foreign_key('equipment_property_id_fkey', 'equipment', 'properties', ['property_id'], ['id'])
    op.create_foreign_key('meter_readings_unit_id_fkey', 'meter_readings', 'units', ['unit_id'], ['id'])
    op.create_foreign_key('maintenance_requests_tenant_id_fkey', 'maintenance_requests', 'tenants', ['tenant_id'], ['id'])


def _downgrade_sqlite() -> None:
    """SQLite downgrade - drop and recreate tables with Integer columns"""

    # Drop tables
    op.drop_table('tasks')
    op.drop_table('incidents')
    op.drop_table('leave_requests')
    op.drop_table('attendance_summary')
    op.drop_table('attendance')
    op.drop_table('meter_readings')
    op.drop_table('maintenance_requests')
    op.drop_table('equipment')
    op.drop_table('staff')

    # Recreate with Integer columns (original schema)
    op.create_table('staff',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('property_id', sa.Integer(), nullable=False),
        sa.Column('supervisor_id', sa.Integer(), nullable=True),
        sa.Column('department', sa.Enum('SECURITY', 'GARDENING', 'MAINTENANCE', name='staffdepartment'), nullable=False),
        sa.Column('position', sa.String(length=100), nullable=False),
        sa.Column('salary', sa.Float(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
        sa.ForeignKeyConstraint(['supervisor_id'], ['staff.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_staff_id', 'staff', ['id'], unique=False)

    op.create_table('equipment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('property_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('type', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('last_maintenance', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_equipment_id', 'equipment', ['id'], unique=False)

    op.create_table('maintenance_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('priority', sa.Enum('LOW', 'MEDIUM', 'HIGH', 'EMERGENCY', name='maintenancepriority'), nullable=True),
        sa.Column('status', sa.Enum('PENDING', 'IN_PROGRESS', 'COMPLETED', 'REJECTED', name='maintenancestatus'), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_maintenance_requests_id', 'maintenance_requests', ['id'], unique=False)

    op.create_table('meter_readings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('unit_id', sa.Integer(), nullable=False),
        sa.Column('reading_date', sa.DateTime(), nullable=False),
        sa.Column('water_reading', sa.Float(), nullable=True),
        sa.Column('electricity_reading', sa.Float(), nullable=True),
        sa.Column('recorded_by', sa.String(length=255), nullable=False),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_meter_readings_id', 'meter_readings', ['id'], unique=False)

    op.create_table('attendance',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('staff_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('check_in_time', sa.DateTime(), nullable=True),
        sa.Column('check_out_time', sa.DateTime(), nullable=True),
        sa.Column('hours_worked', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.Column('verified_by', sa.String(length=255), nullable=True),
        sa.Column('is_verified', sa.Boolean(), nullable=True),
        sa.Column('check_in_location', sa.String(length=255), nullable=True),
        sa.Column('check_out_location', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['staff_id'], ['staff.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_attendance_date', 'attendance', ['date'], unique=False)
    op.create_index('ix_attendance_id', 'attendance', ['id'], unique=False)
    op.create_index('ix_attendance_staff_id', 'attendance', ['staff_id'], unique=False)

    op.create_table('attendance_summary',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('staff_id', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('total_days', sa.Integer(), nullable=False),
        sa.Column('days_present', sa.Integer(), nullable=False),
        sa.Column('days_absent', sa.Integer(), nullable=False),
        sa.Column('days_on_leave', sa.Integer(), nullable=False),
        sa.Column('days_sick', sa.Integer(), nullable=False),
        sa.Column('total_hours_worked', sa.Float(), nullable=False),
        sa.Column('total_overtime_hours', sa.Float(), nullable=False),
        sa.Column('late_arrivals', sa.Integer(), nullable=False),
        sa.Column('total_late_minutes', sa.Integer(), nullable=False),
        sa.Column('attendance_rate', sa.Float(), nullable=True),
        sa.Column('punctuality_rate', sa.Float(), nullable=True),
        sa.Column('performance_score', sa.Float(), nullable=True),
        sa.Column('performance_notes', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['staff_id'], ['staff.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_attendance_summary_id', 'attendance_summary', ['id'], unique=False)
    op.create_index('ix_attendance_summary_staff_id', 'attendance_summary', ['staff_id'], unique=False)

    op.create_table('leave_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('staff_id', sa.Integer(), nullable=False),
        sa.Column('leave_type', sa.String(length=50), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('number_of_days', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('approved_by', sa.String(length=255), nullable=True),
        sa.Column('approval_date', sa.DateTime(), nullable=True),
        sa.Column('rejection_reason', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['staff_id'], ['staff.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_leave_requests_id', 'leave_requests', ['id'], unique=False)
    op.create_index('ix_leave_requests_staff_id', 'leave_requests', ['staff_id'], unique=False)

    op.create_table('incidents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('staff_id', sa.Integer(), nullable=False),
        sa.Column('property_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('severity', sa.Enum('LOW', 'MEDIUM', 'HIGH', 'CRITICAL', name='incidentseverity'), nullable=True),
        sa.Column('reported_at', sa.DateTime(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
        sa.ForeignKeyConstraint(['staff_id'], ['staff.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_incidents_id', 'incidents', ['id'], unique=False)

    op.create_table('tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('assigned_to', sa.Integer(), nullable=False),
        sa.Column('property_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.Enum('PENDING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', name='taskstatus'), nullable=True),
        sa.Column('due_date', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['assigned_to'], ['staff.id'], ),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tasks_id', 'tasks', ['id'], unique=False)
