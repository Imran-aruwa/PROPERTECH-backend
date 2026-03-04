"""
ARIA – PROPERTECH AI Chat Endpoint
POST /api/chat  JWT-protected, single request/response (no streaming).
"""

import os
import json
import logging
from datetime import datetime, date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

import anthropic

from app.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.models.property import Property, Unit
from app.models.tenant import Tenant
from app.models.mpesa import MpesaTransaction, ReconciliationStatus
from app.models.automation import AutomationExecution
from app.models.maintenance import MaintenanceRequest
from app.models.lease import Lease

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class ChatMessageIn(BaseModel):
    role: str
    content: str


class ChatContext(BaseModel):
    page: str = "/"
    role: str = "owner"
    user_id: str = ""
    owner_id: Optional[str] = None


class ChatRequest(BaseModel):
    messages: List[ChatMessageIn]
    context: ChatContext


class ChatResponse(BaseModel):
    reply: str
    role: str = "assistant"


# ── Live-data fetchers ─────────────────────────────────────────────────────────

def _fetch_owner_data(user: User, db: Session) -> dict:
    try:
        prop_count = (
            db.query(func.count(Property.id))
            .filter(Property.user_id == user.id)
            .scalar() or 0
        )

        prop_ids_q = db.query(Property.id).filter(Property.user_id == user.id).subquery()

        unit_count = (
            db.query(func.count(Unit.id))
            .filter(Unit.property_id.in_(prop_ids_q))
            .scalar() or 0
        )

        tenant_count = (
            db.query(func.count(Tenant.id))
            .filter(
                Tenant.property_id.in_(prop_ids_q),
                Tenant.status == "active",
            )
            .scalar() or 0
        )

        month_start = datetime.utcnow().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        collected = (
            db.query(func.coalesce(func.sum(MpesaTransaction.amount), 0))
            .filter(
                MpesaTransaction.owner_id == user.id,
                MpesaTransaction.reconciliation_status == ReconciliationStatus.MATCHED,
                MpesaTransaction.transaction_date >= month_start,
            )
            .scalar() or 0
        )

        overdue = (
            db.query(func.count(Tenant.id))
            .filter(
                Tenant.property_id.in_(prop_ids_q),
                Tenant.balance_due > 0,
                Tenant.status == "active",
            )
            .scalar() or 0
        )

        pending_auto = (
            db.query(func.count(AutomationExecution.id))
            .filter(
                AutomationExecution.owner_id == str(user.id),
                AutomationExecution.status == "awaiting_approval",
            )
            .scalar() or 0
        )

        unmatched = (
            db.query(func.count(MpesaTransaction.id))
            .filter(
                MpesaTransaction.owner_id == user.id,
                MpesaTransaction.reconciliation_status == ReconciliationStatus.UNMATCHED,
            )
            .scalar() or 0
        )

        return {
            "properties": prop_count,
            "units": unit_count,
            "active_tenants": tenant_count,
            "collected_this_month_kes": round(float(collected), 2),
            "tenants_with_balance_due": overdue,
            "pending_autopilot_approvals": pending_auto,
            "unmatched_mpesa_transactions": unmatched,
        }
    except Exception as exc:
        logger.error("Owner data fetch error: %s", exc)
        return {"note": "Live data temporarily unavailable"}


