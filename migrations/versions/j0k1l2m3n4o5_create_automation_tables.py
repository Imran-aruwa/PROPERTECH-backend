"""Create automation tables and add theme_preference to users

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-03-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'j0k1l2m3n4o5'
down_revision = 'i9j0k1l2m3n4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── automation_rules ─────────────────────────────────────────────────────
    op.create_table(
        'automation_rules',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('trigger_event', sa.String(100), nullable=False),
        sa.Column('trigger_conditions', sa.JSON(), nullable=True),
        sa.Column('action_chain', sa.JSON(), nullable=False),
        sa.Column('delay_minutes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('requires_approval', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('execution_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_executed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_automation_rules_owner', 'automation_rules', ['owner_id'])
    op.create_index('idx_automation_rules_trigger', 'automation_rules', ['trigger_event'])
    op.create_index('idx_automation_rules_active', 'automation_rules', ['owner_id', 'is_active'])

    # ── automation_executions ─────────────────────────────────────────────────
    op.create_table(
        'automation_executions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('rule_id', sa.Uuid(), sa.ForeignKey('automation_rules.id', ondelete='SET NULL'), nullable=True),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('trigger_event', sa.String(100), nullable=False),
        sa.Column('trigger_payload', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('actions_taken', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('rolled_back_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rolled_back_by', sa.String(255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_auto_exec_owner', 'automation_executions', ['owner_id'])
    op.create_index('idx_auto_exec_rule', 'automation_executions', ['rule_id'])
    op.create_index('idx_auto_exec_status', 'automation_executions', ['owner_id', 'status'])
    op.create_index('idx_auto_exec_started', 'automation_executions', ['started_at'])

    # ── automation_actions_log ────────────────────────────────────────────────
    op.create_table(
        'automation_actions_log',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('execution_id', sa.Uuid(), sa.ForeignKey('automation_executions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=False),
        sa.Column('action_type', sa.String(100), nullable=False),
        sa.Column('action_payload', sa.JSON(), nullable=True),
        sa.Column('result_status', sa.String(20), nullable=False, server_default='success'),
        sa.Column('result_data', sa.JSON(), nullable=True),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('reversible', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('reversed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_action_log_execution', 'automation_actions_log', ['execution_id'])
    op.create_index('idx_action_log_owner', 'automation_actions_log', ['owner_id'])

    # ── autopilot_settings ────────────────────────────────────────────────────
    op.create_table(
        'autopilot_settings',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('mode', sa.String(30), nullable=False, server_default='notify_only'),
        sa.Column('quiet_hours_start', sa.Integer(), nullable=False, server_default='21'),
        sa.Column('quiet_hours_end', sa.Integer(), nullable=False, server_default='7'),
        sa.Column('max_actions_per_day', sa.Integer(), nullable=False, server_default='50'),
        sa.Column('excluded_property_ids', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_id', name='uq_autopilot_owner'),
    )
    op.create_index('idx_autopilot_owner', 'autopilot_settings', ['owner_id'])

    # ── automation_templates ──────────────────────────────────────────────────
    op.create_table(
        'automation_templates',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('trigger_event', sa.String(100), nullable=False),
        sa.Column('default_conditions', sa.JSON(), nullable=True),
        sa.Column('default_action_chain', sa.JSON(), nullable=False),
        sa.Column('is_system_template', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_by_owner_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_templates_category', 'automation_templates', ['category'])
    op.create_index('idx_templates_system', 'automation_templates', ['is_system_template'])

    # ── users.theme_preference ────────────────────────────────────────────────
    op.add_column(
        'users',
        sa.Column('theme_preference', sa.String(10), nullable=True, server_default='system')
    )


def downgrade() -> None:
    op.drop_column('users', 'theme_preference')
    op.drop_table('automation_templates')
    op.drop_table('autopilot_settings')
    op.drop_table('automation_actions_log')
    op.drop_table('automation_executions')
    op.drop_table('automation_rules')
