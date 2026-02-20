"""
Mpesa Payment Intelligence Engine — API Routes

Owner endpoints (JWT + premium required):
  GET  /api/mpesa/config                  get owner's Mpesa config
  POST /api/mpesa/config                  save/update credentials
  POST /api/mpesa/config/test             send test STK push
  POST /api/mpesa/register-urls           register C2B URLs with Safaricom

  GET  /api/mpesa/transactions            list transactions (filters)
  GET  /api/mpesa/transactions/{id}       transaction detail + audit log
  POST /api/mpesa/transactions/{id}/match manual match
  POST /api/mpesa/transactions/{id}/dispute flag disputed
  POST /api/mpesa/stk-push               initiate STK push to tenant
  POST /api/mpesa/import                 bulk import CSV statement

  GET  /api/mpesa/reminder-rules          get reminder config
  POST /api/mpesa/reminder-rules          save reminder config
  GET  /api/mpesa/reminders               list sent/scheduled reminders
  POST /api/mpesa/reminders/trigger       manual trigger

  GET  /api/mpesa/analytics/collection-rate
  GET  /api/mpesa/analytics/payment-timing
  GET  /api/mpesa/analytics/risk
  GET  /api/mpesa/dashboard              full dashboard summary

Public/webhook endpoints (no auth – verified by Safaricom IP):
  POST /api/mpesa/callbacks/stk           STK push result
  POST /api/mpesa/callbacks/c2b/validation
  POST /api/mpesa/callbacks/c2b/confirmation
"""
from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.mpesa import (
    MpesaConfig,
    MpesaReconciliationLog,
    MpesaReminder,
    MpesaReminderRule,
    MpesaTransaction,
    MpesaEnvironment,
    ReconciliationStatus,
    ReminderStatus,
    ReminderType,
    ShortcodeType,
)
from app.models.payment import Payment, PaymentStatus, Subscription, SubscriptionStatus
from app.models.property import Property, Unit
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.mpesa import (
    C2BConfirmationPayload,
    C2BValidationPayload,
    CsvImportResponse,
    DisputeRequest,
    ManualMatchRequest,
    MpesaConfigCreate,
    MpesaConfigOut,
    MpesaTestConnectionRequest,
    ReminderRuleOut,
    ReminderRuleUpdate,
    STKPushRequest,
    STKPushResponse,
    TriggerReminderRequest,
)
from app.services.mpesa_service import (
    get_access_token,
    handle_c2b_confirmation,
    handle_c2b_validation,
    handle_stk_callback,
    initiate_stk_push,
    normalize_phone,
    parse_mpesa_csv,
    register_c2b_urls,
)
from app.services.reconciliation_service import ReconciliationService
from app.services.reminder_service import (
    cancel_reminders_for_tenant,
    schedule_overdue_reminders,
    send_reminder,
    trigger_manual_reminder,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Mpesa Intelligence"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _backend_url() -> str:
    """Resolve public backend URL for callback registration."""
    url = getattr(settings, "BACKEND_URL", "") or getattr(settings, "BACKEND_API_URL", "")
    if not url or "localhost" in url:
        # On Railway the app is always reachable via the public URL
        url = "https://propertech-backend.up.railway.app"
    return url.rstrip("/")


def _enrich_transaction(txn: MpesaTransaction, db: Session) -> Dict[str, Any]:
    """Add denormalised fields for API response."""
    result = {
        "id": str(txn.id),
        "owner_id": str(txn.owner_id),
        "mpesa_receipt_number": txn.mpesa_receipt_number,
        "transaction_type": txn.transaction_type.value,
        "phone_number": txn.phone_number,
        "amount": txn.amount,
        "account_reference": txn.account_reference,
        "transaction_desc": txn.transaction_desc,
        "transaction_date": txn.transaction_date.isoformat() if txn.transaction_date else None,
        "reconciliation_status": txn.reconciliation_status.value,
        "reconciliation_confidence": txn.reconciliation_confidence,
        "matched_payment_id": str(txn.matched_payment_id) if txn.matched_payment_id else None,
        "property_id": str(txn.property_id) if txn.property_id else None,
        "unit_id": str(txn.unit_id) if txn.unit_id else None,
        "tenant_id": str(txn.tenant_id) if txn.tenant_id else None,
        "created_at": txn.created_at.isoformat(),
        "tenant_name": None,
        "unit_number": None,
        "property_name": None,
    }

    if txn.tenant_id:
        tenant = db.query(Tenant).filter(Tenant.id == txn.tenant_id).first()
        if tenant:
            result["tenant_name"] = tenant.full_name

    if txn.unit_id:
        unit = db.query(Unit).filter(Unit.id == txn.unit_id).first()
        if unit:
            result["unit_number"] = unit.unit_number

    if txn.property_id:
        prop = db.query(Property).filter(Property.id == txn.property_id).first()
        if prop:
            result["property_name"] = prop.name

    return result


def _enrich_reminder(r: MpesaReminder, db: Session) -> Dict[str, Any]:
    result = {
        "id": str(r.id),
        "owner_id": str(r.owner_id),
        "tenant_id": str(r.tenant_id),
        "unit_id": str(r.unit_id) if r.unit_id else None,
        "reminder_type": r.reminder_type.value,
        "channel": r.channel.value,
        "message": r.message,
        "status": r.status.value,
        "scheduled_for": r.scheduled_for.isoformat(),
        "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        "reference_month": r.reference_month,
        "created_at": r.created_at.isoformat(),
        "tenant_name": None,
        "tenant_phone": None,
    }
    tenant = db.query(Tenant).filter(Tenant.id == r.tenant_id).first()
    if tenant:
        result["tenant_name"] = tenant.full_name
        result["tenant_phone"] = tenant.phone
    return result


# ── Premium gate (same pattern as listings.py) ─────────────────────────────────

def require_premium(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Require Professional or Enterprise subscription. Admins bypass."""
    if current_user.role == UserRole.ADMIN:
        return current_user
    active_sub = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == current_user.id,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.plan.in_(["professional", "enterprise"]),
        )
        .first()
    )
    if not active_sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "premium_required",
                "message": (
                    "Mpesa Payment Intelligence is a premium feature. "
                    "Upgrade to Professional or Enterprise to unlock it."
                ),
                "upgrade_url": "/owner/subscription",
            },
        )
    return current_user


def _get_config_or_404(owner_id: uuid.UUID, db: Session) -> MpesaConfig:
    config = db.query(MpesaConfig).filter(MpesaConfig.owner_id == owner_id).first()
    if not config:
        raise HTTPException(
            status_code=404,
            detail="Mpesa configuration not found. Please set up your Mpesa credentials first.",
        )
    return config


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/config", response_model=MpesaConfigOut)
def get_config(
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Get owner's Mpesa configuration."""
    config = db.query(MpesaConfig).filter(MpesaConfig.owner_id == current_user.id).first()
    if not config:
        raise HTTPException(status_code=404, detail="No Mpesa configuration found")
    return config


@router.post("/config", response_model=MpesaConfigOut)
def save_config(
    payload: MpesaConfigCreate,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Create or update Mpesa credentials."""
    callback_base = _backend_url()
    config = db.query(MpesaConfig).filter(MpesaConfig.owner_id == current_user.id).first()

    if config:
        config.shortcode = payload.shortcode
        config.shortcode_type = ShortcodeType(payload.shortcode_type)
        config.consumer_key = payload.consumer_key
        config.consumer_secret = payload.consumer_secret
        config.passkey = payload.passkey
        config.account_reference_format = payload.account_reference_format or "UNIT-{unit_number}"
        config.environment = MpesaEnvironment(payload.environment or "sandbox")
        config.callback_url = callback_base
        config.updated_at = datetime.utcnow()
    else:
        config = MpesaConfig(
            owner_id=current_user.id,
            shortcode=payload.shortcode,
            shortcode_type=ShortcodeType(payload.shortcode_type),
            consumer_key=payload.consumer_key,
            consumer_secret=payload.consumer_secret,
            passkey=payload.passkey,
            account_reference_format=payload.account_reference_format or "UNIT-{unit_number}",
            environment=MpesaEnvironment(payload.environment or "sandbox"),
            callback_url=callback_base,
            is_active=True,
        )
        db.add(config)

    db.commit()
    db.refresh(config)
    logger.info(f"[mpesa] Config saved for owner {current_user.id} shortcode={payload.shortcode}")
    return config


@router.post("/config/test")
def test_connection(
    payload: MpesaTestConnectionRequest,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Send a test STK push to owner's own phone to verify credentials."""
    config = _get_config_or_404(current_user.id, db)

    if not config.passkey:
        raise HTTPException(status_code=400, detail="Passkey is required for STK Push. Add it to your Mpesa config.")

    callback_base = _backend_url()
    stk_callback_url = f"{callback_base}/api/mpesa/callbacks/stk"

    try:
        result = initiate_stk_push(
            phone=payload.phone,
            amount=1,  # KES 1 test charge
            account_ref="TEST",
            description="PROPERTECH Test",
            shortcode=config.shortcode,
            passkey=config.passkey,
            consumer_key=config.consumer_key,
            consumer_secret=config.consumer_secret,
            environment=config.environment.value,
            callback_url=stk_callback_url,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if result.get("ResponseCode") == "0":
        return {
            "success": True,
            "message": "STK Push sent to your phone. Check your Mpesa prompt.",
            "checkout_request_id": result.get("CheckoutRequestID"),
        }
    else:
        return {
            "success": False,
            "message": result.get("ResponseDescription", "STK Push failed"),
            "raw": result,
        }


@router.post("/register-urls")
def register_callback_urls(
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Register C2B confirmation and validation URLs with Safaricom."""
    config = _get_config_or_404(current_user.id, db)
    callback_base = _backend_url()

    confirmation_url = f"{callback_base}/api/mpesa/callbacks/c2b/confirmation"
    validation_url   = f"{callback_base}/api/mpesa/callbacks/c2b/validation"

    try:
        result = register_c2b_urls(
            shortcode=config.shortcode,
            consumer_key=config.consumer_key,
            consumer_secret=config.consumer_secret,
            environment=config.environment.value,
            confirmation_url=confirmation_url,
            validation_url=validation_url,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {
        "success": True,
        "confirmation_url": confirmation_url,
        "validation_url": validation_url,
        "safaricom_response": result,
    }


# ══════════════════════════════════════════════════════════════════════════════
# TRANSACTIONS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/transactions")
def list_transactions(
    reconciliation_status: Optional[str] = Query(None),
    property_id: Optional[uuid.UUID] = Query(None),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """List all transactions for the owner with optional filters."""
    q = db.query(MpesaTransaction).filter(MpesaTransaction.owner_id == current_user.id)

    if reconciliation_status:
        try:
            q = q.filter(MpesaTransaction.reconciliation_status == ReconciliationStatus(reconciliation_status))
        except ValueError:
            pass

    if property_id:
        q = q.filter(MpesaTransaction.property_id == property_id)

    if date_from:
        try:
            q = q.filter(MpesaTransaction.transaction_date >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass

    if date_to:
        try:
            q = q.filter(MpesaTransaction.transaction_date <= datetime.strptime(date_to, "%Y-%m-%d"))
        except ValueError:
            pass

    total = q.count()
    txns = q.order_by(MpesaTransaction.transaction_date.desc()).offset(skip).limit(limit).all()

    unmatched_count = (
        db.query(MpesaTransaction)
        .filter(
            MpesaTransaction.owner_id == current_user.id,
            MpesaTransaction.reconciliation_status == ReconciliationStatus.UNMATCHED,
        )
        .count()
    )
    matched_count = (
        db.query(MpesaTransaction)
        .filter(
            MpesaTransaction.owner_id == current_user.id,
            MpesaTransaction.reconciliation_status == ReconciliationStatus.MATCHED,
        )
        .count()
    )

    return {
        "transactions": [_enrich_transaction(t, db) for t in txns],
        "total": total,
        "unmatched_count": unmatched_count,
        "matched_count": matched_count,
    }


@router.get("/transactions/{transaction_id}")
def get_transaction(
    transaction_id: uuid.UUID,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Get transaction detail with full reconciliation audit log."""
    txn = (
        db.query(MpesaTransaction)
        .filter(
            MpesaTransaction.id == transaction_id,
            MpesaTransaction.owner_id == current_user.id,
        )
        .first()
    )
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    logs = (
        db.query(MpesaReconciliationLog)
        .filter(MpesaReconciliationLog.transaction_id == transaction_id)
        .order_by(MpesaReconciliationLog.created_at.asc())
        .all()
    )

    return {
        **_enrich_transaction(txn, db),
        "raw_payload": json.loads(txn.raw_payload) if txn.raw_payload else None,
        "reconciliation_logs": [
            {
                "id": str(log.id),
                "action": log.action.value,
                "confidence_score": log.confidence_score,
                "match_reason": log.match_reason,
                "performed_by": log.performed_by,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ],
    }


@router.post("/transactions/{transaction_id}/match")
def manual_match(
    transaction_id: uuid.UUID,
    payload: ManualMatchRequest,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Manually match a transaction to a tenant/unit."""
    svc = ReconciliationService(db)
    txn = svc.manual_match(
        transaction_id=transaction_id,
        tenant_id=payload.tenant_id,
        unit_id=payload.unit_id,
        property_id=payload.property_id,
        performed_by=str(current_user.id),
    )
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return {"success": True, "transaction": _enrich_transaction(txn, db)}


@router.post("/transactions/{transaction_id}/dispute")
def dispute_transaction(
    transaction_id: uuid.UUID,
    payload: DisputeRequest,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Flag a transaction as disputed."""
    svc = ReconciliationService(db)
    txn = svc.dispute(
        transaction_id=transaction_id,
        reason=payload.reason,
        performed_by=str(current_user.id),
    )
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return {"success": True, "transaction": _enrich_transaction(txn, db)}


@router.post("/stk-push", response_model=STKPushResponse)
def send_stk_push(
    payload: STKPushRequest,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Initiate an STK Push payment request to a specific tenant."""
    config = _get_config_or_404(current_user.id, db)

    if not config.passkey:
        raise HTTPException(status_code=400, detail="Passkey required for STK Push. Update your Mpesa config.")

    tenant = (
        db.query(Tenant)
        .filter(Tenant.id == payload.tenant_id, Tenant.user_id == current_user.id)
        .first()
    )
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if not tenant.phone:
        raise HTTPException(status_code=400, detail="Tenant has no phone number registered")

    amount = payload.amount or int(tenant.rent_amount or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid amount")

    unit = db.query(Unit).filter(Unit.id == tenant.unit_id).first() if tenant.unit_id else None
    unit_number = unit.unit_number if unit else ""
    account_ref = (config.account_reference_format or "UNIT-{unit_number}").format(
        unit_number=unit_number,
        tenant_name=tenant.full_name or "",
    )[:12]

    callback_base = _backend_url()
    stk_callback_url = f"{callback_base}/api/mpesa/callbacks/stk"

    try:
        result = initiate_stk_push(
            phone=tenant.phone,
            amount=amount,
            account_ref=account_ref,
            description=payload.description or "Rent Payment",
            shortcode=config.shortcode,
            passkey=config.passkey,
            consumer_key=config.consumer_key,
            consumer_secret=config.consumer_secret,
            environment=config.environment.value,
            callback_url=stk_callback_url,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    success = result.get("ResponseCode") == "0"
    return STKPushResponse(
        success=success,
        checkout_request_id=result.get("CheckoutRequestID"),
        merchant_request_id=result.get("MerchantRequestID"),
        message=result.get("CustomerMessage", result.get("ResponseDescription", "")),
    )


@router.post("/import", response_model=CsvImportResponse)
async def import_csv_statement(
    file: UploadFile = File(...),
    current_user: User = Depends(require_premium),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
):
    """
    Bulk import from Mpesa Business Statement CSV.
    Expected columns: Receipt No, Completion Time, Details,
    Transaction Amount, Other Party Info.
    """
    content = await file.read()
    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not decode file. Ensure it is UTF-8 CSV.")

    rows = parse_mpesa_csv(text)
    if not rows:
        raise HTTPException(status_code=400, detail="No valid rows found in CSV. Check column headers.")

    imported = 0
    skipped = 0
    errors = []

    for row in rows:
        try:
            existing = db.query(MpesaTransaction).filter(
                MpesaTransaction.mpesa_receipt_number == row["receipt"]
            ).first()
            if existing:
                skipped += 1
                continue

            from app.models.mpesa import TransactionType, ReconciliationStatus as RS
            txn = MpesaTransaction(
                owner_id=current_user.id,
                mpesa_receipt_number=row["receipt"],
                transaction_type=TransactionType.PAYBILL,
                phone_number=row["phone"] or "254000000000",
                amount=row["amount"],
                account_reference=row["details"][:255] if row["details"] else "",
                transaction_desc="CSV Import",
                transaction_date=row["txn_date"],
                reconciliation_status=RS.UNMATCHED,
                raw_payload=json.dumps(row.get("raw", {})),
            )
            db.add(txn)
            db.flush()

            # Queue reconciliation in background
            background_tasks.add_task(
                _bg_reconcile, txn.id, current_user.id
            )
            imported += 1
        except Exception as exc:
            errors.append(f"Row {row.get('receipt', '?')}: {exc}")

    db.commit()
    logger.info(f"[mpesa] CSV import: {imported} imported, {skipped} skipped for owner {current_user.id}")

    return CsvImportResponse(
        success=True,
        imported=imported,
        skipped_duplicates=skipped,
        errors=errors[:20],  # cap error list
    )


def _bg_reconcile(transaction_id: uuid.UUID, owner_id: uuid.UUID):
    """Background task: run reconciliation for a single transaction."""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        svc = ReconciliationService(db)
        svc.reconcile(transaction_id, owner_id)
    except Exception as exc:
        logger.error(f"[mpesa] Background reconciliation error: {exc}", exc_info=True)
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# REMINDER RULES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/reminder-rules")
def get_reminder_rules(
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Get owner's reminder configuration."""
    from app.services.reminder_service import _get_reminder_rule, _parse_json_field, DEFAULT_TEMPLATES
    rule = _get_reminder_rule(current_user.id, db)
    return {
        "id": str(rule.id),
        "owner_id": str(rule.owner_id),
        "is_active": rule.is_active,
        "pre_due_days": rule.pre_due_days,
        "channels": _parse_json_field(rule.channels, {t: "sms" for t in DEFAULT_TEMPLATES}),
        "escalation_rules": _parse_json_field(rule.escalation_rules, DEFAULT_TEMPLATES),
        "enabled_types": _parse_json_field(rule.enabled_types, {t: True for t in DEFAULT_TEMPLATES}),
        "created_at": rule.created_at.isoformat(),
        "updated_at": rule.updated_at.isoformat(),
    }


@router.post("/reminder-rules")
def save_reminder_rules(
    payload: ReminderRuleUpdate,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Save or update reminder rules."""
    from app.services.reminder_service import _get_reminder_rule, _parse_json_field, DEFAULT_TEMPLATES
    rule = _get_reminder_rule(current_user.id, db)

    if payload.is_active is not None:
        rule.is_active = payload.is_active
    if payload.pre_due_days is not None:
        rule.pre_due_days = payload.pre_due_days
    if payload.channels is not None:
        rule.channels = json.dumps(payload.channels)
    if payload.escalation_rules is not None:
        rule.escalation_rules = json.dumps(payload.escalation_rules)
    if payload.enabled_types is not None:
        rule.enabled_types = json.dumps(payload.enabled_types)

    rule.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(rule)

    return {
        "success": True,
        "id": str(rule.id),
        "is_active": rule.is_active,
        "pre_due_days": rule.pre_due_days,
        "channels": _parse_json_field(rule.channels, {}),
        "escalation_rules": _parse_json_field(rule.escalation_rules, DEFAULT_TEMPLATES),
        "enabled_types": _parse_json_field(rule.enabled_types, {}),
    }


# ══════════════════════════════════════════════════════════════════════════════
# REMINDERS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/reminders")
def list_reminders(
    reminder_status: Optional[str] = Query(None, alias="status"),
    tenant_id: Optional[uuid.UUID] = Query(None),
    month: Optional[str] = Query(None, description="YYYY-MM"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """List sent/scheduled reminders with filters."""
    q = db.query(MpesaReminder).filter(MpesaReminder.owner_id == current_user.id)

    if reminder_status:
        try:
            q = q.filter(MpesaReminder.status == ReminderStatus(reminder_status))
        except ValueError:
            pass
    if tenant_id:
        q = q.filter(MpesaReminder.tenant_id == tenant_id)
    if month:
        q = q.filter(MpesaReminder.reference_month == month)

    total = q.count()
    reminders = q.order_by(MpesaReminder.created_at.desc()).offset(skip).limit(limit).all()

    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    pending_count = (
        db.query(MpesaReminder)
        .filter(
            MpesaReminder.owner_id == current_user.id,
            MpesaReminder.status == ReminderStatus.PENDING,
        )
        .count()
    )
    sent_count = (
        db.query(MpesaReminder)
        .filter(
            MpesaReminder.owner_id == current_user.id,
            MpesaReminder.status == ReminderStatus.SENT,
            MpesaReminder.sent_at >= month_start,
        )
        .count()
    )
    failed_count = (
        db.query(MpesaReminder)
        .filter(
            MpesaReminder.owner_id == current_user.id,
            MpesaReminder.status == ReminderStatus.FAILED,
        )
        .count()
    )

    return {
        "reminders": [_enrich_reminder(r, db) for r in reminders],
        "total": total,
        "pending_count": pending_count,
        "sent_count": sent_count,
        "failed_count": failed_count,
    }


@router.post("/reminders/trigger")
def trigger_reminders(
    payload: TriggerReminderRequest,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Manually trigger reminders for a specific tenant or all overdue tenants."""
    results = trigger_manual_reminder(
        owner_id=current_user.id,
        tenant_id=payload.tenant_id,
        reminder_type=payload.reminder_type,
        channel=payload.channel,
        db=db,
    )
    return {
        "success": True,
        "triggered": len(results),
        "results": results,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/analytics/collection-rate")
def collection_rate(
    month: Optional[str] = Query(None, description="YYYY-MM, defaults to current month"),
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Return collection rate for the given month."""
    now = datetime.utcnow()
    if month:
        try:
            period_start = datetime.strptime(month, "%Y-%m")
        except ValueError:
            raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    else:
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month = now.strftime("%Y-%m")

    if period_start.month == 12:
        period_end = period_start.replace(year=period_start.year + 1, month=1)
    else:
        period_end = period_start.replace(month=period_start.month + 1)

    # Get active tenants
    tenants = (
        db.query(Tenant)
        .filter(Tenant.user_id == current_user.id, Tenant.status == "active")
        .all()
    )

    expected_count = len(tenants)
    total_expected_kes = sum(t.rent_amount or 0 for t in tenants)
    paid_ids = set()
    partial_ids = set()

    # Get Mpesa transactions matched this month
    matched_txns = (
        db.query(MpesaTransaction)
        .filter(
            MpesaTransaction.owner_id == current_user.id,
            MpesaTransaction.transaction_date >= period_start,
            MpesaTransaction.transaction_date < period_end,
            MpesaTransaction.reconciliation_status.in_([
                ReconciliationStatus.MATCHED,
                ReconciliationStatus.PARTIAL,
            ]),
        )
        .all()
    )

    total_collected = sum(t.amount for t in matched_txns)
    tenant_collections: Dict[str, float] = {}
    for t in matched_txns:
        if t.tenant_id:
            tid = str(t.tenant_id)
            tenant_collections[tid] = tenant_collections.get(tid, 0) + t.amount

    # Also check payments table
    payments = (
        db.query(Payment)
        .filter(
            Payment.user_id == current_user.id,
            Payment.payment_date >= period_start,
            Payment.payment_date < period_end,
            Payment.status == PaymentStatus.COMPLETED,
        )
        .all()
    )
    for p in payments:
        if p.tenant_id:
            tid = str(p.tenant_id)
            tenant_collections[tid] = tenant_collections.get(tid, 0) + p.amount

    for tenant in tenants:
        tid = str(tenant.id)
        collected = tenant_collections.get(tid, 0)
        expected = tenant.rent_amount or 0
        if collected >= expected * 0.95:  # 95% threshold = "paid"
            paid_ids.add(tid)
        elif collected > 0:
            partial_ids.add(tid)

    paid_count = len(paid_ids)
    partial_count = len(partial_ids)
    unpaid_count = expected_count - paid_count - partial_count
    collection_rate_pct = (paid_count / expected_count * 100) if expected_count > 0 else 0

    # Per-property breakdown
    properties = (
        db.query(Property)
        .filter(Property.user_id == current_user.id)
        .all()
    )
    by_property = []
    for prop in properties:
        prop_tenants = [t for t in tenants if str(t.property_id) == str(prop.id)]
        prop_paid = sum(1 for t in prop_tenants if str(t.id) in paid_ids)
        prop_expected = sum(t.rent_amount or 0 for t in prop_tenants)
        prop_collected = sum(tenant_collections.get(str(t.id), 0) for t in prop_tenants)
        by_property.append({
            "property_id": str(prop.id),
            "property_name": prop.name,
            "tenant_count": len(prop_tenants),
            "paid_count": prop_paid,
            "expected_kes": prop_expected,
            "collected_kes": prop_collected,
            "rate_pct": (prop_paid / len(prop_tenants) * 100) if prop_tenants else 0,
        })

    return {
        "month": month,
        "expected_count": expected_count,
        "paid_count": paid_count,
        "partial_count": partial_count,
        "unpaid_count": unpaid_count,
        "collection_rate_pct": round(collection_rate_pct, 1),
        "total_expected_kes": total_expected_kes,
        "total_collected_kes": total_collected,
        "by_property": by_property,
    }


@router.get("/analytics/payment-timing")
def payment_timing(
    month: Optional[str] = Query(None, description="YYYY-MM"),
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Distribution of when tenants pay during the month."""
    now = datetime.utcnow()
    if month:
        try:
            period_start = datetime.strptime(month, "%Y-%m")
        except ValueError:
            raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    else:
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month = now.strftime("%Y-%m")

    if period_start.month == 12:
        period_end = period_start.replace(year=period_start.year + 1, month=1)
    else:
        period_end = period_start.replace(month=period_start.month + 1)

    txns = (
        db.query(MpesaTransaction)
        .filter(
            MpesaTransaction.owner_id == current_user.id,
            MpesaTransaction.transaction_date >= period_start,
            MpesaTransaction.transaction_date < period_end,
            MpesaTransaction.reconciliation_status == ReconciliationStatus.MATCHED,
        )
        .all()
    )

    distribution: Dict[str, int] = {}
    for t in txns:
        day = str(t.transaction_date.day)
        distribution[day] = distribution.get(day, 0) + 1

    # Average day
    days = [t.transaction_date.day for t in txns]
    avg_day = sum(days) / len(days) if days else None
    on_time = sum(1 for d in days if d <= 10)
    on_time_pct = (on_time / len(days) * 100) if days else 0

    return {
        "month": month,
        "distribution": distribution,
        "avg_payment_day": round(avg_day, 1) if avg_day else None,
        "on_time_pct": round(on_time_pct, 1),
        "total_payments": len(txns),
    }


@router.get("/analytics/risk")
def payment_risk(
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Flag tenants with 2+ consecutive late months (payment risk analysis)."""
    now = datetime.utcnow()
    tenants = (
        db.query(Tenant)
        .filter(Tenant.user_id == current_user.id, Tenant.status == "active")
        .all()
    )

    flagged = []
    total_at_risk = 0.0

    for tenant in tenants:
        # Look back 3 months
        consecutive_late = 0
        for months_back in range(1, 4):
            if now.month - months_back <= 0:
                check_year = now.year - 1
                check_month = 12 + (now.month - months_back)
            else:
                check_year = now.year
                check_month = now.month - months_back

            period_start = now.replace(year=check_year, month=check_month, day=1,
                                       hour=0, minute=0, second=0, microsecond=0)
            if period_start.month == 12:
                period_end = period_start.replace(year=period_start.year + 1, month=1)
            else:
                period_end = period_start.replace(month=period_start.month + 1)

            # Check Mpesa matched transactions or payments
            paid_txn = db.query(MpesaTransaction).filter(
                MpesaTransaction.tenant_id == tenant.id,
                MpesaTransaction.transaction_date >= period_start,
                MpesaTransaction.transaction_date < period_end,
                MpesaTransaction.reconciliation_status == ReconciliationStatus.MATCHED,
            ).first()

            paid_payment = db.query(Payment).filter(
                Payment.tenant_id == tenant.id,
                Payment.payment_date >= period_start,
                Payment.payment_date < period_end,
                Payment.status == PaymentStatus.COMPLETED,
            ).first()

            if paid_txn or paid_payment:
                break  # paid this month — not consecutive
            consecutive_late += 1

        if consecutive_late >= 2:
            unit = db.query(Unit).filter(Unit.id == tenant.unit_id).first() if tenant.unit_id else None
            prop = db.query(Property).filter(Property.id == tenant.property_id).first() if tenant.property_id else None
            overdue = (tenant.rent_amount or 0) * consecutive_late

            risk_level = "critical" if consecutive_late >= 3 else "high" if consecutive_late == 2 else "medium"
            total_at_risk += overdue

            flagged.append({
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.full_name,
                "unit_number": unit.unit_number if unit else None,
                "property_name": prop.name if prop else None,
                "consecutive_late_months": consecutive_late,
                "total_overdue_kes": overdue,
                "last_payment_date": tenant.last_payment_date.isoformat() if tenant.last_payment_date else None,
                "risk_level": risk_level,
            })

    flagged.sort(key=lambda x: x["consecutive_late_months"], reverse=True)

    return {
        "flagged_tenants": flagged,
        "total_at_risk_kes": total_at_risk,
    }


@router.get("/dashboard")
def dashboard_summary(
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Full dashboard summary: collection rate, payment board, unmatched, activity feed."""
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month = now.strftime("%Y-%m")

    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)

    # Active tenants
    tenants = (
        db.query(Tenant)
        .filter(Tenant.user_id == current_user.id, Tenant.status == "active")
        .all()
    )

    # Matched transactions this month
    matched_txns = (
        db.query(MpesaTransaction)
        .filter(
            MpesaTransaction.owner_id == current_user.id,
            MpesaTransaction.transaction_date >= month_start,
            MpesaTransaction.reconciliation_status.in_([
                ReconciliationStatus.MATCHED,
                ReconciliationStatus.PARTIAL,
            ]),
        )
        .all()
    )
    total_collected = sum(t.amount for t in matched_txns)

    tenant_payments: Dict[str, float] = {}
    for t in matched_txns:
        if t.tenant_id:
            tid = str(t.tenant_id)
            tenant_payments[tid] = tenant_payments.get(tid, 0) + t.amount

    # Also from payments table
    payments_this_month = (
        db.query(Payment)
        .filter(
            Payment.user_id == current_user.id,
            Payment.payment_date >= month_start,
            Payment.status == PaymentStatus.COMPLETED,
        )
        .all()
    )
    for p in payments_this_month:
        if p.tenant_id:
            tid = str(p.tenant_id)
            tenant_payments[tid] = tenant_payments.get(tid, 0) + p.amount

    paid_count = 0
    board = []
    for tenant in tenants:
        tid = str(tenant.id)
        collected = tenant_payments.get(tid, 0)
        expected = tenant.rent_amount or 0
        unit = db.query(Unit).filter(Unit.id == tenant.unit_id).first() if tenant.unit_id else None
        prop = db.query(Property).filter(Property.id == tenant.property_id).first() if tenant.property_id else None

        if collected >= expected * 0.95:
            pstatus = "paid"
            paid_count += 1
            days_overdue = 0
        elif collected > 0:
            pstatus = "partial"
            days_overdue = max(0, (now - month_start).days)
        else:
            pstatus = "overdue" if now.day > 10 else "pending"
            days_overdue = max(0, now.day - 1)

        board.append({
            "tenant_id": tid,
            "tenant_name": tenant.full_name,
            "unit_number": unit.unit_number if unit else None,
            "property_name": prop.name if prop else None,
            "expected_rent": expected,
            "amount_collected": collected,
            "payment_status": pstatus,
            "days_overdue": days_overdue,
            "last_payment_date": tenant.last_payment_date.isoformat() if tenant.last_payment_date else None,
        })

    # Unmatched transactions
    unmatched_txns = (
        db.query(MpesaTransaction)
        .filter(
            MpesaTransaction.owner_id == current_user.id,
            MpesaTransaction.reconciliation_status == ReconciliationStatus.UNMATCHED,
        )
        .order_by(MpesaTransaction.transaction_date.desc())
        .limit(10)
        .all()
    )

    # Reminders sent this month
    reminders_sent = (
        db.query(MpesaReminder)
        .filter(
            MpesaReminder.owner_id == current_user.id,
            MpesaReminder.status == ReminderStatus.SENT,
            MpesaReminder.sent_at >= month_start,
        )
        .count()
    )

    # Recent activity feed (last 20 events)
    recent_txns = (
        db.query(MpesaTransaction)
        .filter(MpesaTransaction.owner_id == current_user.id)
        .order_by(MpesaTransaction.created_at.desc())
        .limit(10)
        .all()
    )
    recent_reminders = (
        db.query(MpesaReminder)
        .filter(
            MpesaReminder.owner_id == current_user.id,
            MpesaReminder.status == ReminderStatus.SENT,
        )
        .order_by(MpesaReminder.sent_at.desc())
        .limit(10)
        .all()
    )

    activity = []
    for t in recent_txns:
        tenant = db.query(Tenant).filter(Tenant.id == t.tenant_id).first() if t.tenant_id else None
        activity.append({
            "type": "payment",
            "timestamp": t.created_at.isoformat(),
            "title": f"KES {int(t.amount):,} received",
            "subtitle": f"{t.mpesa_receipt_number} · {tenant.full_name if tenant else 'Unmatched'}",
            "status": t.reconciliation_status.value,
        })
    for r in recent_reminders:
        tenant = db.query(Tenant).filter(Tenant.id == r.tenant_id).first() if r.tenant_id else None
        activity.append({
            "type": "reminder",
            "timestamp": r.sent_at.isoformat() if r.sent_at else r.created_at.isoformat(),
            "title": f"{r.reminder_type.value.replace('_', ' ').title()} reminder sent",
            "subtitle": f"via {r.channel.value} · {tenant.full_name if tenant else 'Unknown'}",
            "status": r.status.value,
        })

    activity.sort(key=lambda x: x["timestamp"], reverse=True)
    activity = activity[:20]

    collection_rate_pct = (paid_count / len(tenants) * 100) if tenants else 0

    return {
        "month": month,
        "collection_rate_pct": round(collection_rate_pct, 1),
        "total_collected_kes": total_collected,
        "unmatched_count": len(unmatched_txns),
        "reminders_sent_this_month": reminders_sent,
        "payment_status_board": sorted(board, key=lambda x: x["payment_status"]),
        "unmatched_transactions": [_enrich_transaction(t, db) for t in unmatched_txns],
        "recent_activity": activity,
    }


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC WEBHOOK ENDPOINTS (no auth – Safaricom calls these directly)
# ══════════════════════════════════════════════════════════════════════════════

def _find_owner_by_shortcode(shortcode: str, db: Session) -> Optional[uuid.UUID]:
    """Look up which owner's config matches this shortcode."""
    config = db.query(MpesaConfig).filter(MpesaConfig.shortcode == shortcode).first()
    return config.owner_id if config else None


@router.post("/callbacks/stk", include_in_schema=False)
async def stk_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Safaricom STK Push result callback.
    Must return 200 within 5 seconds — reconciliation runs in background.
    """
    try:
        payload = await request.json()
    except Exception:
        logger.warning("[mpesa] STK callback: could not parse JSON body")
        return {"ResultCode": 0, "ResultDesc": "Accepted"}

    logger.info(f"[mpesa] STK callback received: {json.dumps(payload)[:300]}")

    # Extract shortcode to identify owner
    try:
        body = payload.get("Body", {})
        stk = body.get("stkCallback", {})
        metadata_items = stk.get("CallbackMetadata", {}).get("Item", [])
        meta = {item["Name"]: item.get("Value") for item in metadata_items}
        # BusinessShortCode is not always in metadata; fallback to query all active configs
        shortcode = str(meta.get("BusinessShortCode", ""))
    except Exception:
        shortcode = ""

    owner_id = _find_owner_by_shortcode(shortcode, db) if shortcode else None

    # If we can't find owner by shortcode, try the first active config (single-owner mode)
    if not owner_id:
        first_config = db.query(MpesaConfig).filter(MpesaConfig.is_active == True).first()
        owner_id = first_config.owner_id if first_config else None

    if not owner_id:
        logger.warning("[mpesa] STK callback: could not identify owner from shortcode")
        return {"ResultCode": 0, "ResultDesc": "Accepted"}

    receipt = handle_stk_callback(payload, owner_id, db)
    if receipt:
        txn = db.query(MpesaTransaction).filter(
            MpesaTransaction.mpesa_receipt_number == receipt
        ).first()
        if txn:
            background_tasks.add_task(_bg_reconcile, txn.id, owner_id)

    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.post("/callbacks/c2b/validation", include_in_schema=False)
async def c2b_validation(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Safaricom C2B Validation callback.
    Return {"ResultCode": 0} to accept the transaction.
    Must respond within 5 seconds.
    """
    try:
        payload = await request.json()
    except Exception:
        return {"ResultCode": 0, "ResultDesc": "Accepted"}

    logger.info(f"[mpesa] C2B validation: {json.dumps(payload)[:200]}")
    return handle_c2b_validation(payload)


@router.post("/callbacks/c2b/confirmation", include_in_schema=False)
async def c2b_confirmation(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Safaricom C2B Confirmation callback.
    Must return 200 within 5 seconds.
    """
    try:
        payload = await request.json()
    except Exception:
        return {"ResultCode": 0, "ResultDesc": "Accepted"}

    logger.info(f"[mpesa] C2B confirmation: {json.dumps(payload)[:200]}")

    shortcode = str(payload.get("BusinessShortCode", ""))
    owner_id = _find_owner_by_shortcode(shortcode, db) if shortcode else None

    if not owner_id:
        first_config = db.query(MpesaConfig).filter(MpesaConfig.is_active == True).first()
        owner_id = first_config.owner_id if first_config else None

    if not owner_id:
        logger.warning("[mpesa] C2B confirmation: could not identify owner")
        return {"ResultCode": 0, "ResultDesc": "Accepted"}

    receipt = handle_c2b_confirmation(payload, owner_id, db)
    if receipt:
        txn = db.query(MpesaTransaction).filter(
            MpesaTransaction.mpesa_receipt_number == receipt
        ).first()
        if txn:
            background_tasks.add_task(_bg_reconcile, txn.id, owner_id)

    return {"ResultCode": 0, "ResultDesc": "Accepted"}