def _fetch_tenant_data(user: User, db: Session) -> dict:
    try:
        tenant = (
            db.query(Tenant)
            .filter(Tenant.user_id == user.id, Tenant.status == "active")
            .first()
        )
        if not tenant:
            return {"note": "No active tenant record found for this user"}

        unit = (
            db.query(Unit).filter(Unit.id == tenant.unit_id).first()
            if tenant.unit_id else None
        )
        prop = (
            db.query(Property).filter(Property.id == tenant.property_id).first()
            if tenant.property_id else None
        )

        lease = (
            db.query(Lease)
            .filter(Lease.tenant_id == tenant.id, Lease.status == "active")
            .first()
        )

        maint_count = 0
        latest_issue = None
        if tenant.unit_id:
            maint_count = (
                db.query(func.count(MaintenanceRequest.id))
                .filter(
                    MaintenanceRequest.unit_id == tenant.unit_id,
                    MaintenanceRequest.status.in_(["pending", "open", "in_progress"]),
                )
                .scalar() or 0
            )
            latest = (
                db.query(MaintenanceRequest)
                .filter(
                    MaintenanceRequest.unit_id == tenant.unit_id,
                    MaintenanceRequest.status.in_(["pending", "open", "in_progress"]),
                )
                .order_by(MaintenanceRequest.created_at.desc())
                .first()
            )
            if latest:
                desc = getattr(latest, "description", None) or getattr(latest, "title", "")
                latest_issue = str(desc)[:100]

        return {
            "unit_number": unit.unit_number if unit else "N/A",
            "property_name": prop.name if prop else "N/A",
            "monthly_rent_kes": tenant.rent_amount,
            "balance_due_kes": round(float(tenant.balance_due), 2),
            "last_payment_date": (
                tenant.last_payment_date.date().isoformat()
                if tenant.last_payment_date else "No payments recorded"
            ),
            "lease_start": (
                lease.start_date.date().isoformat() if lease and lease.start_date else "N/A"
            ),
            "lease_end": (
                lease.end_date.date().isoformat() if lease and lease.end_date else "N/A"
            ),
            "lease_status": str(lease.status).split(".")[-1] if lease else "N/A",
            "open_maintenance_requests": maint_count,
            "latest_maintenance_issue": latest_issue or "None",
        }
    except Exception as exc:
        logger.error("Tenant data fetch error: %s", exc)
        return {"note": "Live data temporarily unavailable"}


def _fetch_agent_data(user: User, db: Session) -> dict:
    try:
        prop_count = (
            db.query(func.count(Property.id))
            .filter(Property.user_id == user.id)
            .scalar() or 0
        )
        prop_ids_q = db.query(Property.id).filter(Property.user_id == user.id).subquery()

        unit_count = (
            db.query(func.count(Unit.id))
            .filter(Unit.property_id.in_(prop_ids_q))
            .scalar() or 0
        )
        occupied = (
            db.query(func.count(Unit.id))
            .filter(Unit.property_id.in_(prop_ids_q), Unit.status == "occupied")
            .scalar() or 0
        )
        occ_rate = round((occupied / unit_count * 100), 1) if unit_count > 0 else 0.0

        return {
            "properties_managed": prop_count,
            "total_units": unit_count,
            "occupied_units": occupied,
            "occupancy_rate_pct": occ_rate,
        }
    except Exception as exc:
        logger.error("Agent data fetch error: %s", exc)
        return {"note": "Live data temporarily unavailable"}


def _fetch_live_data(user: User, db: Session, role: str) -> dict:
    if role == "tenant":
        return _fetch_tenant_data(user, db)
    if role == "agent":
        return _fetch_agent_data(user, db)
    # owner, staff, admin, caretaker → owner-level view
    return _fetch_owner_data(user, db)


# ── System prompt ──────────────────────────────────────────────────────────────

