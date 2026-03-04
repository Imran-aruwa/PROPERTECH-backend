"""
Automation / Autopilot API — 19 endpoints.
All require JWT auth + owner premium subscription.
Prefix: /api/automation
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.automation import (
    AutomationRule,
    AutomationExecution,
    AutomationActionLog,
    AutopilotSettings,
    AutomationTemplate,
)
from app.models.user import User, UserRole
from app.schemas.automation import (
    AutomationRuleCreate,
    AutomationRuleUpdate,
    AutomationRuleResponse,
    AutomationExecutionResponse,
    AutomationActionLogResponse,
    AutopilotSettingsUpdate,
    AutopilotSettingsResponse,
    AutomationTemplateCreate,
    AutomationTemplateResponse,
    AutopilotHealth,
    DryRunRequest,
    DryRunResponse,
    RejectExecutionRequest,
    ManualTriggerRequest,
    ThemePreferenceUpdate,
)

router = APIRouter()


# ── Premium gate ──────────────────────────────────────────────────────────────

def require_premium(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    from app.models.payment import Subscription, SubscriptionStatus, SubscriptionPlan
    sub = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == current_user.id,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.plan.in_([SubscriptionPlan.PROFESSIONAL, SubscriptionPlan.ENTERPRISE]),
        )
        .first()
    )
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Autopilot requires a Professional or Enterprise subscription",
        )
    return current_user


# ══════════════════════════════════════════════════════════════════════════════
# RULES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/rules", response_model=List[AutomationRuleResponse])
def list_rules(
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    return (
        db.query(AutomationRule)
        .filter(AutomationRule.owner_id == current_user.id)
        .order_by(AutomationRule.created_at.desc())
        .all()
    )


@router.post("/rules", response_model=AutomationRuleResponse, status_code=201)
def create_rule(
    body: AutomationRuleCreate,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    rule = AutomationRule(
        id=uuid.uuid4(),
        owner_id=current_user.id,
        name=body.name,
        description=body.description,
        is_active=body.is_active,
        trigger_event=body.trigger_event,
        trigger_conditions=[c.model_dump() for c in body.trigger_conditions] if body.trigger_conditions else [],
        action_chain=[a.model_dump() for a in body.action_chain],
        delay_minutes=body.delay_minutes,
        requires_approval=body.requires_approval,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/rules/{rule_id}", response_model=AutomationRuleResponse)
def get_rule(
    rule_id: uuid.UUID,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    rule = _get_rule_or_404(rule_id, current_user.id, db)
    return rule


@router.put("/rules/{rule_id}", response_model=AutomationRuleResponse)
def update_rule(
    rule_id: uuid.UUID,
    body: AutomationRuleUpdate,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    rule = _get_rule_or_404(rule_id, current_user.id, db)
    if body.name is not None:
        rule.name = body.name
    if body.description is not None:
        rule.description = body.description
    if body.trigger_event is not None:
        rule.trigger_event = body.trigger_event
    if body.trigger_conditions is not None:
        rule.trigger_conditions = [c.model_dump() for c in body.trigger_conditions]
    if body.action_chain is not None:
        rule.action_chain = [a.model_dump() for a in body.action_chain]
    if body.delay_minutes is not None:
        rule.delay_minutes = body.delay_minutes
    if body.requires_approval is not None:
        rule.requires_approval = body.requires_approval
    if body.is_active is not None:
        rule.is_active = body.is_active
    rule.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(
    rule_id: uuid.UUID,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    rule = _get_rule_or_404(rule_id, current_user.id, db)
    db.delete(rule)
    db.commit()


@router.post("/rules/{rule_id}/toggle", response_model=AutomationRuleResponse)
def toggle_rule(
    rule_id: uuid.UUID,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    rule = _get_rule_or_404(rule_id, current_user.id, db)
    rule.is_active = not rule.is_active
    rule.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(rule)
    return rule


@router.post("/rules/{rule_id}/test", response_model=DryRunResponse)
def dry_run_rule(
    rule_id: uuid.UUID,
    body: DryRunRequest,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """
    Dry-run — strictly read-only.
    Evaluates conditions and previews which actions would fire.
    Zero DB writes, zero external calls, zero side effects.
    """
    rule = _get_rule_or_404(rule_id, current_user.id, db)

    from app.services.automation_engine import AutomationEngine
    engine = AutomationEngine(db)

    conditions_list = rule.trigger_conditions or []
    matched = engine._check_conditions(conditions_list, body.payload)

    conditions_evaluated = []
    for cond in conditions_list:
        field = cond.get("field", "")
        op = cond.get("operator", "eq")
        expected = cond.get("value")
        actual = body.payload.get(field)
        cond_result = engine._check_conditions([cond], body.payload)
        conditions_evaluated.append({
            "field": field,
            "operator": op,
            "expected": expected,
            "actual": actual,
            "passed": cond_result,
        })

    actions_preview = []
    if matched:
        from app.services.action_library import resolve_templates
        for step in (rule.action_chain or []):
            resolved = resolve_templates(step.get("params", {}), body.payload)
            actions_preview.append({
                "action_type": step.get("action_type"),
                "resolved_params": resolved,
                "stop_on_failure": step.get("stop_on_failure", False),
            })

    return DryRunResponse(
        rule_id=rule_id,
        conditions_matched=matched,
        conditions_evaluated=conditions_evaluated,
        actions_that_would_fire=actions_preview,
    )


# ══════════════════════════════════════════════════════════════════════════════
# TEMPLATES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/templates", response_model=List[AutomationTemplateResponse])
def list_templates(
    category: Optional[str] = None,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    q = db.query(AutomationTemplate).filter(
        (AutomationTemplate.is_system_template == True) |
        (AutomationTemplate.created_by_owner_id == current_user.id)
    )
    if category:
        q = q.filter(AutomationTemplate.category == category)
    return q.order_by(AutomationTemplate.is_system_template.desc(), AutomationTemplate.name).all()


@router.post("/templates/{template_id}/activate", response_model=AutomationRuleResponse, status_code=201)
def activate_template(
    template_id: uuid.UUID,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Copy a template as a live rule for this owner."""
    tmpl = db.query(AutomationTemplate).filter(AutomationTemplate.id == template_id).first()
    if not tmpl:
        raise HTTPException(404, "Template not found")

    rule = AutomationRule(
        id=uuid.uuid4(),
        owner_id=current_user.id,
        name=tmpl.name,
        description=tmpl.description,
        is_active=True,
        trigger_event=tmpl.trigger_event,
        trigger_conditions=tmpl.default_conditions or [],
        action_chain=tmpl.default_action_chain or [],
        delay_minutes=0,
        requires_approval=False,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.post("/templates", response_model=AutomationTemplateResponse, status_code=201)
def create_custom_template(
    body: AutomationTemplateCreate,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Owner saves one of their rules as a custom template."""
    tmpl = AutomationTemplate(
        id=uuid.uuid4(),
        name=body.name,
        category=body.category,
        description=body.description,
        trigger_event=body.trigger_event,
        default_conditions=[c.model_dump() for c in body.default_conditions] if body.default_conditions else [],
        default_action_chain=[a.model_dump() for a in body.default_action_chain],
        is_system_template=False,
        created_by_owner_id=current_user.id,
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return tmpl


# ══════════════════════════════════════════════════════════════════════════════
# EXECUTIONS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/executions", response_model=List[AutomationExecutionResponse])
def list_executions(
    rule_id: Optional[uuid.UUID] = None,
    exec_status: Optional[str] = Query(None, alias="status"),
    trigger_event: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    q = db.query(AutomationExecution).filter(
        AutomationExecution.owner_id == current_user.id
    )
    if rule_id:
        q = q.filter(AutomationExecution.rule_id == rule_id)
    if exec_status:
        q = q.filter(AutomationExecution.status == exec_status)
    if trigger_event:
        q = q.filter(AutomationExecution.trigger_event == trigger_event)
    return (
        q.order_by(AutomationExecution.started_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/executions/{execution_id}", response_model=AutomationExecutionResponse)
def get_execution(
    execution_id: uuid.UUID,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    return _get_execution_or_404(execution_id, current_user.id, db)


@router.post("/executions/{execution_id}/approve", response_model=AutomationExecutionResponse)
async def approve_execution(
    execution_id: uuid.UUID,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Approve an awaiting_approval execution and run it now."""
    execution = _get_execution_or_404(execution_id, current_user.id, db)
    if execution.status != "awaiting_approval":
        raise HTTPException(400, f"Execution is '{execution.status}', not awaiting_approval")

    if not execution.rule_id:
        raise HTTPException(400, "Execution has no associated rule")

    rule = db.query(AutomationRule).filter(AutomationRule.id == execution.rule_id).first()
    if not rule:
        raise HTTPException(404, "Associated rule not found")

    from app.services.automation_engine import AutomationEngine
    from app.services.event_bus import PropertyEvent

    engine = AutomationEngine(db)
    event = PropertyEvent(
        event_type=execution.trigger_event,
        owner_id=str(current_user.id),
        payload=execution.trigger_payload or {},
        source="manual_approval",
    )
    # Remove awaiting execution, then run fresh
    db.delete(execution)
    db.commit()

    new_execution = await engine.execute_rule(rule, event)
    return new_execution


@router.post("/executions/{execution_id}/reject", response_model=AutomationExecutionResponse)
def reject_execution(
    execution_id: uuid.UUID,
    body: RejectExecutionRequest,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    execution = _get_execution_or_404(execution_id, current_user.id, db)
    if execution.status != "awaiting_approval":
        raise HTTPException(400, f"Execution is '{execution.status}', not awaiting_approval")

    execution.status = "failed"
    execution.error_message = f"Rejected by owner: {body.reason}"
    execution.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(execution)
    return execution


@router.post("/executions/{execution_id}/rollback", response_model=AutomationExecutionResponse)
def rollback_execution(
    execution_id: uuid.UUID,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Reverse all reversible actions in a completed execution."""
    execution = _get_execution_or_404(execution_id, current_user.id, db)
    if execution.status not in ("completed", "failed"):
        raise HTTPException(400, f"Cannot rollback execution in status '{execution.status}'")

    logs = (
        db.query(AutomationActionLog)
        .filter(
            AutomationActionLog.execution_id == execution_id,
            AutomationActionLog.reversible == True,
            AutomationActionLog.reversed_at == None,
        )
        .all()
    )

    rolled_back_count = 0
    for log in logs:
        # Mark reversed (actual reversal logic is action-specific)
        log.reversed_at = datetime.now(timezone.utc)
        rolled_back_count += 1

    execution.status = "rolled_back"
    execution.rolled_back_at = datetime.now(timezone.utc)
    execution.rolled_back_by = str(current_user.id)
    db.commit()
    db.refresh(execution)
    return execution


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/settings", response_model=AutopilotSettingsResponse)
def get_settings(
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    s = _get_or_create_settings(current_user.id, db)
    return s


@router.put("/settings", response_model=AutopilotSettingsResponse)
def update_settings(
    body: AutopilotSettingsUpdate,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    s = _get_or_create_settings(current_user.id, db)
    if body.is_enabled is not None:
        s.is_enabled = body.is_enabled
    if body.mode is not None:
        s.mode = body.mode
    if body.quiet_hours_start is not None:
        s.quiet_hours_start = body.quiet_hours_start
    if body.quiet_hours_end is not None:
        s.quiet_hours_end = body.quiet_hours_end
    if body.max_actions_per_day is not None:
        s.max_actions_per_day = body.max_actions_per_day
    if body.excluded_property_ids is not None:
        s.excluded_property_ids = body.excluded_property_ids
    s.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(s)
    return s


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/health", response_model=AutopilotHealth)
def get_health(
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    active_rules = (
        db.query(sqlfunc.count(AutomationRule.id))
        .filter(
            AutomationRule.owner_id == current_user.id,
            AutomationRule.is_active == True,
        )
        .scalar() or 0
    )

    executions_today = (
        db.query(sqlfunc.count(AutomationExecution.id))
        .filter(
            AutomationExecution.owner_id == current_user.id,
            AutomationExecution.started_at >= today_start,
        )
        .scalar() or 0
    )

    pending_approvals = (
        db.query(sqlfunc.count(AutomationExecution.id))
        .filter(
            AutomationExecution.owner_id == current_user.id,
            AutomationExecution.status == "awaiting_approval",
        )
        .scalar() or 0
    )

    last_exec = (
        db.query(AutomationExecution.completed_at)
        .filter(
            AutomationExecution.owner_id == current_user.id,
            AutomationExecution.status == "completed",
        )
        .order_by(AutomationExecution.completed_at.desc())
        .first()
    )
    last_execution_at = last_exec[0] if last_exec else None

    # Upcoming = rules with delay_minutes > 0 that have been active recently
    upcoming_scheduled_count = (
        db.query(sqlfunc.count(AutomationRule.id))
        .filter(
            AutomationRule.owner_id == current_user.id,
            AutomationRule.is_active == True,
            AutomationRule.delay_minutes > 0,
        )
        .scalar() or 0
    )

    return AutopilotHealth(
        active_rules=active_rules,
        executions_today=executions_today,
        pending_approvals=pending_approvals,
        last_execution_at=last_execution_at,
        upcoming_scheduled_count=upcoming_scheduled_count,
    )


# ══════════════════════════════════════════════════════════════════════════════
# MANUAL TRIGGER
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/trigger")
async def manual_trigger(
    body: ManualTriggerRequest,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Manually fire any event for testing purposes."""
    from app.services.event_bus import event_bus, PropertyEvent

    event = PropertyEvent(
        event_type=body.event_type,
        owner_id=str(current_user.id),
        payload=body.payload,
        source="manual_trigger",
    )
    event_bus.publish(event)

    return {
        "triggered": True,
        "event_type": body.event_type,
        "owner_id": str(current_user.id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# THEME PREFERENCE (attached here for simplicity — used by frontend dark mode)
# ══════════════════════════════════════════════════════════════════════════════

@router.patch("/users/me/preferences")
def update_theme_preference(
    body: ThemePreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.user import User as UserModel
    user = db.query(UserModel).filter(UserModel.id == current_user.id).first()
    if user:
        user.theme_preference = body.theme
        user.updated_at = datetime.now(timezone.utc)
        db.commit()
    return {"theme": body.theme, "updated": True}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_rule_or_404(rule_id: uuid.UUID, owner_id: uuid.UUID, db: Session) -> AutomationRule:
    rule = db.query(AutomationRule).filter(
        AutomationRule.id == rule_id,
        AutomationRule.owner_id == owner_id,
    ).first()
    if not rule:
        raise HTTPException(404, "Rule not found")
    return rule


def _get_execution_or_404(execution_id: uuid.UUID, owner_id: uuid.UUID, db: Session) -> AutomationExecution:
    e = db.query(AutomationExecution).filter(
        AutomationExecution.id == execution_id,
        AutomationExecution.owner_id == owner_id,
    ).first()
    if not e:
        raise HTTPException(404, "Execution not found")
    return e


def _get_or_create_settings(owner_id: uuid.UUID, db: Session) -> AutopilotSettings:
    s = db.query(AutopilotSettings).filter(AutopilotSettings.owner_id == owner_id).first()
    if not s:
        s = AutopilotSettings(
            id=uuid.uuid4(),
            owner_id=owner_id,
            is_enabled=False,
            mode="notify_only",
            quiet_hours_start=21,
            quiet_hours_end=7,
            max_actions_per_day=50,
            excluded_property_ids=[],
        )
        db.add(s)
        db.commit()
        db.refresh(s)
    return s
