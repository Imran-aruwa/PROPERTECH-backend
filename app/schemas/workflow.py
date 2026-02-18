"""
Workflow Automation Schemas
Pydantic models for request/response validation.
"""
from pydantic import BaseModel, field_validator
from typing import Optional, List, Any, Dict
from datetime import datetime
import uuid
import json

from app.models.workflow import TriggerEvent, ActionType, WorkflowStatus, WorkflowLogStatus


# ─────────────────────────── Actions ───────────────────────────

class WorkflowActionCreate(BaseModel):
    order: int = 0
    action_type: ActionType
    config: Dict[str, Any] = {}
    delay_minutes: int = 0


class WorkflowActionResponse(BaseModel):
    id: uuid.UUID
    order: int
    action_type: ActionType
    config: str           # raw JSON string stored in DB
    delay_minutes: int
    created_at: datetime

    @property
    def config_dict(self) -> Dict[str, Any]:
        try:
            return json.loads(self.config)
        except Exception:
            return {}

    class Config:
        from_attributes = True


# ─────────────────────────── Workflows ───────────────────────────

class WorkflowCreate(BaseModel):
    name: str
    description: Optional[str] = None
    trigger_event: TriggerEvent
    conditions: Optional[Dict[str, Any]] = None
    status: WorkflowStatus = WorkflowStatus.ACTIVE
    actions: List[WorkflowActionCreate] = []


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_event: Optional[TriggerEvent] = None
    conditions: Optional[Dict[str, Any]] = None
    status: Optional[WorkflowStatus] = None
    actions: Optional[List[WorkflowActionCreate]] = None


class WorkflowResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: Optional[str]
    trigger_event: TriggerEvent
    conditions: Optional[str]          # raw JSON string
    status: WorkflowStatus
    is_template: bool
    run_count: int
    last_triggered_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    actions: List[WorkflowActionResponse]

    class Config:
        from_attributes = True


# ─────────────────────────── Logs ───────────────────────────

class WorkflowLogResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    triggered_by: str
    context: Optional[str]
    status: WorkflowLogStatus
    actions_run: int
    error_message: Optional[str]
    triggered_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


# ─────────────────────────── Templates ───────────────────────────

class WorkflowTemplate(BaseModel):
    """Pre-built workflow template definition (read-only, not persisted)."""
    id: str
    name: str
    description: str
    trigger_event: TriggerEvent
    conditions: Optional[Dict[str, Any]] = None
    actions: List[WorkflowActionCreate]