_ARIA_KNOWLEDGE = """
YOUR KNOWLEDGE — You know the following about PROPERTECH in full detail:

PLATFORM OVERVIEW
PROPERTECH is a Kenyan property management platform. It handles properties, units, tenants,
leases, payments via M-Pesa, maintenance requests, and automated workflows.

M-PESA PAYMENTS
Rent is paid via M-Pesa Paybill or Till number. Owners configure their shortcode in the
M-Pesa Settings page. Tenants pay by going to M-Pesa > Lipa Na M-Pesa > Pay Bill, entering
the business number and their unit number as account reference. The system auto-reconciles
incoming payments to the correct tenant using phone number, amount, and account reference
matching. Confidence scores: 90-100 = auto-matched, 70-89 = auto-matched with review flag,
below 70 = manual match required. Owners can initiate an STK Push from the M-Pesa dashboard
to request payment directly to a tenant's phone. Reminders are sent automatically before and
after due date via SMS.

LEASES
Each tenant has one active lease linked to a unit. Leases have a start date, end date, monthly
rent amount, deposit, and status (active/pending_renewal/expired). The system automatically
sends renewal notices 60, 30, and 7 days before expiry. Owners can generate a renewal document
from the Leases page. When a lease expires the unit automatically moves to vacant status.

UNITS AND PROPERTIES
Properties contain units. Each unit has a unit number, type, monthly rent, status
(occupied/vacant/reserved/maintenance). Vacancy listings are auto-created when a unit becomes
vacant. Owners can manage all units from the Properties page.

MAINTENANCE REQUESTS
Tenants submit maintenance requests from their dashboard. Each request has a category,
description, priority (low/normal/urgent), and status (open/in_progress/resolved). Owners and
staff can assign requests to a caretaker and update status. The autopilot can automatically
escalate requests open more than 48 hours.

AUTOPILOT — AUTONOMOUS PROPERTY MANAGER MODE
The autopilot runs automated workflows triggered by events. It has three modes: Full Auto
(acts immediately), Approval Required (queues actions for owner to approve), Notify Only
(alerts owner but takes no action). Owners configure rules on the Autopilot > Rules page.
System templates are pre-built chains owners can activate with one click. Examples: when
payment is received → generate receipt + cancel reminders + mark unit paid. When rent is 3
days overdue → apply late fee + send SMS notice. When unit becomes vacant → create listing +
schedule move-out inspection. Owners can see all actions taken in Autopilot > Executions.
Any completed action can be rolled back from there. Quiet hours prevent actions firing at
night (default 9pm–7am EAT).

USER ROLES
Owner: full access to all properties they own. Can configure M-Pesa, autopilot, reminders.
Sees all analytics.
Tenant: sees only their own unit, lease, payment history, and can submit maintenance requests.
Agent: manages properties on behalf of owners. Same access as owner but scoped to assigned
properties.
Staff: caretakers or admin staff. Can update maintenance requests and view assigned units.

RESPONSE RULES
- Always address the user by first name on the first message.
- If the user asks about their specific data (balance, lease dates, payment status) use the
  LIVE DATA SNAPSHOT above to answer accurately — do not say you cannot access their data.
- If asked to do something that requires a UI action (submit maintenance request, make a
  payment), guide them step by step — tell them exactly which menu to click.
- Keep answers concise. Use bullet points for steps. Use KES for currency amounts.
- If you genuinely do not know something, say so clearly — do not guess.
- Never discuss anything unrelated to property management or PROPERTECH.
- You are ARIA, not Claude. Do not reveal you are built on Claude or any other AI model.
"""


def _build_system_prompt(user: User, context: ChatContext, live_data: dict) -> str:
    first_name = (user.full_name or "User").split()[0]
    live_json = json.dumps(live_data, indent=2, default=str)
    return (
        "You are ARIA — the PROPERTECH AI Assistant. You are embedded inside the PROPERTECH "
        "property management platform used in Kenya. You are helpful, concise, and professional. "
        "You know everything about how PROPERTECH works.\n\n"
        f"CURRENT USER\nName: {first_name}\nRole: {context.role}\n"
        f"Page they are on: {context.page}\n\n"
        f"LIVE DATA SNAPSHOT (as of right now)\n```json\n{live_json}\n```\n"
        f"{_ARIA_KNOWLEDGE}"
    )


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
def chat_endpoint(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="AI service not configured — set ANTHROPIC_API_KEY")

    # 1. Live data
    live_data = _fetch_live_data(current_user, db, request.context.role)

    # 2. System prompt
    system_prompt = _build_system_prompt(current_user, request.context, live_data)

    # 3. Filter & validate messages
    messages = [
        {"role": m.role, "content": m.content}
        for m in request.messages
        if m.content.strip() and m.role in ("user", "assistant")
    ]
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    # 4. Call Claude
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
        reply_text = response.content[0].text
    except anthropic.APIStatusError as exc:
        logger.error("Anthropic API error %s: %s", exc.status_code, exc.message)
        raise HTTPException(status_code=502, detail="AI service temporarily unavailable")
    except Exception as exc:
        logger.error("Chat endpoint error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error processing chat request")

    return ChatResponse(reply=reply_text, role="assistant")
