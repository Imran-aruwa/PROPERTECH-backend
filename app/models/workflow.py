"""
Workflow Automation Models
Database models for workflows, workflow actions, and workflow execution logs.
"""
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, Text, Enum as SQLEnum, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
import uuid

from app.db.base import Base


class TriggerEvent(str, Enum):
    RENT_OVERDUE = "rent_overdue"
    LEASE_EXPIRING_SOON = "lease_expiring_soon"
    MAINTENANCE_REQUEST_OPENED = "maintenance_request_opened"
    MAINTENANCE_REQUEST_RESOLVED = "maintenance_request_resolved"
    UNIT_VACATED = "unit_vacated"
    TENANT_ONBOARDED = "tenant_onboarded"


class ActionType(str, Enum):
    SEND_NOTIFICATION = "send_notification"
    SEND_EMAIL = "send_email"
    CREATE_TASK = "create_task"
    UPDATE_FIELD = "update_field"
    ESCALATE = "escalate"


class WorkflowStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DRAFT = "draft"


class WorkflowLogStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class Workflow(Base):
    """Automation workflow definition owned by a property owner."""
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    trigger_event: Mapped[TriggerEvent] = mapped_column(SQLEnum(TriggerEvent), nullable=False, index=True)

    # JSON string: optional filter conditions, e.g. {"days_overdue": 7}
    conditions: Mapped[str] = mapped_column(Text, nullable=True)

    status: Mapped[WorkflowStatus] = mapped_column(
        SQLEnum(WorkflowStatus), default=WorkflowStatus.ACTIVE, nullable=False
    )
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)

    run_count: Mapped[int] = mapped_column(Integer, default=0)
    last_triggered_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    actions = relationship(
        "WorkflowAction",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowAction.order",
    )
    logs = relationship(
        "WorkflowLog",
        back_populates="workflow",
        cascade="all, delete-orphan",
    )


class WorkflowAction(Base):
    """An individual action within a workflow, executed in order."""
    __tablename__ = "workflow_actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflows.id"), nullable=False, index=True
    )

    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    action_type: Mapped[ActionType] = mapped_column(SQLEnum(ActionType), nullable=False)

    # JSON config string keyed by action_type:
    #   send_notification: {"title": "...", "body": "..."}
    #   send_email:        {"to": "owner|tenant|caretaker", "subject": "...", "body": "..."}
    #   create_task:       {"title": "...", "assigned_to": "caretaker|owner", "due_in_days": 2}
    #   update_field:      {"model": "unit|tenant", "field": "status", "value": "vacant"}
    #   escalate:          {"notify_role": "owner", "message": "..."}
    config: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # Optional delay before this action fires (minutes)
    delay_minutes: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    workflow = relationship("Workflow", back_populates="actions")


class WorkflowLog(Base):
    """Execution audit log for each workflow run."""
    __tablename__ = "workflow_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflows.id"), nullable=False, index=True
    )

    triggered_by: Mapped[str] = mapped_column(String(50), nullable=False)   # TriggerEvent value
    context: Mapped[str] = mapped_column(Text, nullable=True)               # JSON context dict
    status: Mapped[WorkflowLogStatus] = mapped_column(SQLEnum(WorkflowLogStatus), nullable=False)
    actions_run: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)

    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # Relationships
    workflow = relationship("Workflow", back_populates="logs")
