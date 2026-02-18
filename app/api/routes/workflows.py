"""
Workflow Automation Routes
Premium-gated CRUD for workflows + execution logs + scheduled event triggers.

Endpoints:
  GET    /workflows/templates          – list built-in templates
  GET    /workflows/logs               – paginated log list (all workflows)
  POST   /workflows/check-scheduled    – trigger time-based events (rent overdue, lease expiry)
  GET    /workflows                    – list owner's workflows
  POST   /workflows                    – create workflow
  GET    /workflows/{id}               – get workflow
  PUT    /workflows/{id}               – update workflow
  DELETE /workflows/{id}               – delete workflow
  GET    /workflows/{id}/logs          – logs for one workflow
"""
import json
import logging
import uuid as uuid_module
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.payment import Subscription, SubscriptionStatus, SubscriptionPlan
from app.models.user import User, UserRole
from app.models.workflow import (
    Workflow, WorkflowAction, WorkflowLog,
    TriggerEvent, ActionType, WorkflowStatus,
)
from app.schemas.workflow import (
    WorkflowCreate, WorkflowUpdate, WorkflowResponse,
    WorkflowLogResponse, WorkflowTemplate, WorkflowActionCreate,
)
from app.services.workflow_engine import WorkflowEngine

router = APIRouter(tags=["Workflows"])
logger = logging.getLogger(__name__)


# ═══════════════════════ PREMIUM GATE ═══════════════════════

