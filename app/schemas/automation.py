"""Pydantic schemas for the Autonomous Property Manager feature."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field


# ── Shared primitives ─────────────────────────────────────────────────────────

TriggerEvent = Literal[
    "payment_received",
    "payment_overdue_3d",
    "payment_overdue_7d",
    "payment_overdue_14d",
    "lease_expiring_60d",
    "lease_expiring_30d",
    "lease_expiring_7d",
    "lease_expired",
    "unit_vacated",
    "unit_vacant_7d",
    "unit_vacant_30d",
    "maintenance_request_created",
    "maintenance_overdue",
    "tenant_onboarded",
    "manual",
    "scheduled",
]

AutopilotMode = Literal["full_auto", "approval_required", "notify_only"]
ExecutionStatus = Literal["pending", "running", "completed", "failed", "rolled_back", "awaiting_approval"]
ActionResultStatus = Literal["success", "failed", "skipped"]


class Condition(BaseModel):
    field: str
    operator: Literal["eq", "neq", "gt", "lt", "gte", "lte", "in", "contains"]
    value: Any


class ActionStep(BaseModel):
    action_type: str
    params: Dict[str, Any] = Field(default_factory=dict)
    stop_on_failure: bool = False


# ── AutomationRule ────────────────────────────────────────────────────────────

class AutomationRuleCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    trigger_event: str
    trigger_conditions: Optional[List[Condition]] = None
    action_chain: List[ActionStep]
    delay_minutes: int = 0
    requires_approval: bool = False
    is_active: bool = True


class AutomationRuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_event: Optional[str] = None
    trigger_conditions: Optional[List[Condition]] = None
    action_chain: Optional[List[ActionStep]] = None
    delay_minutes: Optional[int] = None
    requires_approval: Optional[bool] = None
    is_active: Optional[bool] = None


class AutomationRuleResponse(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    description: Optional[str]
    is_active: bool
    trigger_event: str
    trigger_conditions: Optional[List[Dict[str, Any]]]
    action_chain: List[Dict[str, Any]]
    delay_minutes: int
    requires_approval: bool
    execution_count: int
    last_executed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── AutomationExecution ───────────────────────────────────────────────────────

class ActionResult(BaseModel):
    action_type: str
    status: ActionResultStatus
    data: Optional[Dict[str, Any]] = None
    reversible: bool = False
    log_id: Optional[str] = None


class AutomationExecutionResponse(BaseModel):
    id: UUID
    rule_id: Optional[UUID]
    owner_id: UUID
    trigger_event: str
    trigger_payload: Optional[Dict[str, Any]]
    status: ExecutionStatus
    started_at: datetime
    completed_at: Optional[datetime]
    actions_taken: Optional[List[Dict[str, Any]]]
    error_message: Optional[str]
    rolled_back_at: Optional[datetime]
    rolled_back_by: Optional[str]

    class Config:
        from_attributes = True


# ── AutomationActionLog ───────────────────────────────────────────────────────

class AutomationActionLogResponse(BaseModel):
    id: UUID
    execution_id: UUID
    owner_id: UUID
    action_type: str
    action_payload: Optional[Dict[str, Any]]
    result_status: ActionResultStatus
    result_data: Optional[Dict[str, Any]]
    executed_at: datetime
    reversible: bool
    reversed_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── AutopilotSettings ─────────────────────────────────────────────────────────

class AutopilotSettingsUpdate(BaseModel):
    is_enabled: Optional[bool] = None
    mode: Optional[AutopilotMode] = None
    quiet_hours_start: Optional[int] = Field(None, ge=0, le=23)
    quiet_hours_end: Optional[int] = Field(None, ge=0, le=23)
    max_actions_per_day: Optional[int] = Field(None, ge=1, le=500)
    excluded_property_ids: Optional[List[str]] = None


class AutopilotSettingsResponse(BaseModel):
    id: UUID
    owner_id: UUID
    is_enabled: bool
    mode: str
    quiet_hours_start: int
    quiet_hours_end: int
    max_actions_per_day: int
    excluded_property_ids: Optional[List[str]]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── AutomationTemplate ────────────────────────────────────────────────────────

class AutomationTemplateCreate(BaseModel):
    name: str
    category: Literal["payments", "leases", "vacancy", "maintenance", "onboarding"]
    description: Optional[str] = None
    trigger_event: str
    default_conditions: Optional[List[Condition]] = None
    default_action_chain: List[ActionStep]


class AutomationTemplateResponse(BaseModel):
    id: UUID
    name: str
    category: str
    description: Optional[str]
    trigger_event: str
    default_conditions: Optional[List[Dict[str, Any]]]
    default_action_chain: List[Dict[str, Any]]
    is_system_template: bool
    created_by_owner_id: Optional[UUID]
    created_at: datetime

    class Config:
        from_attributes = True


# ── Health ────────────────────────────────────────────────────────────────────

class AutopilotHealth(BaseModel):
    active_rules: int
    executions_today: int
    pending_approvals: int
    last_execution_at: Optional[datetime]
    upcoming_scheduled_count: int


# ── Test / Dry-run ────────────────────────────────────────────────────────────

class DryRunRequest(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict)


class DryRunResponse(BaseModel):
    rule_id: UUID
    conditions_matched: bool
    conditions_evaluated: List[Dict[str, Any]]
    actions_that_would_fire: List[Dict[str, Any]]
    dry_run: bool = True
    note: str = "Zero side-effects — nothing was written or sent"


# ── Approval / Reject ─────────────────────────────────────────────────────────

class RejectExecutionRequest(BaseModel):
    reason: str


# ── Manual trigger ────────────────────────────────────────────────────────────

class ManualTriggerRequest(BaseModel):
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)


# ── Theme preference ──────────────────────────────────────────────────────────

class ThemePreferenceUpdate(BaseModel):
    theme: Literal["light", "dark", "system"]
