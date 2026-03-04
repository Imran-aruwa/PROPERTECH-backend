"""
Autonomous Property Manager — ORM Models

Tables:
  automation_rules       — owner-defined trigger → action chains
  automation_executions  — per-run execution record
  automation_actions_log — per-action audit trail
  autopilot_settings     — per-owner on/off + mode config
  automation_templates   — reusable rule blueprints (system + custom)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, Uuid
)
from app.db.base import Base


class AutomationRule(Base):
    __tablename__ = "automation_rules"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    trigger_event = Column(String(100), nullable=False, index=True)
    # List of {field, operator, value} dicts
    trigger_conditions = Column(JSON, nullable=True)
    # List of {action_type, params, stop_on_failure} dicts
    action_chain = Column(JSON, nullable=False)
    delay_minutes = Column(Integer, default=0, nullable=False)
    requires_approval = Column(Boolean, default=False, nullable=False)
    execution_count = Column(Integer, default=0, nullable=False)
    last_executed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class AutomationExecution(Base):
    __tablename__ = "automation_executions"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    rule_id = Column(Uuid, ForeignKey("automation_rules.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_id = Column(Uuid, nullable=False, index=True)
    trigger_event = Column(String(100), nullable=False)
    trigger_payload = Column(JSON, nullable=True)
    # pending / running / completed / failed / rolled_back / awaiting_approval
    status = Column(String(30), default="pending", nullable=False)
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    actions_taken = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    rolled_back_at = Column(DateTime(timezone=True), nullable=True)
    rolled_back_by = Column(String(255), nullable=True)


class AutomationActionLog(Base):
    __tablename__ = "automation_actions_log"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    execution_id = Column(Uuid, ForeignKey("automation_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(Uuid, nullable=False, index=True)
    action_type = Column(String(100), nullable=False)
    action_payload = Column(JSON, nullable=True)
    # success / failed / skipped
    result_status = Column(String(20), default="success", nullable=False)
    result_data = Column(JSON, nullable=True)
    executed_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    reversible = Column(Boolean, default=False, nullable=False)
    reversed_at = Column(DateTime(timezone=True), nullable=True)


class AutopilotSettings(Base):
    __tablename__ = "autopilot_settings"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    is_enabled = Column(Boolean, default=False, nullable=False)
    # full_auto / approval_required / notify_only
    mode = Column(String(30), default="notify_only", nullable=False)
    quiet_hours_start = Column(Integer, default=21, nullable=False)
    quiet_hours_end = Column(Integer, default=7, nullable=False)
    max_actions_per_day = Column(Integer, default=50, nullable=False)
    excluded_property_ids = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class AutomationTemplate(Base):
    __tablename__ = "automation_templates"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    # payments / leases / vacancy / maintenance / onboarding
    category = Column(String(50), nullable=False, index=True)
    description = Column(Text, nullable=True)
    trigger_event = Column(String(100), nullable=False)
    default_conditions = Column(JSON, nullable=True)
    default_action_chain = Column(JSON, nullable=False)
    is_system_template = Column(Boolean, default=False, nullable=False, index=True)
    created_by_owner_id = Column(Uuid, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