def require_premium(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Allow ADMIN freely; require Professional/Enterprise subscription for others."""
    if current_user.role == UserRole.ADMIN:
        return current_user

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
            detail="Workflow Automation requires a Professional or Enterprise subscription.",
        )
    return current_user


# ═══════════════════════ HELPERS ═══════════════════════

def _save_actions(
    db: Session,
    workflow: Workflow,
    action_list: List[WorkflowActionCreate],
) -> None:
    """Delete existing actions and insert new ones."""
    for old in list(workflow.actions):
        db.delete(old)
    db.flush()

    for a in action_list:
        db.add(
            WorkflowAction(
                id=uuid_module.uuid4(),
                workflow_id=workflow.id,
                order=a.order,
                action_type=a.action_type,
                config=json.dumps(a.config),
                delay_minutes=a.delay_minutes,
            )
        )


# ═══════════════════════ BUILT-IN TEMPLATES ═══════════════════════

_TEMPLATES: List[WorkflowTemplate] = [
    WorkflowTemplate(
        id="tpl_rent_overdue_7",
        name="Rent Overdue – 7-Day Email Alert",
        description=(
            "Send the owner an email alert when a tenant's rent is 7 days overdue."
        ),
        trigger_event=TriggerEvent.RENT_OVERDUE,
        conditions={"days_overdue": "7"},
        actions=[
            WorkflowActionCreate(
                order=0,
                action_type=ActionType.SEND_EMAIL,
                config={
                    "to": "owner",
                    "subject": "Rent Overdue – {{tenant_name}}",
                    "body": (
                        "Hi,\n\n"
                        "{{tenant_name}} in Unit {{unit_number}} has not paid rent. "
                        "Amount due: KES {{amount_due}}.\n\n"
                        "Please follow up immediately.\n\n"
                        "— Propertech"
                    ),
                },
            ),
        ],
    ),
    WorkflowTemplate(
        id="tpl_rent_overdue_escalate",
        name="Rent Overdue – 14-Day Escalation",
        description=(
            "Escalate to the owner and create a follow-up task when rent is 14 days overdue."
        ),
        trigger_event=TriggerEvent.RENT_OVERDUE,
        conditions={"days_overdue": "14"},
        actions=[
            WorkflowActionCreate(
                order=0,
                action_type=ActionType.ESCALATE,
                config={
                    "notify_role": "owner",
                    "message": (
                        "ESCALATION: {{tenant_name}} (Unit {{unit_number}}) is 14 days overdue. "
                        "Amount: KES {{amount_due}}."
                    ),
                },
            ),
            WorkflowActionCreate(
                order=1,
                action_type=ActionType.CREATE_TASK,
                config={
                    "title": "Follow up on overdue rent – {{tenant_name}}",
                    "description": "Tenant {{tenant_name}} in Unit {{unit_number}} is 14 days overdue on rent.",
                    "due_in_days": 1,
                },
            ),
        ],
    ),
    WorkflowTemplate(
        id="tpl_lease_expiry_30",
        name="Lease Expiring in 30 Days – Renewal Reminder",
        description="Notify the owner 30 days before a lease expires so they can start renewal discussions.",
        trigger_event=TriggerEvent.LEASE_EXPIRING_SOON,
        conditions={"days_until_expiry": "30"},
        actions=[
            WorkflowActionCreate(
                order=0,
                action_type=ActionType.SEND_NOTIFICATION,
                config={
                    "title": "Lease Expiring Soon – {{tenant_name}}",
                    "body": (
                        "Lease for {{tenant_name}} in Unit {{unit_number}} "
                        "expires on {{lease_end}}. Start renewal now."
                    ),
                },
            ),
            WorkflowActionCreate(
                order=1,
                action_type=ActionType.SEND_EMAIL,
                config={
                    "to": "owner",
                    "subject": "Lease Renewal Reminder – {{tenant_name}}",
                    "body": (
                        "Hi,\n\n"
                        "The lease for {{tenant_name}} (Unit {{unit_number}}) expires on {{lease_end}}. "
                        "Please initiate renewal or find a replacement tenant.\n\n"
                        "— Propertech"
                    ),
                },
            ),
        ],
    ),
    WorkflowTemplate(
        id="tpl_maintenance_opened",
        name="New Maintenance Request – Owner Alert",
        description="Alert the property owner immediately when a maintenance request is opened.",
        trigger_event=TriggerEvent.MAINTENANCE_REQUEST_OPENED,
        actions=[
            WorkflowActionCreate(
                order=0,
                action_type=ActionType.SEND_NOTIFICATION,
                config={
                    "title": "New Maintenance Request",
                    "body": "A {{priority}} maintenance request has been opened: {{title}}.",
                },
            ),
        ],
    ),
    WorkflowTemplate(
        id="tpl_unit_vacated",
        name="Unit Vacated – Inspection Task",
        description="Create an inspection task automatically when a unit is vacated.",
        trigger_event=TriggerEvent.UNIT_VACATED,
        actions=[
            WorkflowActionCreate(
                order=0,
                action_type=ActionType.CREATE_TASK,
                config={
                    "title": "Move-out inspection – Unit {{unit_number}}",
                    "description": (
                        "Unit {{unit_number}} has been vacated. "
                        "Complete a move-out inspection and document the condition."
                    ),
                    "due_in_days": 2,
                },
            ),
            WorkflowActionCreate(
                order=1,
                action_type=ActionType.SEND_NOTIFICATION,
                config={
                    "title": "Unit Vacated – {{unit_number}}",
                    "body": "Unit {{unit_number}} is now vacant. Schedule inspection and cleaning.",
                },
            ),
        ],
    ),
    WorkflowTemplate(
        id="tpl_tenant_onboarded",
        name="New Tenant Welcome Email",
        description="Send a welcome email to the owner (and log a notification) when a tenant is onboarded.",
        trigger_event=TriggerEvent.TENANT_ONBOARDED,
        actions=[
            WorkflowActionCreate(
                order=0,
                action_type=ActionType.SEND_NOTIFICATION,
                config={
                    "title": "New Tenant Onboarded",
                    "body": "{{tenant_name}} has been added to Unit {{unit_number}}.",
                },
            ),
            WorkflowActionCreate(
                order=1,
                action_type=ActionType.SEND_EMAIL,
                config={
                    "to": "owner",
                    "subject": "New Tenant Added – {{tenant_name}}",
                    "body": (
                        "Hi,\n\n"
                        "{{tenant_name}} has been successfully onboarded to Unit {{unit_number}}. "
                        "Lease start: {{lease_start}}. Rent: KES {{rent_amount}}.\n\n"
                        "— Propertech"
                    ),
                },
            ),
        ],
    ),
]


# ═══════════════════════ ROUTES ═══════════════════════

# ── Static routes first (must come before /{workflow_id}) ──

@router.get("/templates", response_model=List[WorkflowTemplate])
def list_templates(
    current_user: User = Depends(require_premium),
):
    """Return built-in workflow templates the owner can install with one click."""
    return _TEMPLATES


@router.get("/logs", response_model=List[WorkflowLogResponse])
def list_all_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_premium),
):
    """Paginated log list across all workflows owned by the current user."""
    owner_wf_ids = (
        db.query(Workflow.id)
        .filter(Workflow.owner_id == current_user.id)
        .all()
    )
    ids = [r[0] for r in owner_wf_ids]
    if not ids:
        return []

    logs = (
        db.query(WorkflowLog)
        .filter(WorkflowLog.workflow_id.in_(ids))
        .order_by(WorkflowLog.triggered_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return logs


@router.post("/check-scheduled", status_code=status.HTTP_200_OK)
def check_scheduled_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_premium),
):
    """
    Evaluate time-based trigger events for this owner:
      - rent_overdue      (tenants whose balance_due > 0 and rent is past due)
      - lease_expiring_soon (tenants whose lease ends within 30 days)

    Can be called from a cron job (e.g. Railway Cron or Vercel Cron) or
    manually from the frontend dashboard.
    """
    from app.models.tenant import Tenant

    engine = WorkflowEngine(db)
    now = datetime.utcnow()
    fired = {"rent_overdue": 0, "lease_expiring_soon": 0}

    # ── Rent overdue ──────────────────────────────────────────────────
    overdue_tenants = (
        db.query(Tenant)
        .filter(
            Tenant.property_id.in_(
                db.query(Tenant.property_id).filter(
                    Tenant.status == "active"
                )
            ),
            Tenant.status == "active",
            Tenant.balance_due > 0,
        )
        .all()
    )

    for t in overdue_tenants:
        days_overdue = 0
        if t.lease_start:
            # Use the day-of-month the rent is due (lease_start day) to calculate overdue
            this_month_due = t.lease_start.replace(
                year=now.year, month=now.month
            )
            if this_month_due > now:
                # Roll back one month
                month = now.month - 1 or 12
                year = now.year if now.month > 1 else now.year - 1
                this_month_due = t.lease_start.replace(year=year, month=month)
            days_overdue = max(0, (now - this_month_due).days)

        context = {
            "tenant_id": str(t.id),
            "tenant_name": t.full_name,
            "tenant_email": t.email,
            "unit_id": str(t.unit_id) if t.unit_id else "",
            "unit_number": "",
            "property_id": str(t.property_id) if t.property_id else "",
            "amount_due": t.balance_due,
            "days_overdue": days_overdue,
            "owner_id": str(current_user.id),
            "owner_email": current_user.email,
        }
        fired["rent_overdue"] += engine.fire(
            TriggerEvent.RENT_OVERDUE, context, owner_id=current_user.id
        )

    # ── Lease expiring soon ────────────────────────────────────────────
    expiring_tenants = (
        db.query(Tenant)
        .filter(
            Tenant.status == "active",
            Tenant.lease_end.isnot(None),
            Tenant.lease_end.between(now, now + timedelta(days=30)),
        )
        .all()
    )

    for t in expiring_tenants:
        days_until_expiry = (t.lease_end - now).days if t.lease_end else 0
        context = {
            "tenant_id": str(t.id),
            "tenant_name": t.full_name,
            "tenant_email": t.email,
            "unit_id": str(t.unit_id) if t.unit_id else "",
            "unit_number": "",
            "property_id": str(t.property_id) if t.property_id else "",
            "lease_end": t.lease_end.strftime("%Y-%m-%d") if t.lease_end else "",
            "days_until_expiry": days_until_expiry,
            "owner_id": str(current_user.id),
            "owner_email": current_user.email,
        }
        fired["lease_expiring_soon"] += engine.fire(
            TriggerEvent.LEASE_EXPIRING_SOON, context, owner_id=current_user.id
        )

    return {
        "success": True,
        "message": "Scheduled event check complete.",
        "workflows_fired": fired,
        "checked_at": now.isoformat(),
    }


# ── Workflow CRUD ──────────────────────────────────────────────────────────

@router.get("/", response_model=List[WorkflowResponse])
def list_workflows(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_premium),
):
    """List all workflows belonging to the current owner."""
    workflows = (
        db.query(Workflow)
        .filter(Workflow.owner_id == current_user.id)
        .order_by(Workflow.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return workflows


@router.post("/", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
def create_workflow(
    payload: WorkflowCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_premium),
):
    """Create a new workflow (optionally with inline actions)."""
    wf = Workflow(
        id=uuid_module.uuid4(),
        owner_id=current_user.id,
        name=payload.name,
        description=payload.description,
        trigger_event=payload.trigger_event,
        conditions=json.dumps(payload.conditions) if payload.conditions else None,
        status=payload.status,
    )
    db.add(wf)
    db.flush()

    _save_actions(db, wf, payload.actions)

    db.commit()
    db.refresh(wf)
    return wf


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_premium),
):
    """Get a specific workflow by ID."""
    wf = (
        db.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.owner_id == current_user.id)
        .first()
    )
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return wf


@router.put("/{workflow_id}", response_model=WorkflowResponse)
def update_workflow(
    workflow_id: UUID,
    payload: WorkflowUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_premium),
):
    """Update a workflow's metadata and/or actions."""
    wf = (
        db.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.owner_id == current_user.id)
        .first()
    )
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    update_data = payload.dict(exclude_unset=True)

    # Handle conditions specially (serialize to JSON)
    if "conditions" in update_data:
        wf.conditions = (
            json.dumps(update_data.pop("conditions"))
            if update_data["conditions"]
            else None
        )
    else:
        update_data.pop("conditions", None)

    # Replace actions if provided
    if "actions" in update_data:
        _save_actions(db, wf, update_data.pop("actions"))

    for key, value in update_data.items():
        setattr(wf, key, value)

    db.commit()
    db.refresh(wf)
    return wf


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_premium),
):
    """Delete a workflow and all its actions/logs."""
    wf = (
        db.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.owner_id == current_user.id)
        .first()
    )
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    db.delete(wf)
    db.commit()
    return None


@router.get("/{workflow_id}/logs", response_model=List[WorkflowLogResponse])
def get_workflow_logs(
    workflow_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_premium),
):
    """Get execution logs for a specific workflow."""
    wf = (
        db.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.owner_id == current_user.id)
        .first()
    )
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    logs = (
        db.query(WorkflowLog)
        .filter(WorkflowLog.workflow_id == workflow_id)
        .order_by(WorkflowLog.triggered_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return logs
