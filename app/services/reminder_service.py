"""
Mpesa Smart Reminder Engine

Responsibilities:
  • schedule_monthly_reminders — called 1st of each month for all active tenants
  • send_reminder            — dispatch via Africa's Talking SMS or WhatsApp fallback
  • cancel_reminders_for_tenant — call when payment is received
  • trigger_manual_reminder  — ad-hoc dispatch from owner dashboard

SMS: Africa's Talking (AT) API. Reads AT_API_KEY + AT_USERNAME from env.
     If keys are missing, logs message instead of failing.

WhatsApp fallback: generates a wa.me deep-link (no API key required).
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Africa's Talking SMS API ──────────────────────────────────────────────────
AT_API_KEY    = os.getenv("AT_API_KEY", "")
AT_USERNAME   = os.getenv("AT_USERNAME", "sandbox")
AT_SMS_URL    = "https://api.africastalking.com/version1/messaging"
AT_SENDER_ID  = os.getenv("AT_SENDER_ID", "")  # optional short-code sender


# ── Default message templates (owner-customisable via MpesaReminderRule) ──────
DEFAULT_TEMPLATES = {
    "pre_due": (
        "Hi {name}, your rent of KES {amount} for {unit} is due on {date}. "
        "Pay to Paybill {shortcode}, Account: {reference}. – {company}"
    ),
    "due_today": (
        "Hi {name}, your rent of KES {amount} for {unit} is due TODAY. "
        "Pay now to avoid late fees. Paybill: {shortcode}, Acc: {reference}. – {company}"
    ),
    "day_1": (
        "Hi {name}, your rent of KES {amount} for {unit} was due yesterday. "
        "Please pay today to avoid penalties. Paybill: {shortcode}. – {company}"
    ),
    "day_3": (
        "Hi {name}, your rent for {unit} is now 3 days overdue. "
        "Amount: KES {amount}. Please pay immediately. Paybill: {shortcode}. – {company}"
    ),
    "day_7": (
        "Hi {name}, your rent is 7 days overdue. A late fee of KES {late_fee} has been added. "
        "Total due: KES {total}. Paybill: {shortcode}, Acc: {reference}. – {company}"
    ),
    "day_14": (
        "URGENT: Hi {name}, your rent for {unit} is 14 days overdue. "
        "Total due: KES {total}. Please settle immediately or contact us. – {company}"
    ),
    "final_notice": (
        "FINAL NOTICE: Rent for {unit} is {days} days overdue. "
        "Legal proceedings may begin if payment is not received within 48 hours. "
        "Total due: KES {total}. – {company}"
    ),
}

# Reminder types that get scheduled automatically (in order)
OVERDUE_TYPES = ["day_1", "day_3", "day_7", "day_14", "final_notice"]


# ── AT SMS dispatch ───────────────────────────────────────────────────────────

def _send_sms_at(phone: str, message: str) -> bool:
    """
    Send SMS via Africa's Talking API.
    Returns True on success, False on failure.
    Falls back to logging if AT_API_KEY is not configured.
    """
    if not AT_API_KEY:
        logger.info(f"[AT SMS – no key] To {phone}: {message}")
        return True  # treat as sent in dev mode

    payload = {
        "username": AT_USERNAME,
        "to": phone,
        "message": message,
    }
    if AT_SENDER_ID:
        payload["from"] = AT_SENDER_ID

    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(
                AT_SMS_URL,
                data=payload,
                headers={
                    "apiKey": AT_API_KEY,
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            result = response.json()
            recipients = result.get("SMSMessageData", {}).get("Recipients", [])
            if recipients and recipients[0].get("status") == "Success":
                logger.info(f"[AT SMS] Sent to {phone}")
                return True
            else:
                logger.warning(f"[AT SMS] Send failed for {phone}: {result}")
                return False
    except Exception as exc:
        logger.error(f"[AT SMS] Exception sending to {phone}: {exc}")
        return False


def _whatsapp_url(phone: str, message: str) -> str:
    """Generate wa.me deep-link URL (no API required)."""
    import urllib.parse
    phone_clean = "".join(c for c in phone if c.isdigit())
    return f"https://wa.me/{phone_clean}?text={urllib.parse.quote(message)}"


# ── Core reminder functions ───────────────────────────────────────────────────

def _get_owner_config(owner_id: uuid.UUID, db):
    """Return MpesaConfig for owner or None."""
    from app.models.mpesa import MpesaConfig
    return db.query(MpesaConfig).filter(MpesaConfig.owner_id == owner_id).first()


def _get_reminder_rule(owner_id: uuid.UUID, db):
    """Return MpesaReminderRule for owner or create a default."""
    from app.models.mpesa import MpesaReminderRule
    rule = db.query(MpesaReminderRule).filter(MpesaReminderRule.owner_id == owner_id).first()
    if not rule:
        rule = MpesaReminderRule(
            owner_id=owner_id,
            is_active=True,
            pre_due_days=3,
            channels=json.dumps({t: "sms" for t in list(DEFAULT_TEMPLATES.keys())}),
            escalation_rules=json.dumps(DEFAULT_TEMPLATES),
            enabled_types=json.dumps({t: True for t in list(DEFAULT_TEMPLATES.keys())}),
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
    return rule


def _parse_json_field(value: str, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback


def _build_message(template: str, context: dict) -> str:
    """Substitute {placeholders} in template, ignore missing keys."""
    try:
        return template.format(**context)
    except KeyError:
        # Fallback: replace only the keys we have
        msg = template
        for k, v in context.items():
            msg = msg.replace(f"{{{k}}}", str(v))
        return msg


def schedule_monthly_reminders(owner_id: uuid.UUID, db, due_day: int = 1) -> int:
    """
    Schedule pre-due reminders for all active tenants of an owner.
    Should be called on the 1st of each month (via cron or manual trigger).
    Returns the count of reminders scheduled.
    """
    from app.models.mpesa import MpesaReminder, ReminderType, ReminderChannel, ReminderStatus
    from app.models.tenant import Tenant
    from app.models.property import Unit

    rule = _get_reminder_rule(owner_id, db)
    if not rule.is_active:
        logger.info(f"[reminders] Reminder rules disabled for owner {owner_id}")
        return 0

    config = _get_owner_config(owner_id, db)
    shortcode = config.shortcode if config else ""
    channels = _parse_json_field(rule.channels, {t: "sms" for t in DEFAULT_TEMPLATES})
    templates = _parse_json_field(rule.escalation_rules, DEFAULT_TEMPLATES)
    enabled = _parse_json_field(rule.enabled_types, {t: True for t in DEFAULT_TEMPLATES})

    now = datetime.utcnow()
    # Due date = due_day of current month
    due_date = now.replace(day=due_day, hour=8, minute=0, second=0, microsecond=0)
    month_key = now.strftime("%Y-%m")

    tenants = (
        db.query(Tenant)
        .filter(Tenant.user_id == owner_id, Tenant.status == "active")
        .all()
    )

    scheduled = 0
    for tenant in tenants:
        if not tenant.phone:
            continue

        unit = db.query(Unit).filter(Unit.id == tenant.unit_id).first() if tenant.unit_id else None
        unit_number = unit.unit_number if unit else "your unit"
        reference = f"UNIT-{unit_number}" if unit_number else tenant.full_name

        context = {
            "name": tenant.full_name.split()[0] if tenant.full_name else "Tenant",
            "amount": int(tenant.rent_amount or 0),
            "unit": unit_number,
            "date": due_date.strftime("%d %B %Y"),
            "shortcode": shortcode,
            "reference": reference,
            "company": "PropTech",
            "late_fee": int((tenant.rent_amount or 0) * 0.05),  # 5% default late fee
            "total": int((tenant.rent_amount or 0) * 1.05),
            "days": 0,
        }

        # PRE-DUE reminder
        if enabled.get("pre_due", True):
            pre_due_days = rule.pre_due_days or 3
            scheduled_for = due_date - timedelta(days=pre_due_days)
            if scheduled_for > now:  # only future reminders
                template = templates.get("pre_due", DEFAULT_TEMPLATES["pre_due"])
                channel = channels.get("pre_due", "sms")
                message = _build_message(template, context)

                # Avoid duplicate scheduling
                existing = db.query(MpesaReminder).filter(
                    MpesaReminder.tenant_id == tenant.id,
                    MpesaReminder.reminder_type == ReminderType.PRE_DUE,
                    MpesaReminder.reference_month == month_key,
                ).first()
                if not existing:
                    reminder = MpesaReminder(
                        owner_id=owner_id,
                        tenant_id=tenant.id,
                        unit_id=tenant.unit_id,
                        reminder_type=ReminderType.PRE_DUE,
                        channel=ReminderChannel(channel),
                        message=message,
                        status=ReminderStatus.PENDING,
                        scheduled_for=scheduled_for,
                        reference_month=month_key,
                    )
                    db.add(reminder)
                    scheduled += 1

        # DUE TODAY reminder
        if enabled.get("due_today", True):
            template = templates.get("due_today", DEFAULT_TEMPLATES["due_today"])
            channel = channels.get("due_today", "sms")
            message = _build_message(template, context)
            existing = db.query(MpesaReminder).filter(
                MpesaReminder.tenant_id == tenant.id,
                MpesaReminder.reminder_type == ReminderType.DUE_TODAY,
                MpesaReminder.reference_month == month_key,
            ).first()
            if not existing:
                reminder = MpesaReminder(
                    owner_id=owner_id,
                    tenant_id=tenant.id,
                    unit_id=tenant.unit_id,
                    reminder_type=ReminderType.DUE_TODAY,
                    channel=ReminderChannel(channel),
                    message=message,
                    status=ReminderStatus.PENDING,
                    scheduled_for=due_date.replace(hour=9),
                    reference_month=month_key,
                )
                db.add(reminder)
                scheduled += 1

    db.commit()
    logger.info(f"[reminders] Scheduled {scheduled} reminders for owner {owner_id} month {month_key}")
    return scheduled


def schedule_overdue_reminders(owner_id: uuid.UUID, db) -> int:
    """
    Called daily. Schedules overdue reminders for tenants who haven't paid.
    Checks which tenants are 1/3/7/14/30+ days past due and haven't received
    that specific reminder yet this month.
    """
    from app.models.mpesa import MpesaReminder, ReminderType, ReminderChannel, ReminderStatus
    from app.models.tenant import Tenant
    from app.models.property import Unit
    from app.models.payment import Payment, PaymentStatus

    rule = _get_reminder_rule(owner_id, db)
    if not rule.is_active:
        return 0

    config = _get_owner_config(owner_id, db)
    shortcode = config.shortcode if config else ""
    channels = _parse_json_field(rule.channels, {t: "sms" for t in DEFAULT_TEMPLATES})
    templates = _parse_json_field(rule.escalation_rules, DEFAULT_TEMPLATES)
    enabled = _parse_json_field(rule.enabled_types, {t: True for t in DEFAULT_TEMPLATES})

    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_key = now.strftime("%Y-%m")

    # day thresholds for overdue reminder types
    overdue_map = {
        "day_1": 1,
        "day_3": 3,
        "day_7": 7,
        "day_14": 14,
        "final_notice": 30,
    }
    rtype_map = {
        "day_1": ReminderType.DAY_1,
        "day_3": ReminderType.DAY_3,
        "day_7": ReminderType.DAY_7,
        "day_14": ReminderType.DAY_14,
        "final_notice": ReminderType.FINAL_NOTICE,
    }

    tenants = (
        db.query(Tenant)
        .filter(Tenant.user_id == owner_id, Tenant.status == "active")
        .all()
    )

    scheduled = 0
    for tenant in tenants:
        if not tenant.phone:
            continue

        # Check if tenant paid this month
        paid = db.query(Payment).filter(
            Payment.tenant_id == tenant.id,
            Payment.payment_date >= month_start,
            Payment.status == PaymentStatus.COMPLETED,
        ).first()
        if paid:
            continue  # Paid — no overdue reminders needed

        unit = db.query(Unit).filter(Unit.id == tenant.unit_id).first() if tenant.unit_id else None
        unit_number = unit.unit_number if unit else "your unit"
        reference = f"UNIT-{unit_number}" if unit_number else tenant.full_name
        days_overdue = (now - month_start).days

        context = {
            "name": tenant.full_name.split()[0] if tenant.full_name else "Tenant",
            "amount": int(tenant.rent_amount or 0),
            "unit": unit_number,
            "date": month_start.strftime("%d %B %Y"),
            "shortcode": shortcode,
            "reference": reference,
            "company": "PropTech",
            "late_fee": int((tenant.rent_amount or 0) * 0.05),
            "total": int((tenant.rent_amount or 0) * 1.05),
            "days": days_overdue,
        }

        for type_key, threshold_days in overdue_map.items():
            if not enabled.get(type_key, True):
                continue
            if days_overdue < threshold_days:
                continue

            rtype = rtype_map[type_key]
            # Only send once per type per month
            existing = db.query(MpesaReminder).filter(
                MpesaReminder.tenant_id == tenant.id,
                MpesaReminder.reminder_type == rtype,
                MpesaReminder.reference_month == month_key,
            ).first()
            if existing:
                continue

            template = templates.get(type_key, DEFAULT_TEMPLATES.get(type_key, ""))
            channel = channels.get(type_key, "sms")
            message = _build_message(template, context)

            reminder = MpesaReminder(
                owner_id=owner_id,
                tenant_id=tenant.id,
                unit_id=tenant.unit_id,
                reminder_type=rtype,
                channel=ReminderChannel(channel),
                message=message,
                status=ReminderStatus.PENDING,
                scheduled_for=now,
                reference_month=month_key,
            )
            db.add(reminder)
            scheduled += 1

    db.commit()
    logger.info(f"[reminders] Scheduled {scheduled} overdue reminders for owner {owner_id}")
    return scheduled


def send_reminder(reminder_id: uuid.UUID, db) -> bool:
    """
    Dispatch a single pending reminder via its configured channel.
    Updates status to SENT or FAILED.
    Returns True if sent successfully.
    """
    from app.models.mpesa import MpesaReminder, ReminderStatus, ReminderChannel
    from app.models.tenant import Tenant

    reminder = db.query(MpesaReminder).filter(MpesaReminder.id == reminder_id).first()
    if not reminder:
        logger.warning(f"[reminders] Reminder {reminder_id} not found")
        return False

    if reminder.status != ReminderStatus.PENDING:
        logger.info(f"[reminders] Reminder {reminder_id} already {reminder.status.value}")
        return False

    tenant = db.query(Tenant).filter(Tenant.id == reminder.tenant_id).first()
    if not tenant or not tenant.phone:
        reminder.status = ReminderStatus.FAILED
        db.commit()
        return False

    from app.services.mpesa_service import normalize_phone
    phone = normalize_phone(tenant.phone)
    success = False

    if reminder.channel == ReminderChannel.SMS:
        success = _send_sms_at(phone, reminder.message)
    elif reminder.channel == ReminderChannel.WHATSAPP:
        # WhatsApp wa.me link — log the link; in production owner sends manually
        # or triggers via WhatsApp Business API if configured
        wa_url = _whatsapp_url(phone, reminder.message)
        logger.info(f"[reminders] WhatsApp link for tenant {tenant.full_name}: {wa_url}")
        success = True  # treated as sent (link generated)
    else:
        logger.warning(f"[reminders] Unknown channel {reminder.channel}")

    reminder.status = ReminderStatus.SENT if success else ReminderStatus.FAILED
    reminder.sent_at = datetime.utcnow() if success else None
    db.commit()

    return success


def cancel_reminders_for_tenant(tenant_id: uuid.UUID, month: str, db) -> int:
    """
    Cancel all pending reminders for a tenant for a given month.
    Called when payment is reconciled.
    month format: "2025-01"
    """
    from app.models.mpesa import MpesaReminder, ReminderStatus

    reminders = db.query(MpesaReminder).filter(
        MpesaReminder.tenant_id == tenant_id,
        MpesaReminder.reference_month == month,
        MpesaReminder.status == ReminderStatus.PENDING,
    ).all()

    for r in reminders:
        r.status = ReminderStatus.FAILED  # "cancelled"

    db.commit()
    count = len(reminders)
    if count:
        logger.info(f"[reminders] Cancelled {count} reminders for tenant {tenant_id} month {month}")
    return count


def trigger_manual_reminder(
    owner_id: uuid.UUID,
    tenant_id: Optional[uuid.UUID],
    reminder_type: Optional[str],
    channel: Optional[str],
    db,
) -> List[dict]:
    """
    Manually trigger reminders.
    If tenant_id is None, fires for all overdue tenants.
    Returns list of results: {tenant_name, status, channel}.
    """
    from app.models.mpesa import MpesaReminder, ReminderType, ReminderChannel, ReminderStatus
    from app.models.tenant import Tenant
    from app.models.property import Unit
    from app.models.payment import Payment, PaymentStatus

    config = _get_owner_config(owner_id, db)
    shortcode = config.shortcode if config else ""
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_key = now.strftime("%Y-%m")
    days_overdue = (now - month_start).days

    rule = _get_reminder_rule(owner_id, db)
    templates = _parse_json_field(rule.escalation_rules, DEFAULT_TEMPLATES)

    # Determine which tenants to target
    if tenant_id:
        tenants = db.query(Tenant).filter(
            Tenant.id == tenant_id, Tenant.user_id == owner_id
        ).all()
    else:
        # All unpaid active tenants
        tenants = (
            db.query(Tenant)
            .filter(Tenant.user_id == owner_id, Tenant.status == "active")
            .all()
        )
        # Filter to only overdue (no payment this month)
        unpaid = []
        for t in tenants:
            paid = db.query(Payment).filter(
                Payment.tenant_id == t.id,
                Payment.payment_date >= month_start,
                Payment.status == PaymentStatus.COMPLETED,
            ).first()
            if not paid:
                unpaid.append(t)
        tenants = unpaid

    results = []
    for tenant in tenants:
        if not tenant.phone:
            continue

        unit = db.query(Unit).filter(Unit.id == tenant.unit_id).first() if tenant.unit_id else None
        unit_number = unit.unit_number if unit else "your unit"
        reference = f"UNIT-{unit_number}"

        context = {
            "name": tenant.full_name.split()[0] if tenant.full_name else "Tenant",
            "amount": int(tenant.rent_amount or 0),
            "unit": unit_number,
            "date": month_start.strftime("%d %B %Y"),
            "shortcode": shortcode,
            "reference": reference,
            "company": "PropTech",
            "late_fee": int((tenant.rent_amount or 0) * 0.05),
            "total": int((tenant.rent_amount or 0) * 1.05),
            "days": days_overdue,
        }

        # Determine type
        rtype_str = reminder_type or ("day_1" if days_overdue >= 1 else "due_today")
        try:
            rtype = ReminderType(rtype_str)
        except ValueError:
            rtype = ReminderType.DAY_1

        ch_str = channel or "sms"
        try:
            ch = ReminderChannel(ch_str)
        except ValueError:
            ch = ReminderChannel.SMS

        template = templates.get(rtype_str, DEFAULT_TEMPLATES.get(rtype_str, ""))
        message = _build_message(template, context)

        from app.services.mpesa_service import normalize_phone
        phone = normalize_phone(tenant.phone)

        # Create and immediately send
        reminder = MpesaReminder(
            owner_id=owner_id,
            tenant_id=tenant.id,
            unit_id=tenant.unit_id,
            reminder_type=rtype,
            channel=ch,
            message=message,
            status=ReminderStatus.PENDING,
            scheduled_for=now,
            reference_month=month_key,
        )
        db.add(reminder)
        db.flush()

        success = send_reminder(reminder.id, db)
        results.append({
            "tenant_name": tenant.full_name,
            "tenant_id": str(tenant.id),
            "channel": ch_str,
            "status": "sent" if success else "failed",
        })

    db.commit()
    return results
