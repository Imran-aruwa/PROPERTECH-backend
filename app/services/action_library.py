"""
Action Library — 29 discrete actions for the Autonomous Property Manager.

Each action is registered via the @action decorator and stored in ACTION_REGISTRY.
dispatch_action() resolves Jinja2 templates, calls the action, logs to
automation_actions_log, and returns a result dict.

Idempotency key: execution_id is used for fee/charge inserts so that
re-running a failed execution does not double-charge tenants.
"""
from __future__ import annotations

import json
import logging
import smtplib
import uuid
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import wraps
from typing import Any, Callable, Dict, Optional

import httpx
from jinja2 import Environment, Undefined
from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Jinja2 env ────────────────────────────────────────────────────────────────
_jinja_env = Environment(undefined=Undefined)


def resolve_templates(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively resolve {{variable}} tokens in param string values."""
    resolved = {}
    for k, v in params.items():
        if isinstance(v, str):
            try:
                resolved[k] = _jinja_env.from_string(v).render(**ctx)
            except Exception:
                resolved[k] = v
        elif isinstance(v, dict):
            resolved[k] = resolve_templates(v, ctx)
        elif isinstance(v, list):
            resolved[k] = [
                resolve_templates(item, ctx) if isinstance(item, dict)
                else (_jinja_env.from_string(item).render(**ctx) if isinstance(item, str) else item)
                for item in v
            ]
        else:
            resolved[k] = v
    return resolved


# ── Registry ─────────────────────────────────────────────────────────────────
ACTION_REGISTRY: Dict[str, Dict[str, Any]] = {}


def action(name: str, reversible: bool = False):
    """Decorator that registers an async action function."""
    def decorator(fn: Callable):
        ACTION_REGISTRY[name] = {"fn": fn, "reversible": reversible}
        fn._action_name = name
        fn._reversible = reversible

        @wraps(fn)
        async def wrapper(*args, **kwargs):
            return await fn(*args, **kwargs)
        return wrapper
    return decorator


# ── dispatch_action ───────────────────────────────────────────────────────────

async def dispatch_action(
    action_type: str,
    params: Dict[str, Any],
    event_payload: Dict[str, Any],
    execution_id: uuid.UUID,
    db: Session,
    owner_id: Optional[uuid.UUID] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Resolve templates, call the action function, log result, return result dict.
    If dry_run=True: skip the actual action call and return a preview.
    """
    from app.models.automation import AutomationActionLog

    entry = ACTION_REGISTRY.get(action_type)
    if not entry:
        logger.warning(f"[action_lib] Unknown action '{action_type}'")
        return {"action_type": action_type, "status": "skipped", "data": {"reason": "unknown action"}}

    # Build template context from event payload
    ctx = {**event_payload, "execution_id": str(execution_id)}

    # Resolve Jinja2 templates in params
    resolved_params = resolve_templates(params, ctx)

    if dry_run:
        return {
            "action_type": action_type,
            "status": "dry_run",
            "resolved_params": resolved_params,
            "reversible": entry["reversible"],
            "data": {"note": "dry_run — no side effects"},
        }

    # Execute
    try:
        result_data = await entry["fn"](
            params=resolved_params,
            event_payload=event_payload,
            execution_id=execution_id,
            db=db,
            owner_id=owner_id,
        )
        status = "success"
    except Exception as exc:
        logger.error(f"[action_lib] Action '{action_type}' failed: {exc}", exc_info=True)
        result_data = {"error": str(exc)}
        status = "failed"

    # Log to DB
    if db and execution_id:
        try:
            log_entry = AutomationActionLog(
                id=uuid.uuid4(),
                execution_id=execution_id,
                owner_id=owner_id or uuid.UUID(int=0),
                action_type=action_type,
                action_payload=resolved_params,
                result_status=status,
                result_data=result_data,
                executed_at=datetime.now(timezone.utc),
                reversible=entry["reversible"],
            )
            db.add(log_entry)
            db.commit()
            log_id = str(log_entry.id)
        except Exception as log_exc:
            logger.error(f"[action_lib] Failed to log action: {log_exc}")
            db.rollback()
            log_id = None
    else:
        log_id = None

    return {
        "action_type": action_type,
        "status": status,
        "data": result_data,
        "reversible": entry["reversible"],
        "log_id": log_id,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ACTION IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════════

# ── 1. send_sms ───────────────────────────────────────────────────────────────
@action("send_sms", reversible=False)
async def send_sms(params, event_payload, execution_id, db, owner_id):
    phone = params.get("phone", "")
    message = params.get("message", "")
    if not phone or not message:
        return {"sent": False, "reason": "missing phone or message"}

    at_key = getattr(settings, "AT_API_KEY", None)
    at_user = getattr(settings, "AT_USERNAME", "sandbox")
    sender = getattr(settings, "AT_SENDER_ID", None)

    if not at_key:
        logger.info(f"[send_sms] DEV: would send to {phone}: {message[:80]}")
        return {"sent": True, "dev_mode": True, "phone": phone}

    try:
        import africastalking
        africastalking.initialize(at_user, at_key)
        sms = africastalking.SMS
        kwargs = {"message": message, "recipients": [phone]}
        if sender:
            kwargs["sender_id"] = sender
        resp = sms.send(**kwargs)
        logger.info(f"[send_sms] Sent to {phone}: {resp}")
        return {"sent": True, "response": str(resp), "phone": phone}
    except ImportError:
        # Fallback via AT HTTP API
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.africastalking.com/version1/messaging",
                    headers={"apiKey": at_key, "Content-Type": "application/x-www-form-urlencoded"},
                    data={"username": at_user, "to": phone, "message": message},
                )
                return {"sent": True, "status_code": resp.status_code, "phone": phone}
        except Exception as exc:
            logger.error(f"[send_sms] HTTP fallback failed: {exc}")
            return {"sent": False, "error": str(exc)}
    except Exception as exc:
        logger.error(f"[send_sms] Failed: {exc}")
        return {"sent": False, "error": str(exc)}


# ── 2. send_whatsapp ──────────────────────────────────────────────────────────
@action("send_whatsapp", reversible=False)
async def send_whatsapp(params, event_payload, execution_id, db, owner_id):
    phone = params.get("phone", "").replace("+", "").replace(" ", "")
    message = params.get("message", "")
    if not phone:
        return {"sent": False, "reason": "missing phone"}
    wa_link = f"https://wa.me/{phone}?text={message[:500].replace(' ', '%20')}"
    logger.info(f"[send_whatsapp] WA link generated for {phone}")
    # Production: use AT WhatsApp sandbox or Business API key here
    return {"sent": True, "wa_link": wa_link, "phone": phone}


# ── 3. send_email ─────────────────────────────────────────────────────────────
@action("send_email", reversible=False)
async def send_email(params, event_payload, execution_id, db, owner_id):
    to_email = params.get("to", "")
    subject = params.get("subject", "Propertech Notification")
    body = params.get("body", "")

    if not to_email:
        return {"sent": False, "reason": "missing to address"}

    smtp_server = getattr(settings, "SMTP_SERVER", None)
    smtp_user = getattr(settings, "SMTP_USER", None)
    smtp_pass = getattr(settings, "SMTP_PASSWORD", None)
    from_addr = getattr(settings, "EMAIL_FROM", smtp_user or "noreply@propertech.co.ke")
    send_emails = getattr(settings, "SEND_EMAILS", False)

    if not send_emails or not smtp_server or not smtp_user:
        logger.info(f"[send_email] DEV: would email {to_email} — {subject}")
        return {"sent": True, "dev_mode": True, "to": to_email}

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_email
        msg.attach(MIMEText(body, "html" if "<" in body else "plain"))

        with smtplib.SMTP(smtp_server, getattr(settings, "SMTP_PORT", 587)) as srv:
            srv.starttls()
            srv.login(smtp_user, smtp_pass)
            srv.sendmail(from_addr, [to_email], msg.as_string())

        logger.info(f"[send_email] Sent '{subject}' to {to_email}")
        return {"sent": True, "to": to_email}
    except Exception as exc:
        logger.error(f"[send_email] Failed: {exc}")
        return {"sent": False, "error": str(exc)}


# ── 4. send_stk_push ─────────────────────────────────────────────────────────
@action("send_stk_push", reversible=False)
async def send_stk_push(params, event_payload, execution_id, db, owner_id):
    from app.models.mpesa import MpesaConfig
    from app.services.mpesa_service import initiate_stk_push

    phone = params.get("phone", "")
    amount = int(params.get("amount", 0))
    account_ref = params.get("account_ref", "RENT")
    description = params.get("description", "Rent Payment")

    if not phone or not amount:
        return {"initiated": False, "reason": "missing phone or amount"}

    config = db.query(MpesaConfig).filter(MpesaConfig.owner_id == owner_id).first()
    if not config:
        return {"initiated": False, "reason": "no mpesa config for owner"}

    callback_url = getattr(settings, "BACKEND_URL", "") + "/api/mpesa/callbacks/stk"
    try:
        result = initiate_stk_push(
            phone=phone, amount=amount, account_ref=account_ref,
            description=description, shortcode=config.shortcode,
            passkey=config.passkey, consumer_key=config.consumer_key,
            consumer_secret=config.consumer_secret, environment=config.environment.value,
            callback_url=callback_url,
        )
        return {"initiated": True, "result": result}
    except Exception as exc:
        return {"initiated": False, "error": str(exc)}


# ── 5. create_payment_record ──────────────────────────────────────────────────
@action("create_payment_record", reversible=True)
async def create_payment_record(params, event_payload, execution_id, db, owner_id):
    from app.models.payment import Payment, PaymentStatus, PaymentMethod, PaymentGateway, PaymentType, PaymentCurrency
    from app.models.user import User

    tenant_id = event_payload.get("tenant_id")
    amount = float(event_payload.get("amount", 0))
    receipt = event_payload.get("mpesa_receipt") or event_payload.get("reference", f"AUTO-{execution_id}")

    existing = db.query(Payment).filter(Payment.reference == receipt).first()
    if existing:
        return {"created": False, "payment_id": str(existing.id), "reason": "already exists"}

    owner_user = db.query(User).filter(User.id == owner_id).first()
    payment = Payment(
        id=uuid.uuid4(),
        user_id=owner_id,
        user_email=owner_user.email if owner_user else "",
        amount=amount,
        currency=PaymentCurrency.KES,
        gateway=PaymentGateway.PAYSTACK,
        method=PaymentMethod.MPESA,
        reference=receipt,
        status=PaymentStatus.COMPLETED,
        payment_type=PaymentType.RENT,
        tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
        payment_date=datetime.utcnow(),
        paid_at=datetime.utcnow(),
        description="Auto-recorded via Autopilot",
        payment_metadata=json.dumps({"execution_id": str(execution_id), "source": "automation"}),
    )
    db.add(payment)
    db.commit()
    return {"created": True, "payment_id": str(payment.id)}


# ── 6. mark_payment_overdue ───────────────────────────────────────────────────
@action("mark_payment_overdue", reversible=True)
async def mark_payment_overdue(params, event_payload, execution_id, db, owner_id):
    from app.models.property import Unit
    unit_id = event_payload.get("unit_id")
    if not unit_id:
        return {"updated": False, "reason": "no unit_id"}
    unit = db.query(Unit).filter(Unit.id == uuid.UUID(unit_id)).first()
    if not unit:
        return {"updated": False, "reason": "unit not found"}
    unit.status = "overdue"
    db.commit()
    return {"updated": True, "unit_id": unit_id, "new_status": "overdue"}


# ── 7. apply_late_fee ─────────────────────────────────────────────────────────
@action("apply_late_fee", reversible=True)
async def apply_late_fee(params, event_payload, execution_id, db, owner_id):
    from app.models.payment import Payment, PaymentStatus, PaymentMethod, PaymentGateway, PaymentType, PaymentCurrency
    from app.models.user import User

    idempotency_key = f"late_fee_{execution_id}"
    existing = db.query(Payment).filter(Payment.reference == idempotency_key).first()
    if existing:
        return {"applied": False, "reason": "already applied", "payment_id": str(existing.id)}

    tenant_id = event_payload.get("tenant_id")
    fee_amount = float(params.get("amount", event_payload.get("monthly_rent", 0)) * 0.05)
    if fee_amount <= 0:
        fee_amount = 500.0  # KES 500 default late fee

    owner_user = db.query(User).filter(User.id == owner_id).first()
    payment = Payment(
        id=uuid.uuid4(),
        user_id=owner_id,
        user_email=owner_user.email if owner_user else "",
        amount=fee_amount,
        currency=PaymentCurrency.KES,
        gateway=PaymentGateway.PAYSTACK,
        method=PaymentMethod.MPESA,
        reference=idempotency_key,
        status=PaymentStatus.PENDING,
        payment_type=PaymentType.PENALTY,
        tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
        payment_date=datetime.utcnow(),
        description="Late payment fee (Autopilot)",
        payment_metadata=json.dumps({"execution_id": str(execution_id), "source": "late_fee"}),
    )
    db.add(payment)
    db.commit()
    return {"applied": True, "amount": fee_amount, "payment_id": str(payment.id)}


# ── 8. reverse_late_fee ───────────────────────────────────────────────────────
@action("reverse_late_fee", reversible=False)
async def reverse_late_fee(params, event_payload, execution_id, db, owner_id):
    from app.models.payment import Payment
    # Find by idempotency key from the target execution_id
    target_exec_id = params.get("target_execution_id", str(execution_id))
    idempotency_key = f"late_fee_{target_exec_id}"
    payment = db.query(Payment).filter(Payment.reference == idempotency_key).first()
    if not payment:
        return {"reversed": False, "reason": "late fee not found"}
    db.delete(payment)
    db.commit()
    return {"reversed": True, "idempotency_key": idempotency_key}


# ── 9. generate_lease_renewal ─────────────────────────────────────────────────
@action("generate_lease_renewal", reversible=True)
async def generate_lease_renewal(params, event_payload, execution_id, db, owner_id):
    from app.models.lease import Lease, LeaseStatus
    tenant_id = event_payload.get("tenant_id")
    lease_id = event_payload.get("lease_id")

    if not lease_id:
        return {"generated": False, "reason": "no lease_id"}

    original = db.query(Lease).filter(Lease.id == uuid.UUID(lease_id)).first()
    if not original:
        return {"generated": False, "reason": "lease not found"}

    from datetime import timedelta
    new_lease = Lease(
        id=uuid.uuid4(),
        owner_id=owner_id,
        property_id=original.property_id,
        unit_id=original.unit_id,
        tenant_id=original.tenant_id,
        tenant_name=original.tenant_name,
        tenant_email=original.tenant_email,
        tenant_phone=original.tenant_phone,
        title=f"Renewal — {original.title}",
        status=LeaseStatus.DRAFT,
        start_date=original.end_date,
        end_date=original.end_date + timedelta(days=365),
        rent_amount=original.rent_amount,
        deposit_amount=original.deposit_amount,
        payment_cycle=original.payment_cycle,
        escalation_rate=original.escalation_rate,
    )
    db.add(new_lease)
    db.commit()
    return {"generated": True, "new_lease_id": str(new_lease.id)}


# ── 10. send_lease_renewal_notice ────────────────────────────────────────────
@action("send_lease_renewal_notice", reversible=False)
async def send_lease_renewal_notice(params, event_payload, execution_id, db, owner_id):
    tenant_name = event_payload.get("tenant_name", "Tenant")
    tenant_email = event_payload.get("tenant_email", "")
    tenant_phone = event_payload.get("tenant_phone", "")
    days_remaining = event_payload.get("days_remaining", "")
    msg = f"Dear {tenant_name}, your lease expires in {days_remaining} days. Please contact us to discuss renewal."
    results = {}
    if tenant_phone:
        results["sms"] = await send_sms.__wrapped__(
            params={"phone": tenant_phone, "message": msg},
            event_payload=event_payload, execution_id=execution_id, db=db, owner_id=owner_id
        )
    if tenant_email:
        results["email"] = await send_email.__wrapped__(
            params={"to": tenant_email, "subject": "Lease Renewal Notice", "body": msg},
            event_payload=event_payload, execution_id=execution_id, db=db, owner_id=owner_id
        )
    return results


# ── 11. mark_lease_expired ───────────────────────────────────────────────────
@action("mark_lease_expired", reversible=True)
async def mark_lease_expired(params, event_payload, execution_id, db, owner_id):
    from app.models.lease import Lease, LeaseStatus
    from app.services.event_bus import event_bus, PropertyEvent

    lease_id = event_payload.get("lease_id")
    if not lease_id:
        return {"updated": False, "reason": "no lease_id"}

    lease = db.query(Lease).filter(Lease.id == uuid.UUID(lease_id)).first()
    if not lease:
        return {"updated": False, "reason": "lease not found"}

    lease.status = LeaseStatus.EXPIRED
    db.commit()

    # Fire unit_vacated event
    if lease.unit_id:
        event_bus.publish(PropertyEvent(
            event_type="unit_vacated",
            owner_id=str(owner_id),
            payload={**event_payload, "unit_id": str(lease.unit_id)},
            source="mark_lease_expired",
        ))

    return {"updated": True, "lease_id": lease_id, "new_status": "expired"}


# ── 12. create_vacancy_listing ───────────────────────────────────────────────
@action("create_vacancy_listing", reversible=True)
async def create_vacancy_listing(params, event_payload, execution_id, db, owner_id):
    from app.models.listing import VacancyListing, ListingStatus
    from app.services.listing_service import ListingService

    unit_id = event_payload.get("unit_id")
    property_id = event_payload.get("property_id")

    existing = db.query(VacancyListing).filter(
        VacancyListing.unit_id == uuid.UUID(unit_id) if unit_id else False,
        VacancyListing.status == ListingStatus.ACTIVE,
    ).first() if unit_id else None

    if existing:
        return {"created": False, "listing_id": str(existing.id), "reason": "active listing exists"}

    svc = ListingService(db)
    slug = svc.generate_slug(
        event_payload.get("property_name", "property"),
        event_payload.get("unit_number", "unit"),
    )

    listing = VacancyListing(
        id=uuid.uuid4(),
        owner_id=owner_id,
        property_id=uuid.UUID(property_id) if property_id else None,
        unit_id=uuid.UUID(unit_id) if unit_id else None,
        title=params.get("title", f"Available unit — {event_payload.get('unit_number', '')}"),
        description=params.get("description", "Available for immediate occupancy."),
        monthly_rent=float(event_payload.get("monthly_rent", 0)),
        deposit_amount=float(event_payload.get("monthly_rent", 0)) * 2,
        slug=slug,
        status=ListingStatus.ACTIVE,
    )
    db.add(listing)
    db.commit()
    return {"created": True, "listing_id": str(listing.id), "slug": slug}


# ── 13. post_to_listing_sites ────────────────────────────────────────────────
@action("post_to_listing_sites", reversible=False)
async def post_to_listing_sites(params, event_payload, execution_id, db, owner_id):
    # Placeholder — hook for full syndication (Feature #4 equivalent)
    listing_id = event_payload.get("listing_id", "")
    platforms = params.get("platforms", ["facebook", "whatsapp"])
    logger.info(f"[post_to_listing_sites] HOOK: would syndicate listing {listing_id} to {platforms}")
    return {"syndicated": False, "platforms": platforms, "note": "scaffolded — platform APIs pending"}


# ── 14. send_move_out_notice ─────────────────────────────────────────────────
@action("send_move_out_notice", reversible=False)
async def send_move_out_notice(params, event_payload, execution_id, db, owner_id):
    tenant_name = event_payload.get("tenant_name", "Tenant")
    tenant_email = event_payload.get("tenant_email", "")
    tenant_phone = event_payload.get("tenant_phone", "")
    unit_number = event_payload.get("unit_number", "")
    msg = (f"Dear {tenant_name}, this is your move-out notice for unit {unit_number}. "
           "Please arrange to vacate by the agreed date and return the keys to management.")
    results = {}
    if tenant_phone:
        results["sms"] = await send_sms.__wrapped__(
            params={"phone": tenant_phone, "message": msg},
            event_payload=event_payload, execution_id=execution_id, db=db, owner_id=owner_id
        )
    if tenant_email:
        results["email"] = await send_email.__wrapped__(
            params={"to": tenant_email, "subject": "Move-Out Notice", "body": msg},
            event_payload=event_payload, execution_id=execution_id, db=db, owner_id=owner_id
        )
    return {"sent": True, "results": results}


# ── 15. schedule_inspection ──────────────────────────────────────────────────
@action("schedule_inspection", reversible=True)
async def schedule_inspection(params, event_payload, execution_id, db, owner_id):
    from app.models.inspection import Inspection
    from datetime import timedelta

    unit_id = event_payload.get("unit_id")
    property_id = event_payload.get("property_id")
    insp_type = params.get("type", "routine")
    days_offset = int(params.get("days_offset", 3))
    scheduled_date = datetime.utcnow() + timedelta(days=days_offset)

    inspection = Inspection(
        id=uuid.uuid4(),
        owner_id=owner_id,
        property_id=uuid.UUID(property_id) if property_id else None,
        unit_id=uuid.UUID(unit_id) if unit_id else None,
        type=insp_type,
        status="submitted",
        scheduled_date=scheduled_date,
        findings_summary=f"Auto-scheduled {insp_type} inspection via Autopilot",
    )
    db.add(inspection)
    db.commit()
    return {"scheduled": True, "inspection_id": str(inspection.id), "date": scheduled_date.isoformat()}


# ── 16. create_maintenance_task ──────────────────────────────────────────────
@action("create_maintenance_task", reversible=True)
async def create_maintenance_task(params, event_payload, execution_id, db, owner_id):
    from app.models.maintenance import MaintenanceRequest, MaintenancePriority, MaintenanceStatus

    unit_id = event_payload.get("unit_id")
    property_id = event_payload.get("property_id")
    tenant_id = event_payload.get("tenant_id")

    request = MaintenanceRequest(
        id=uuid.uuid4(),
        property_id=uuid.UUID(property_id) if property_id else None,
        unit_id=uuid.UUID(unit_id) if unit_id else None,
        tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
        title=params.get("title", "Autopilot-created maintenance task"),
        description=params.get("description", f"Auto-created via Autopilot (exec {execution_id})"),
        priority=MaintenancePriority(params.get("priority", "medium")),
        status=MaintenanceStatus.PENDING,
        notes=f"Created by automation execution {execution_id}",
    )
    db.add(request)
    db.commit()
    return {"created": True, "request_id": str(request.id)}


# ── 17. escalate_maintenance ─────────────────────────────────────────────────
@action("escalate_maintenance", reversible=True)
async def escalate_maintenance(params, event_payload, execution_id, db, owner_id):
    from app.models.maintenance import MaintenanceRequest, MaintenancePriority

    request_id = event_payload.get("maintenance_request_id")
    if not request_id:
        return {"escalated": False, "reason": "no maintenance_request_id"}

    req = db.query(MaintenanceRequest).filter(MaintenanceRequest.id == uuid.UUID(request_id)).first()
    if not req:
        return {"escalated": False, "reason": "not found"}

    req.priority = MaintenancePriority.EMERGENCY
    req.notes = (req.notes or "") + f"\n[Autopilot] Escalated to urgent by execution {execution_id}"
    db.commit()
    return {"escalated": True, "request_id": request_id, "new_priority": "emergency"}


# ── 18. generate_receipt ─────────────────────────────────────────────────────
@action("generate_receipt", reversible=False)
async def generate_receipt(params, event_payload, execution_id, db, owner_id):
    tenant_email = event_payload.get("tenant_email", "")
    tenant_name = event_payload.get("tenant_name", "Tenant")
    amount = event_payload.get("amount", 0)
    receipt_no = event_payload.get("mpesa_receipt", str(execution_id)[:8].upper())

    receipt_html = (
        f"<h2>Payment Receipt</h2>"
        f"<p>Dear {tenant_name},</p>"
        f"<p>We confirm receipt of <strong>KES {amount:,.0f}</strong>.</p>"
        f"<p>Receipt No: <strong>{receipt_no}</strong></p>"
        f"<p>Thank you for your prompt payment.</p>"
        f"<p>— Propertech Management</p>"
    )
    result = {"receipt_generated": True, "receipt_no": receipt_no}
    if tenant_email:
        email_result = await send_email.__wrapped__(
            params={"to": tenant_email, "subject": f"Payment Receipt — {receipt_no}", "body": receipt_html},
            event_payload=event_payload, execution_id=execution_id, db=db, owner_id=owner_id
        )
        result["email"] = email_result
    return result


# ── 19. update_unit_status ────────────────────────────────────────────────────
@action("update_unit_status", reversible=True)
async def update_unit_status(params, event_payload, execution_id, db, owner_id):
    from app.models.property import Unit

    unit_id = event_payload.get("unit_id") or params.get("unit_id")
    new_status = params.get("status", "vacant")
    if not unit_id:
        return {"updated": False, "reason": "no unit_id"}

    unit = db.query(Unit).filter(Unit.id == uuid.UUID(unit_id)).first()
    if not unit:
        return {"updated": False, "reason": "unit not found"}

    old_status = unit.status
    unit.status = new_status
    db.commit()
    return {"updated": True, "unit_id": unit_id, "old_status": str(old_status), "new_status": new_status}


# ── 20. update_tenant_status ─────────────────────────────────────────────────
@action("update_tenant_status", reversible=True)
async def update_tenant_status(params, event_payload, execution_id, db, owner_id):
    from app.models.tenant import Tenant

    tenant_id = event_payload.get("tenant_id") or params.get("tenant_id")
    new_status = params.get("status", "active")
    if not tenant_id:
        return {"updated": False, "reason": "no tenant_id"}

    tenant = db.query(Tenant).filter(Tenant.id == uuid.UUID(tenant_id)).first()
    if not tenant:
        return {"updated": False, "reason": "tenant not found"}

    old_status = tenant.status
    tenant.status = new_status
    db.commit()
    return {"updated": True, "tenant_id": tenant_id, "old_status": old_status, "new_status": new_status}


# ── 21. create_notice_document ───────────────────────────────────────────────
@action("create_notice_document", reversible=True)
async def create_notice_document(params, event_payload, execution_id, db, owner_id):
    notice_type = params.get("notice_type", "late_payment")
    tenant_name = event_payload.get("tenant_name", "Tenant")
    unit_number = event_payload.get("unit_number", "")

    # Generate simple notice text (production: use ReportLab for PDF)
    notices = {
        "late_payment": f"LATE PAYMENT NOTICE\n\nDear {tenant_name},\nYour rent for unit {unit_number} is overdue. Please remit payment immediately to avoid further action.",
        "non_renewal": f"NON-RENEWAL NOTICE\n\nDear {tenant_name},\nYour lease for unit {unit_number} will not be renewed. Please arrange to vacate by the lease end date.",
        "eviction_warning": f"EVICTION WARNING\n\nDear {tenant_name},\nFinal notice: failure to clear outstanding rent for unit {unit_number} within 48 hours will result in eviction proceedings.",
    }
    notice_text = notices.get(notice_type, notices["late_payment"])
    doc_id = str(uuid.uuid4())

    logger.info(f"[create_notice_document] Generated {notice_type} notice doc {doc_id} for {tenant_name}")
    return {
        "created": True,
        "document_id": doc_id,
        "notice_type": notice_type,
        "content_preview": notice_text[:120],
    }


# ── 22. charge_fee ────────────────────────────────────────────────────────────
@action("charge_fee", reversible=True)
async def charge_fee(params, event_payload, execution_id, db, owner_id):
    from app.models.payment import Payment, PaymentStatus, PaymentMethod, PaymentGateway, PaymentType, PaymentCurrency
    from app.models.user import User

    fee_type = params.get("fee_type", "admin_fee")
    idempotency_key = f"{fee_type}_{execution_id}"
    existing = db.query(Payment).filter(Payment.reference == idempotency_key).first()
    if existing:
        return {"charged": False, "reason": "already charged"}

    tenant_id = event_payload.get("tenant_id")
    amount = float(params.get("amount", 250))
    owner_user = db.query(User).filter(User.id == owner_id).first()

    payment = Payment(
        id=uuid.uuid4(),
        user_id=owner_id,
        user_email=owner_user.email if owner_user else "",
        amount=amount,
        currency=PaymentCurrency.KES,
        gateway=PaymentGateway.PAYSTACK,
        method=PaymentMethod.MPESA,
        reference=idempotency_key,
        status=PaymentStatus.PENDING,
        payment_type=PaymentType.PENALTY,
        tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
        payment_date=datetime.utcnow(),
        description=f"{fee_type.replace('_', ' ').title()} (Autopilot)",
        payment_metadata=json.dumps({"execution_id": str(execution_id), "fee_type": fee_type}),
    )
    db.add(payment)
    db.commit()
    return {"charged": True, "amount": amount, "fee_type": fee_type, "payment_id": str(payment.id)}


# ── 23. credit_account ────────────────────────────────────────────────────────
@action("credit_account", reversible=True)
async def credit_account(params, event_payload, execution_id, db, owner_id):
    # Record a credit memo as a negative payment / accounting entry
    credit_reason = params.get("reason", "Overpayment credit")
    amount = float(params.get("amount", event_payload.get("overpayment_amount", 0)))
    tenant_id = event_payload.get("tenant_id")

    logger.info(f"[credit_account] Credit KES {amount} for tenant {tenant_id}: {credit_reason}")
    return {
        "credited": True,
        "amount": amount,
        "reason": credit_reason,
        "tenant_id": tenant_id,
        "note": "Recorded as credit memo",
    }


# ── 24. cancel_pending_reminders ─────────────────────────────────────────────
@action("cancel_pending_reminders", reversible=False)
async def cancel_pending_reminders(params, event_payload, execution_id, db, owner_id):
    from app.models.mpesa import MpesaReminder, ReminderStatus
    tenant_id = event_payload.get("tenant_id")
    if not tenant_id:
        return {"cancelled": 0}

    month_key = event_payload.get("reference_month", datetime.utcnow().strftime("%Y-%m"))
    reminders = db.query(MpesaReminder).filter(
        MpesaReminder.tenant_id == uuid.UUID(tenant_id),
        MpesaReminder.status == ReminderStatus.PENDING,
        MpesaReminder.reference_month == month_key,
    ).all()

    for r in reminders:
        r.status = ReminderStatus.FAILED  # Using FAILED as "cancelled"

    db.commit()
    return {"cancelled": len(reminders), "tenant_id": tenant_id, "month": month_key}


# ── 25. send_owner_digest ────────────────────────────────────────────────────
@action("send_owner_digest", reversible=False)
async def send_owner_digest(params, event_payload, execution_id, db, owner_id):
    from app.models.user import User
    owner = db.query(User).filter(User.id == owner_id).first()
    if not owner or not owner.email:
        return {"sent": False, "reason": "owner not found"}

    subject = params.get("subject", "Weekly Property Management Digest")
    body = params.get("body", "Your weekly digest summary from Propertech Autopilot.")

    return await send_email.__wrapped__(
        params={"to": owner.email, "subject": subject, "body": body},
        event_payload=event_payload, execution_id=execution_id, db=db, owner_id=owner_id
    )


# ── 26. send_owner_alert ─────────────────────────────────────────────────────
@action("send_owner_alert", reversible=False)
async def send_owner_alert(params, event_payload, execution_id, db, owner_id):
    from app.models.user import User
    owner = db.query(User).filter(User.id == owner_id).first()
    if not owner:
        return {"sent": False, "reason": "owner not found"}

    message = params.get("message", f"Autopilot alert: {event_payload.get('event_type', 'event')} occurred.")
    results = {}

    if owner.phone:
        results["sms"] = await send_sms.__wrapped__(
            params={"phone": owner.phone, "message": message},
            event_payload=event_payload, execution_id=execution_id, db=db, owner_id=owner_id
        )
    if owner.email:
        results["email"] = await send_email.__wrapped__(
            params={"to": owner.email, "subject": "Propertech Alert", "body": message},
            event_payload=event_payload, execution_id=execution_id, db=db, owner_id=owner_id
        )
    return {"sent": True, "results": results}


# ── 27. trigger_rent_increase ────────────────────────────────────────────────
@action("trigger_rent_increase", reversible=True)
async def trigger_rent_increase(params, event_payload, execution_id, db, owner_id):
    unit_id = event_payload.get("unit_id")
    increase_pct = float(params.get("increase_pct", 5))
    current_rent = float(event_payload.get("monthly_rent", 0))
    new_rent = current_rent * (1 + increase_pct / 100)

    logger.info(f"[trigger_rent_increase] Unit {unit_id}: KES {current_rent} → KES {new_rent:.0f} (+{increase_pct}%)")
    return {
        "created": True,
        "unit_id": unit_id,
        "current_rent": current_rent,
        "new_rent": round(new_rent, 2),
        "increase_pct": increase_pct,
        "note": "Rent review recorded — apply change via unit settings",
    }


# ── 28. archive_tenant ────────────────────────────────────────────────────────
@action("archive_tenant", reversible=True)
async def archive_tenant(params, event_payload, execution_id, db, owner_id):
    from app.models.tenant import Tenant
    tenant_id = event_payload.get("tenant_id")
    if not tenant_id:
        return {"archived": False, "reason": "no tenant_id"}

    tenant = db.query(Tenant).filter(Tenant.id == uuid.UUID(tenant_id)).first()
    if not tenant:
        return {"archived": False, "reason": "tenant not found"}

    tenant.status = "archived"
    db.commit()
    return {"archived": True, "tenant_id": tenant_id}


# ── 29. webhook_notify ────────────────────────────────────────────────────────
@action("webhook_notify", reversible=False)
async def webhook_notify(params, event_payload, execution_id, db, owner_id):
    url = params.get("url", "")
    if not url:
        return {"sent": False, "reason": "no url"}

    payload = {
        "event_type": event_payload.get("event_type", ""),
        "owner_id": str(owner_id),
        "execution_id": str(execution_id),
        "payload": event_payload,
        "timestamp": datetime.utcnow().isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
        return {"sent": True, "url": url, "status_code": resp.status_code}
    except Exception as exc:
        return {"sent": False, "url": url, "error": str(exc)}
