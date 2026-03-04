"""
Seed System Templates — idempotent function called at startup.
Creates 11 built-in automation templates if they don't already exist.
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# ── Helper builders ───────────────────────────────────────────────────────────

def _step(action_type: str, params: Dict[str, Any] = None, stop_on_failure: bool = False) -> Dict:
    return {"action_type": action_type, "params": params or {}, "stop_on_failure": stop_on_failure}


SYSTEM_TEMPLATES: List[Dict] = [

    # ── 1. Payment received ───────────────────────────────────────────────────
    {
        "name": "Payment Received — Full Processing",
        "category": "payments",
        "description": "When M-Pesa payment arrives: create record, send receipt, cancel reminders, update unit status. Alerts owner if underpaid.",
        "trigger_event": "payment_received",
        "default_conditions": [],
        "default_action_chain": [
            _step("create_payment_record"),
            _step("generate_receipt"),
            _step("cancel_pending_reminders"),
            _step("update_unit_status", {"status": "occupied"}),
            _step("credit_account", {"reason": "Overpayment credit"}),
            _step("reverse_late_fee"),
            _step("send_sms", {
                "phone": "{{tenant_phone}}",
                "message": "Dear {{tenant_name}}, your payment of KES {{amount}} has been received. Receipt: {{mpesa_receipt}}. Thank you!"
            }),
            _step("send_owner_alert", {"message": "Payment of KES {{amount}} received from {{tenant_name}} ({{unit_number}})."}),
        ],
    },

    # ── 2. Payment overdue 3 days ─────────────────────────────────────────────
    {
        "name": "Payment Overdue — Day 3",
        "category": "payments",
        "description": "After 3 days overdue: mark unit overdue, apply late fee, create notice document, SMS tenant, alert owner.",
        "trigger_event": "payment_overdue_3d",
        "default_conditions": [],
        "default_action_chain": [
            _step("mark_payment_overdue"),
            _step("apply_late_fee", {"amount": 500}),
            _step("create_notice_document", {"notice_type": "late_payment"}),
            _step("send_sms", {
                "phone": "{{tenant_phone}}",
                "message": "Dear {{tenant_name}}, your rent for unit {{unit_number}} is 3 days overdue. A late fee has been applied. Please pay immediately."
            }),
            _step("send_owner_alert", {"message": "Tenant {{tenant_name}} ({{unit_number}}) is 3 days overdue on rent."}),
        ],
    },

    # ── 3. Payment overdue 7 days ─────────────────────────────────────────────
    {
        "name": "Payment Overdue — Day 7",
        "category": "payments",
        "description": "After 7 days: update tenant status to overdue_warning, escalate any maintenance, add admin fee, WhatsApp + owner alert.",
        "trigger_event": "payment_overdue_7d",
        "default_conditions": [],
        "default_action_chain": [
            _step("update_tenant_status", {"status": "overdue_warning"}),
            _step("escalate_maintenance"),
            _step("charge_fee", {"fee_type": "admin_fee", "amount": 250}),
            _step("send_whatsapp", {
                "phone": "{{tenant_phone}}",
                "message": "Dear {{tenant_name}}, your rent for unit {{unit_number}} is now 7 days overdue. KES {{monthly_rent}} + fees are due. Please pay immediately to avoid eviction proceedings."
            }),
            _step("send_owner_alert", {"message": "URGENT: Tenant {{tenant_name}} ({{unit_number}}) is 7 days overdue. Escalated."}),
        ],
    },

    # ── 4. Payment overdue 14 days ────────────────────────────────────────────
    {
        "name": "Payment Overdue — Day 14 (Requires Approval)",
        "category": "payments",
        "description": "Final notice at 14 days: eviction warning document, update tenant status. Requires owner approval before sending.",
        "trigger_event": "payment_overdue_14d",
        "default_conditions": [],
        "default_action_chain": [
            _step("create_notice_document", {"notice_type": "eviction_warning"}),
            _step("update_tenant_status", {"status": "eviction_warning"}),
            _step("send_sms", {
                "phone": "{{tenant_phone}}",
                "message": "FINAL NOTICE: Rent for unit {{unit_number}} is 14 days overdue. Eviction proceedings will commence in 48 hours if payment is not received."
            }),
            _step("send_owner_alert", {"message": "ACTION REQUIRED: Eviction warning issued to {{tenant_name}} ({{unit_number}}). Rent 14 days overdue."}),
        ],
    },

    # ── 5. Lease expiring 60 days ─────────────────────────────────────────────
    {
        "name": "Lease Expiring — 60 Days Notice",
        "category": "leases",
        "description": "Generate renewal draft and send renewal notice 60 days before lease end.",
        "trigger_event": "lease_expiring_60d",
        "default_conditions": [],
        "default_action_chain": [
            _step("generate_lease_renewal"),
            _step("send_lease_renewal_notice"),
        ],
    },

    # ── 6. Lease expiring 7 days ──────────────────────────────────────────────
    {
        "name": "Lease Expiring — 7 Days (Non-Renewal Notice)",
        "category": "leases",
        "description": "Create non-renewal notice document and send move-out notice 7 days before lease end.",
        "trigger_event": "lease_expiring_7d",
        "default_conditions": [],
        "default_action_chain": [
            _step("create_notice_document", {"notice_type": "non_renewal"}),
            _step("send_move_out_notice"),
        ],
    },

    # ── 7. Lease expired ──────────────────────────────────────────────────────
    {
        "name": "Lease Expired — Mark & Vacate",
        "category": "leases",
        "description": "Mark lease as expired (automatically fires unit_vacated event).",
        "trigger_event": "lease_expired",
        "default_conditions": [],
        "default_action_chain": [
            _step("mark_lease_expired"),
        ],
    },

    # ── 8. Unit vacated ───────────────────────────────────────────────────────
    {
        "name": "Unit Vacated — Full Offboarding",
        "category": "vacancy",
        "description": "When unit becomes vacant: update status, create listing, schedule move-out inspection, send notice. Archives tenant after 2 days.",
        "trigger_event": "unit_vacated",
        "default_conditions": [],
        "default_action_chain": [
            _step("update_unit_status", {"status": "vacant"}),
            _step("create_vacancy_listing"),
            _step("schedule_inspection", {"type": "move_out", "days_offset": 1}),
            _step("send_move_out_notice"),
            _step("archive_tenant"),
        ],
    },

    # ── 9. Unit vacant 7 days ─────────────────────────────────────────────────
    {
        "name": "Unit Vacant for 7 Days — Boost & Review",
        "category": "vacancy",
        "description": "After 7 days vacant: post to listing sites and trigger rent increase review.",
        "trigger_event": "unit_vacant_7d",
        "default_conditions": [],
        "default_action_chain": [
            _step("post_to_listing_sites", {"platforms": ["facebook", "whatsapp", "twitter"]}),
            _step("trigger_rent_increase", {"increase_pct": 0}),  # 0% = no change, just a review
        ],
    },

    # ── 10. Maintenance request created ───────────────────────────────────────
    {
        "name": "Maintenance Request — Auto-Process",
        "category": "maintenance",
        "description": "On new maintenance request: create tracking task. Schedule structural inspection automatically.",
        "trigger_event": "maintenance_request_created",
        "default_conditions": [],
        "default_action_chain": [
            _step("create_maintenance_task", {"title": "Follow-up: {{title}}", "priority": "medium"}),
            _step("schedule_inspection", {"type": "routine", "days_offset": 2}),
        ],
    },

    # ── 11. Tenant onboarded ──────────────────────────────────────────────────
    {
        "name": "Tenant Onboarded — Welcome Package",
        "category": "onboarding",
        "description": "On new tenant move-in: generate deposit receipt, schedule move-in inspection, create welcome walkthrough task.",
        "trigger_event": "tenant_onboarded",
        "default_conditions": [],
        "default_action_chain": [
            _step("generate_receipt"),
            _step("schedule_inspection", {"type": "move_in", "days_offset": 0}),
            _step("create_maintenance_task", {
                "title": "Welcome walkthrough for {{tenant_name}}",
                "description": "Walk new tenant through property rules, meter readings, emergency contacts.",
                "priority": "low",
            }),
            _step("send_sms", {
                "phone": "{{tenant_phone}}",
                "message": "Welcome to your new home, {{tenant_name}}! We're delighted to have you. Please contact us anytime via the Propertech portal."
            }),
        ],
    },
]


def seed_system_templates(db) -> None:
    """
    Idempotent seed function.
    Inserts system templates that don't already exist (matched by name).
    Safe to call on every startup.
    """
    from app.models.automation import AutomationTemplate

    try:
        existing_names = {
            r[0] for r in db.query(AutomationTemplate.name)
            .filter(AutomationTemplate.is_system_template == True)
            .all()
        }

        created = 0
        for tmpl_data in SYSTEM_TEMPLATES:
            if tmpl_data["name"] in existing_names:
                continue

            tmpl = AutomationTemplate(
                id=uuid.uuid4(),
                name=tmpl_data["name"],
                category=tmpl_data["category"],
                description=tmpl_data.get("description"),
                trigger_event=tmpl_data["trigger_event"],
                default_conditions=tmpl_data.get("default_conditions", []),
                default_action_chain=tmpl_data["default_action_chain"],
                is_system_template=True,
                created_by_owner_id=None,
            )
            db.add(tmpl)
            created += 1

        if created:
            db.commit()
            logger.info(f"[seed_templates] Created {created} new system templates")
        else:
            logger.info("[seed_templates] All system templates already exist — skipped")

    except Exception as exc:
        logger.error(f"[seed_templates] Failed: {exc}", exc_info=True)
        db.rollback()
