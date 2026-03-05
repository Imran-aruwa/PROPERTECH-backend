"""
APScheduler — Scheduled jobs for the Autonomous Property Manager.

Jobs:
  07:30 — check_maintenance_schedules (creates VendorJobs for due schedules)
  08:00 — check_payment_overdue   (publishes payment_overdue_3d/7d/14d)
  08:15 — check_lease_expiry      (publishes lease_expiring_60d/30d/7d)
  08:30 — check_vacant_units      (publishes unit_vacant_7d / unit_vacant_30d)
  08:45 — check_renewal_campaigns (follow-up SMS for stale campaigns)
  09:00 — check_maintenance_overdue (publishes maintenance_overdue)
  09:00 — check_overdue_leads     (alerts owner for overdue leads)
  Mon 07:00 — weekly_owner_digest
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)
NAIROBI_TZ = pytz.timezone("Africa/Nairobi")

_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> Optional[AsyncIOScheduler]:
    return _scheduler


def create_scheduler() -> AsyncIOScheduler:
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone=NAIROBI_TZ)

    _scheduler.add_job(
        check_maintenance_schedules, "cron", hour=7, minute=30,
        id="check_maintenance_schedules", replace_existing=True
    )
    _scheduler.add_job(
        check_payment_overdue, "cron", hour=8, minute=0,
        id="check_payment_overdue", replace_existing=True
    )
    _scheduler.add_job(
        check_lease_expiry, "cron", hour=8, minute=15,
        id="check_lease_expiry", replace_existing=True
    )
    _scheduler.add_job(
        check_vacant_units, "cron", hour=8, minute=30,
        id="check_vacant_units", replace_existing=True
    )
    _scheduler.add_job(
        check_maintenance_overdue, "cron", hour=9, minute=0,
        id="check_maintenance_overdue", replace_existing=True
    )
    _scheduler.add_job(
        weekly_owner_digest, "cron", day_of_week="mon", hour=7, minute=0,
        id="weekly_owner_digest", replace_existing=True
    )
    _scheduler.add_job(
        check_overdue_leads, "cron", hour=9, minute=0,
        id="check_overdue_leads", replace_existing=True
    )
    _scheduler.add_job(
        check_renewal_campaigns, "cron", hour=8, minute=45,
        id="check_renewal_campaigns", replace_existing=True
    )

    logger.info("[scheduler] AsyncIOScheduler configured with 8 jobs (Africa/Nairobi)")
    return _scheduler


# ── Helper: get a fresh DB session ───────────────────────────────────────────

def _get_db():
    from app.database import SessionLocal
    return SessionLocal()


# ── Job 1: check_payment_overdue ─────────────────────────────────────────────

async def check_payment_overdue() -> None:
    """
    Find tenants with unpaid rent, compute days overdue,
    publish payment_overdue_3d / _7d / _14d events.
    Deduplicate against automation_executions within the same day.
    """
    from app.services.event_bus import event_bus, PropertyEvent
    from app.models.tenant import Tenant
    from app.models.automation import AutomationExecution

    db = _get_db()
    try:
        now = datetime.now(timezone.utc)
        today_str = now.strftime("%Y-%m")

        # Tenants with unpaid rent this month
        tenants = (
            db.query(Tenant)
            .filter(Tenant.status == "active")
            .all()
        )

        published = 0
        for tenant in tenants:
            if not tenant.rent_amount or not tenant.lease_start:
                continue

            last_paid = tenant.last_payment_date
            if last_paid and last_paid.strftime("%Y-%m") == today_str:
                continue  # Already paid this month

            # Compute days overdue from 1st of month
            first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            days_overdue = (now - first_of_month).days

            event_type = None
            if days_overdue >= 14:
                event_type = "payment_overdue_14d"
            elif days_overdue >= 7:
                event_type = "payment_overdue_7d"
            elif days_overdue >= 3:
                event_type = "payment_overdue_3d"

            if not event_type:
                continue

            # Deduplicate: skip if we already fired this event today
            already_fired = db.query(AutomationExecution).filter(
                AutomationExecution.owner_id == tenant.user_id,
                AutomationExecution.trigger_event == event_type,
                AutomationExecution.started_at >= now.replace(hour=0, minute=0, second=0),
                AutomationExecution.trigger_payload.cast(
                    db.bind.dialect.type_descriptor(db.bind.dialect.colspecs.get(type(None), type(None)))
                ) if False else True,  # Skip complex JSON check
            ).first()

            if already_fired:
                continue

            owner_id = str(tenant.user_id) if tenant.user_id else None
            if not owner_id:
                continue

            property_id = str(tenant.property_id) if tenant.property_id else None
            unit_id = str(tenant.unit_id) if tenant.unit_id else None

            payload = {
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.full_name or "",
                "tenant_email": tenant.email or "",
                "tenant_phone": tenant.phone or "",
                "unit_id": unit_id,
                "property_id": property_id,
                "monthly_rent": float(tenant.rent_amount or 0),
                "days_overdue": days_overdue,
                "event_type": event_type,
                "reference_month": today_str,
            }

            event_bus.publish(PropertyEvent(
                event_type=event_type,
                owner_id=owner_id,
                payload=payload,
                source="scheduler",
            ))
            published += 1

        logger.info(f"[scheduler] check_payment_overdue: published {published} events")
    except Exception as exc:
        logger.error(f"[scheduler] check_payment_overdue failed: {exc}", exc_info=True)
    finally:
        db.close()


# ── Job 2: check_lease_expiry ─────────────────────────────────────────────────

async def check_lease_expiry() -> None:
    """Publish lease_expiring_60d / _30d / _7d events."""
    from app.services.event_bus import event_bus, PropertyEvent
    from app.models.lease import Lease, LeaseStatus

    db = _get_db()
    try:
        now = datetime.now(timezone.utc)
        published = 0

        leases = (
            db.query(Lease)
            .filter(
                Lease.status == LeaseStatus.ACTIVE,
                Lease.end_date.isnot(None),
            )
            .all()
        )

        for lease in leases:
            end = lease.end_date
            if hasattr(end, "tzinfo") and end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)

            days_remaining = (end - now).days

            if days_remaining < 0:
                event_type = "lease_expired"
            elif days_remaining <= 7:
                event_type = "lease_expiring_7d"
            elif days_remaining <= 30:
                event_type = "lease_expiring_30d"
            elif days_remaining <= 60:
                event_type = "lease_expiring_60d"
            else:
                continue

            payload = {
                "lease_id": str(lease.id),
                "tenant_id": str(lease.tenant_id) if lease.tenant_id else None,
                "tenant_name": lease.tenant_name or "",
                "tenant_email": lease.tenant_email or "",
                "tenant_phone": lease.tenant_phone or "",
                "unit_id": str(lease.unit_id) if lease.unit_id else None,
                "property_id": str(lease.property_id) if lease.property_id else None,
                "days_remaining": days_remaining,
                "end_date": end.isoformat(),
                "monthly_rent": float(lease.rent_amount or 0),
                "event_type": event_type,
            }

            event_bus.publish(PropertyEvent(
                event_type=event_type,
                owner_id=str(lease.owner_id),
                payload=payload,
                source="scheduler",
            ))
            published += 1

        logger.info(f"[scheduler] check_lease_expiry: published {published} events")
    except Exception as exc:
        logger.error(f"[scheduler] check_lease_expiry failed: {exc}", exc_info=True)
    finally:
        db.close()


# ── Job 3: check_vacant_units ─────────────────────────────────────────────────

async def check_vacant_units() -> None:
    """Publish unit_vacant_7d / unit_vacant_30d events."""
    from app.services.event_bus import event_bus, PropertyEvent
    from app.models.property import Unit, Property

    db = _get_db()
    try:
        now = datetime.now(timezone.utc)
        published = 0

        units = (
            db.query(Unit)
            .filter(Unit.status == "vacant")
            .all()
        )

        for unit in units:
            prop = db.query(Property).filter(Property.id == unit.property_id).first() if unit.property_id else None
            if not prop:
                continue

            # Estimate vacancy duration from updated_at
            vacated_at = unit.updated_at or now
            if hasattr(vacated_at, "tzinfo") and vacated_at.tzinfo is None:
                vacated_at = vacated_at.replace(tzinfo=timezone.utc)

            days_vacant = (now - vacated_at).days

            if days_vacant >= 30:
                event_type = "unit_vacant_30d"
            elif days_vacant >= 7:
                event_type = "unit_vacant_7d"
            else:
                continue

            payload = {
                "unit_id": str(unit.id),
                "unit_number": unit.unit_number or "",
                "property_id": str(prop.id),
                "property_name": prop.name or "",
                "monthly_rent": float(unit.monthly_rent or 0),
                "days_vacant": days_vacant,
                "event_type": event_type,
            }

            event_bus.publish(PropertyEvent(
                event_type=event_type,
                owner_id=str(prop.user_id),
                payload=payload,
                source="scheduler",
            ))
            published += 1

        logger.info(f"[scheduler] check_vacant_units: published {published} events")
    except Exception as exc:
        logger.error(f"[scheduler] check_vacant_units failed: {exc}", exc_info=True)
    finally:
        db.close()


# ── Job 4: check_maintenance_overdue ─────────────────────────────────────────

async def check_maintenance_overdue() -> None:
    """Publish maintenance_overdue for open requests > 48 hours."""
    from app.services.event_bus import event_bus, PropertyEvent
    from app.models.maintenance import MaintenanceRequest, MaintenanceStatus
    from app.models.property import Property

    db = _get_db()
    try:
        now = datetime.now(timezone.utc)
        threshold = now - timedelta(hours=48)
        published = 0

        requests = (
            db.query(MaintenanceRequest)
            .filter(
                MaintenanceRequest.status.in_([
                    MaintenanceStatus.PENDING, MaintenanceStatus.IN_PROGRESS
                ]),
                MaintenanceRequest.created_at <= threshold,
            )
            .all()
        )

        for req in requests:
            prop = db.query(Property).filter(Property.id == req.property_id).first() if req.property_id else None
            if not prop:
                continue

            created = req.created_at
            if hasattr(created, "tzinfo") and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            hours_open = (now - created).total_seconds() / 3600

            payload = {
                "maintenance_request_id": str(req.id),
                "title": req.title or "",
                "priority": req.priority.value if req.priority else "medium",
                "unit_id": str(req.unit_id) if req.unit_id else None,
                "property_id": str(req.property_id) if req.property_id else None,
                "tenant_id": str(req.tenant_id) if req.tenant_id else None,
                "hours_open": round(hours_open, 1),
                "event_type": "maintenance_overdue",
            }

            event_bus.publish(PropertyEvent(
                event_type="maintenance_overdue",
                owner_id=str(prop.user_id),
                payload=payload,
                source="scheduler",
            ))
            published += 1

        logger.info(f"[scheduler] check_maintenance_overdue: published {published} events")
    except Exception as exc:
        logger.error(f"[scheduler] check_maintenance_overdue failed: {exc}", exc_info=True)
    finally:
        db.close()


# ── Job 5: weekly_owner_digest ────────────────────────────────────────────────

async def weekly_owner_digest() -> None:
    """Send a weekly summary digest to every owner who has autopilot enabled."""
    from app.services.event_bus import event_bus, PropertyEvent
    from app.models.automation import AutopilotSettings
    from app.models.user import User, UserRole

    db = _get_db()
    try:
        settings_list = (
            db.query(AutopilotSettings)
            .filter(AutopilotSettings.is_enabled == True)
            .all()
        )

        for s in settings_list:
            owner = db.query(User).filter(User.id == s.owner_id).first()
            if not owner:
                continue

            payload = {
                "owner_id": str(s.owner_id),
                "owner_name": f"{owner.first_name or ''} {owner.last_name or ''}".strip() or owner.email,
                "owner_email": owner.email or "",
                "digest_week": datetime.now(timezone.utc).strftime("%Y-W%W"),
                "event_type": "weekly_digest",
            }

            event_bus.publish(PropertyEvent(
                event_type="scheduled",
                owner_id=str(s.owner_id),
                payload=payload,
                source="weekly_scheduler",
            ))

        logger.info(f"[scheduler] weekly_owner_digest: queued for {len(settings_list)} owners")
    except Exception as exc:
        logger.error(f"[scheduler] weekly_owner_digest failed: {exc}", exc_info=True)
    finally:
        db.close()


# ── Job 6: check_maintenance_schedules ───────────────────────────────────────

async def check_maintenance_schedules() -> None:
    """
    07:30 EAT daily — find all active MaintenanceSchedules where next_due <= today.
    Delegates to VendorService.check_due_schedules() per owner.
    Idempotent: VendorService checks for existing active VendorJob.schedule_id.
    """
    from app.models.vendor_intelligence import MaintenanceSchedule
    from app.models.user import User, UserRole

    db = _get_db()
    try:
        today = datetime.now(timezone.utc).date()

        # Get distinct owners who have due schedules
        owner_ids = (
            db.query(MaintenanceSchedule.owner_id)
            .filter(
                MaintenanceSchedule.is_active == True,
                MaintenanceSchedule.next_due <= today,
            )
            .distinct()
            .all()
        )

        processed = 0
        for (owner_id,) in owner_ids:
            try:
                from app.services.vendor_service import VendorService
                svc = VendorService(db, owner_id)
                svc.check_due_schedules()
                processed += 1
            except Exception as owner_exc:
                logger.warning(
                    f"[scheduler] check_maintenance_schedules failed for owner {owner_id}: {owner_exc}"
                )

        logger.info(f"[scheduler] check_maintenance_schedules: processed {processed} owners")
    except Exception as exc:
        logger.error(f"[scheduler] check_maintenance_schedules failed: {exc}", exc_info=True)
    finally:
        db.close()


# ── Job 7: check_overdue_leads ────────────────────────────────────────────────

async def check_overdue_leads() -> None:
    """
    09:00 EAT daily — find all leads where follow_up_due_at < now
    and status not in (converted/lost/rejected).
    Alert owner by SMS for each overdue lead.
    """
    from app.models.vacancy_prevention import VacancyLead, VacancyPreventionSettings
    from app.models.user import User

    db = _get_db()
    try:
        now = datetime.now(timezone.utc)
        inactive = {"converted", "lost", "rejected"}

        overdue_leads = (
            db.query(VacancyLead)
            .filter(
                VacancyLead.follow_up_due_at < now,
                VacancyLead.status.notin_(list(inactive)),
            )
            .all()
        )

        # Group by owner
        by_owner: dict = {}
        for lead in overdue_leads:
            key = str(lead.owner_id)
            by_owner.setdefault(key, []).append(lead)

        alerted = 0
        for owner_id_str, leads in by_owner.items():
            try:
                owner_uuid = uuid.UUID(owner_id_str)
                owner = db.query(User).filter(User.id == owner_uuid).first()
                if not owner:
                    continue

                owner_phone = getattr(owner, "phone", None)
                if not owner_phone:
                    continue

                settings = (
                    db.query(VacancyPreventionSettings)
                    .filter(VacancyPreventionSettings.owner_id == owner_uuid)
                    .first()
                )
                if settings and not settings.is_enabled:
                    continue

                for lead in leads[:5]:  # cap at 5 alerts per owner per day
                    due = lead.follow_up_due_at
                    if due and hasattr(due, "tzinfo") and due.tzinfo is None:
                        due = due.replace(tzinfo=timezone.utc)
                    days_overdue = max(0, (now - due).days) if due else 0

                    msg = (
                        f"PROPERTECH: Lead {lead.lead_name} ({lead.lead_phone}) "
                        f"has not been followed up. "
                        f"{days_overdue} day(s) overdue. Log in to action."
                    )
                    from app.services.vacancy_prevention_service import _send_sms
                    _send_sms(owner_phone, msg)
                    alerted += 1

            except Exception as owner_exc:
                logger.warning(f"[scheduler] overdue lead alert failed for {owner_id_str}: {owner_exc}")

        logger.info(f"[scheduler] check_overdue_leads: sent {alerted} alerts")
    except Exception as exc:
        logger.error(f"[scheduler] check_overdue_leads failed: {exc}", exc_info=True)
    finally:
        db.close()


# ── Job 7: check_renewal_campaigns ───────────────────────────────────────────

async def check_renewal_campaigns() -> None:
    """
    08:45 EAT daily — find active campaigns with no response for > 7 days.
    Send follow-up SMS to tenant and increment follow_up_count.
    """
    from app.models.vacancy_prevention import RenewalCampaign
    from app.models.lease import Lease
    from app.models.property import Unit

    db = _get_db()
    try:
        now = datetime.now(timezone.utc)
        stale_cutoff = now - timedelta(days=7)

        campaigns = (
            db.query(RenewalCampaign)
            .filter(
                RenewalCampaign.campaign_status == "active",
                RenewalCampaign.tenant_response == None,  # noqa: E711
            )
            .all()
        )

        followed_up = 0
        for campaign in campaigns:
            last = campaign.last_follow_up_at
            if last:
                if hasattr(last, "tzinfo") and last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if last > stale_cutoff:
                    continue  # followed up recently — skip

            lease = (
                db.query(Lease).filter(Lease.id == campaign.lease_id).first()
                if campaign.lease_id else None
            )
            if not lease or not lease.tenant_phone:
                continue

            unit = (
                db.query(Unit).filter(Unit.id == campaign.unit_id).first()
                if campaign.unit_id else None
            )
            unit_label = f"Unit {unit.unit_number}" if unit else "your unit"
            tenant_name = lease.tenant_name or "Tenant"
            end_date = lease.end_date.strftime("%d %b %Y") if lease.end_date else "soon"
            rent = f"{float(campaign.current_rent or 0):,.0f}"

            msg = (
                f"Hi {tenant_name}, just a reminder — your lease for {unit_label} "
                f"expires on {end_date}. "
                f"Reply YES to renew at KES {rent}/month. PROPERTECH"
            )
            from app.services.vacancy_prevention_service import _send_sms
            _send_sms(lease.tenant_phone, msg)

            campaign.follow_up_count = (campaign.follow_up_count or 0) + 1
            campaign.last_follow_up_at = now
            followed_up += 1

        if followed_up:
            db.commit()

        logger.info(f"[scheduler] check_renewal_campaigns: sent {followed_up} follow-ups")
    except Exception as exc:
        logger.error(f"[scheduler] check_renewal_campaigns failed: {exc}", exc_info=True)
        db.rollback()
    finally:
        db.close()
