"""
Vendor & Maintenance Intelligence Service
Core business logic: vendor scoring, job assignment, cost analytics,
schedule management, budget tracking.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.vendor_intelligence import (
    MaintenanceCostBudget,
    MaintenanceSchedule,
    Vendor,
    VendorJob,
)
from app.models.maintenance import MaintenanceRequest
from app.models.property import Property, Unit

logger = logging.getLogger(__name__)

# ── SMS helper ────────────────────────────────────────────────────────────────

def _send_sms(phone: str, message: str) -> None:
    from app.core.config import settings as _cfg
    at_key = getattr(_cfg, "AT_API_KEY", None)
    at_user = getattr(_cfg, "AT_USERNAME", "sandbox")
    sender = getattr(_cfg, "AT_SENDER_ID", None)
    if not phone:
        return
    if not at_key:
        logger.info(f"[vendor] DEV SMS to {phone}: {message[:120]}")
        return
    try:
        import africastalking
        africastalking.initialize(at_user, at_key)
        kwargs = {"message": message, "recipients": [phone]}
        if sender:
            kwargs["sender_id"] = sender
        africastalking.SMS.send(**kwargs)
    except Exception as exc:
        logger.warning(f"[vendor] SMS failed to {phone}: {exc}")


def _log_action(
    db: Session,
    owner_id: uuid.UUID,
    action_type: str,
    payload: Dict[str, Any],
    result: Dict[str, Any],
    status: str = "success",
) -> None:
    """Log to automation_actions_log for audit trail. Never raises."""
    try:
        from app.models.automation import AutomationActionLog
        log = AutomationActionLog(
            id=uuid.uuid4(),
            execution_id=uuid.UUID(int=0),
            owner_id=owner_id,
            action_type=action_type,
            action_payload=payload,
            result_status=status,
            result_data=result,
            executed_at=datetime.now(timezone.utc),
            reversible=False,
        )
        db.add(log)
        db.commit()
    except Exception as exc:
        logger.warning(f"[vendor] _log_action failed: {exc}")
        try:
            db.rollback()
        except Exception:
            pass


def _compute_vendor_score(vendor: Vendor) -> float:
    """Compute vendor score 0–100."""
    score = float(vendor.rating or 3.0) * 20
    if vendor.is_preferred:
        score += 10
    if vendor.avg_response_hours and float(vendor.avg_response_hours) > 48:
        score -= 20
    if (
        vendor.total_jobs >= 3
        and vendor.completed_jobs is not None
        and vendor.total_jobs > 0
        and (vendor.completed_jobs / vendor.total_jobs) < 0.7
    ):
        score -= 15
    return max(0.0, min(100.0, round(score, 1)))


class VendorService:
    def __init__(self, db: Session, owner_id: uuid.UUID) -> None:
        self.db = db
        self.owner_id = owner_id

    # ── Vendor recommendations ────────────────────────────────────────────────

    def get_recommended_vendors(
        self, category: str, unit_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        vendors = (
            self.db.query(Vendor)
            .filter(
                Vendor.owner_id == self.owner_id,
                Vendor.category == category,
                Vendor.is_blacklisted == False,  # noqa: E712
            )
            .all()
        )
        scored = []
        for v in vendors:
            score = _compute_vendor_score(v)
            scored.append({
                "id": str(v.id),
                "name": v.name,
                "category": v.category,
                "phone": v.phone,
                "email": v.email,
                "rating": float(v.rating) if v.rating else None,
                "total_jobs": v.total_jobs,
                "completed_jobs": v.completed_jobs,
                "avg_response_hours": float(v.avg_response_hours) if v.avg_response_hours else None,
                "avg_completion_days": float(v.avg_completion_days) if v.avg_completion_days else None,
                "total_paid": float(v.total_paid or 0),
                "is_preferred": v.is_preferred,
                "score": score,
            })
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:5]

    # ── Assign job ────────────────────────────────────────────────────────────

    def assign_job(
        self,
        vendor_id: str,
        unit_id: str,
        property_id: str,
        title: str,
        category: str,
        description: Optional[str] = None,
        priority: str = "normal",
        quoted_amount: Optional[float] = None,
        due_date: Optional[date] = None,
        maintenance_request_id: Optional[str] = None,
        schedule_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> VendorJob:
        vendor_uuid = uuid.UUID(vendor_id)
        unit_uuid = uuid.UUID(unit_id)
        prop_uuid = uuid.UUID(property_id)
        now = datetime.now(timezone.utc)

        job = VendorJob(
            id=uuid.uuid4(),
            owner_id=self.owner_id,
            vendor_id=vendor_uuid,
            unit_id=unit_uuid,
            property_id=prop_uuid,
            title=title,
            description=description,
            category=category,
            priority=priority,
            status="assigned",
            quoted_amount=quoted_amount,
            due_date=due_date,
            assigned_at=now,
            photos_before=[],
            photos_after=[],
            notes=notes,
            schedule_id=uuid.UUID(schedule_id) if schedule_id else None,
        )
        if maintenance_request_id:
            try:
                job.maintenance_request_id = uuid.UUID(maintenance_request_id)
            except ValueError:
                pass

        self.db.add(job)

        # Update maintenance_request status + assign vendor
        if maintenance_request_id:
            try:
                mr = self.db.query(MaintenanceRequest).filter(
                    MaintenanceRequest.id == uuid.UUID(maintenance_request_id)
                ).first()
                if mr:
                    mr.status = "in_progress"
                    # assigned_vendor_id added via startup ALTER TABLE
                    if hasattr(mr, "assigned_vendor_id"):
                        mr.assigned_vendor_id = vendor_uuid
            except Exception as e:
                logger.warning(f"[vendor] Could not update maintenance_request: {e}")

        # Increment vendor.total_jobs
        vendor = self.db.query(Vendor).filter(Vendor.id == vendor_uuid).first()
        if vendor:
            vendor.total_jobs = (vendor.total_jobs or 0) + 1

        self.db.commit()
        self.db.refresh(job)

        # SMS vendor — never throws
        try:
            if vendor and vendor.phone:
                unit = self.db.query(Unit).filter(Unit.id == unit_uuid).first()
                prop = self.db.query(Property).filter(Property.id == prop_uuid).first()
                owner_user = self.db.query(
                    __import__("app.models.user", fromlist=["User"]).User
                ).filter_by(id=self.owner_id).first()
                owner_phone = owner_user.phone if owner_user and hasattr(owner_user, "phone") else ""
                due_str = str(due_date) if due_date else "ASAP"
                msg = (
                    f"New job from PROPERTECH: {title} at "
                    f"{prop.name if prop else 'property'}, "
                    f"Unit {unit.unit_number if unit else ''}. "
                    f"Due: {due_str}. Contact owner: {owner_phone}. "
                    f"Ref: {str(job.id)[:8].upper()}"
                )
                _send_sms(vendor.phone, msg)
        except Exception as sms_err:
            _log_action(
                self.db, self.owner_id,
                "vendor_sms_failed",
                {"job_id": str(job.id), "vendor_id": vendor_id},
                {"error": str(sms_err)},
                status="failed",
            )

        return job

    # ── Complete job ──────────────────────────────────────────────────────────

    def complete_job(
        self, job_id: str, final_amount: float, photos_after: List[str]
    ) -> VendorJob:
        job = self._get_job(job_id)
        now = datetime.now(timezone.utc)

        job.status = "completed"
        job.completed_at = now
        job.final_amount = final_amount
        job.photos_after = photos_after

        # Update maintenance_request
        if job.maintenance_request_id:
            mr = self.db.query(MaintenanceRequest).filter(
                MaintenanceRequest.id == job.maintenance_request_id
            ).first()
            if mr:
                mr.status = "resolved"

        # Update vendor metrics
        vendor = self.db.query(Vendor).filter(Vendor.id == job.vendor_id).first()
        if vendor:
            vendor.completed_jobs = (vendor.completed_jobs or 0) + 1
            vendor.total_paid = float(vendor.total_paid or 0) + final_amount

            # Recompute avg_completion_days
            if job.assigned_at:
                assigned = job.assigned_at
                if assigned.tzinfo is None:
                    assigned = assigned.replace(tzinfo=timezone.utc)
                days = (now - assigned).days
                prev_avg = float(vendor.avg_completion_days or days)
                prev_count = max(1, (vendor.completed_jobs or 1) - 1)
                vendor.avg_completion_days = round(
                    (prev_avg * prev_count + days) / vendor.completed_jobs, 2
                )

        # Atomically update budget actual — single UPDATE statement
        today = date.today()
        self.db.execute(
            text("""
                UPDATE maintenance_cost_budgets
                SET actual_amount = actual_amount + :amount,
                    updated_at = NOW()
                WHERE owner_id = :owner_id
                  AND year = :year
                  AND (month = :month OR month IS NULL)
                  AND (property_id = :property_id OR property_id IS NULL)
            """),
            {
                "amount": final_amount,
                "owner_id": str(self.owner_id),
                "year": today.year,
                "month": today.month,
                "property_id": str(job.property_id),
            },
        )

        self.db.commit()
        self.db.refresh(job)
        return job

    # ── Rate vendor ───────────────────────────────────────────────────────────

    def rate_vendor(self, job_id: str, rating: int, review: Optional[str]) -> VendorJob:
        job = self._get_job(job_id)
        now = datetime.now(timezone.utc)

        job.owner_rating = rating
        job.owner_review = review
        job.rated_at = now
        self.db.flush()

        # Recompute vendor.rating via DB AVG to avoid race conditions
        avg_result = self.db.execute(
            text("""
                SELECT AVG(owner_rating::float)
                FROM vendor_jobs
                WHERE vendor_id = :vendor_id
                  AND owner_rating IS NOT NULL
            """),
            {"vendor_id": str(job.vendor_id)},
        ).scalar()

        if avg_result is not None:
            self.db.execute(
                text("""
                    UPDATE vendors
                    SET rating = :rating, updated_at = NOW()
                    WHERE id = :vendor_id
                """),
                {"rating": round(float(avg_result), 2), "vendor_id": str(job.vendor_id)},
            )

        self.db.commit()
        self.db.refresh(job)
        return job

    # ── Mark paid ─────────────────────────────────────────────────────────────

    def mark_paid(self, job_id: str, payment_method: str) -> VendorJob:
        job = self._get_job(job_id)
        now = datetime.now(timezone.utc)
        final = float(job.final_amount or job.quoted_amount or 0)

        job.paid = True
        job.paid_at = now
        job.payment_method = payment_method

        # Atomically update budget actual for payment
        today = date.today()
        self.db.execute(
            text("""
                UPDATE maintenance_cost_budgets
                SET actual_amount = actual_amount + :amount,
                    updated_at = NOW()
                WHERE owner_id = :owner_id
                  AND year = :year
                  AND (month = :month OR month IS NULL)
                  AND (property_id = :property_id OR property_id IS NULL)
                  AND budget_amount > 0
            """),
            {
                "amount": final,
                "owner_id": str(self.owner_id),
                "year": today.year,
                "month": today.month,
                "property_id": str(job.property_id),
            },
        )

        self.db.commit()
        self.db.refresh(job)
        return job

    # ── Cost analytics ────────────────────────────────────────────────────────

    def get_cost_analytics(
        self, property_id: Optional[str] = None, months: int = 12
    ) -> Dict[str, Any]:
        from datetime import datetime as _dt
        cutoff = date.today() - timedelta(days=months * 30)

        q = self.db.query(VendorJob).filter(
            VendorJob.owner_id == self.owner_id,
            VendorJob.paid == True,  # noqa: E712
            VendorJob.completed_at >= datetime(
                cutoff.year, cutoff.month, cutoff.day, tzinfo=timezone.utc
            ),
        )
        if property_id:
            try:
                q = q.filter(VendorJob.property_id == uuid.UUID(property_id))
            except ValueError:
                pass

        jobs = q.all()
        total = sum(float(j.final_amount or 0) for j in jobs)

        # Spend by category
        by_cat: Dict[str, float] = {}
        for j in jobs:
            by_cat[j.category] = by_cat.get(j.category, 0) + float(j.final_amount or 0)

        # Spend by property
        by_prop: Dict[str, float] = {}
        for j in jobs:
            prop = self.db.query(Property).filter(Property.id == j.property_id).first()
            key = prop.name if prop else str(j.property_id)
            by_prop[key] = by_prop.get(key, 0) + float(j.final_amount or 0)

        # Spend by vendor (top 5)
        by_vendor_raw: Dict[str, Dict] = {}
        for j in jobs:
            k = str(j.vendor_id)
            if k not in by_vendor_raw:
                v = self.db.query(Vendor).filter(Vendor.id == j.vendor_id).first()
                by_vendor_raw[k] = {"vendor_name": v.name if v else k, "total": 0, "jobs": 0}
            by_vendor_raw[k]["total"] += float(j.final_amount or 0)
            by_vendor_raw[k]["jobs"] += 1
        top_vendors = sorted(by_vendor_raw.values(), key=lambda x: x["total"], reverse=True)[:5]

        # Monthly breakdown
        monthly: Dict[str, Dict] = {}
        for j in jobs:
            if j.completed_at:
                ct = j.completed_at
                if ct.tzinfo is None:
                    ct = ct.replace(tzinfo=timezone.utc)
                key = ct.strftime("%Y-%m")
                monthly.setdefault(key, {"actual": 0.0})
                monthly[key]["actual"] += float(j.final_amount or 0)

        avg_monthly = round(total / max(1, len(monthly)), 2)
        most_expensive = (
            max(monthly, key=lambda k: monthly[k]["actual"]) if monthly else ""
        )

        # Budget vs actual per month
        budgets = (
            self.db.query(MaintenanceCostBudget)
            .filter(
                MaintenanceCostBudget.owner_id == self.owner_id,
                MaintenanceCostBudget.month != None,  # noqa: E711
            )
            .all()
        )
        bva: List[Dict] = []
        for b in budgets:
            month_key = f"{b.year}-{b.month:02d}"
            actual = monthly.get(month_key, {}).get("actual", 0.0)
            bva.append({
                "month": month_key,
                "budget": float(b.budget_amount),
                "actual": actual,
                "variance": actual - float(b.budget_amount),
            })

        return {
            "total_spend": round(total, 2),
            "spend_by_category": {k: round(v, 2) for k, v in by_cat.items()},
            "spend_by_property": {k: round(v, 2) for k, v in by_prop.items()},
            "spend_by_vendor": top_vendors,
            "avg_monthly_spend": avg_monthly,
            "most_expensive_month": most_expensive,
            "budget_vs_actual": sorted(bva, key=lambda x: x["month"]),
        }

    # ── Vendor scorecard ──────────────────────────────────────────────────────

    def get_vendor_scorecard(self, vendor_id: str) -> Dict[str, Any]:
        vendor_uuid = uuid.UUID(vendor_id)
        vendor = self.db.query(Vendor).filter(
            Vendor.id == vendor_uuid,
            Vendor.owner_id == self.owner_id,
        ).first()
        if not vendor:
            raise ValueError(f"Vendor {vendor_id} not found")

        jobs = (
            self.db.query(VendorJob)
            .filter(VendorJob.vendor_id == vendor_uuid)
            .all()
        )
        completed = [j for j in jobs if j.status == "completed"]
        cancelled = [j for j in jobs if j.status == "cancelled"]

        # On-time rate
        on_time = [
            j for j in completed
            if j.due_date and j.completed_at
            and j.completed_at.date() <= j.due_date
        ]
        on_time_rate = round(len(on_time) / max(1, len(completed)) * 100, 1)

        avg_rating = None
        rated = [j.owner_rating for j in jobs if j.owner_rating]
        if rated:
            avg_rating = round(sum(rated) / len(rated), 2)

        # Jobs by category
        by_cat: Dict[str, int] = {}
        for j in jobs:
            by_cat[j.category] = by_cat.get(j.category, 0) + 1

        # Jobs by property
        by_prop: Dict[str, int] = {}
        for j in jobs:
            prop = self.db.query(Property).filter(Property.id == j.property_id).first()
            key = prop.name if prop else str(j.property_id)
            by_prop[key] = by_prop.get(key, 0) + 1

        # Recent reviews
        reviews = [
            {
                "rating": j.owner_rating,
                "review": j.owner_review,
                "job_title": j.title,
                "date": j.rated_at.date().isoformat() if j.rated_at else None,
            }
            for j in sorted(
                [j for j in jobs if j.owner_rating],
                key=lambda x: x.rated_at or datetime.min,
                reverse=True,
            )[:5]
        ]

        return {
            "vendor_id": vendor_id,
            "name": vendor.name,
            "total_jobs": len(jobs),
            "completed_jobs": len(completed),
            "cancelled_jobs": len(cancelled),
            "avg_response_hours": float(vendor.avg_response_hours) if vendor.avg_response_hours else None,
            "avg_completion_days": float(vendor.avg_completion_days) if vendor.avg_completion_days else None,
            "on_time_rate": on_time_rate,
            "avg_rating": avg_rating,
            "total_paid": float(vendor.total_paid or 0),
            "jobs_by_category": by_cat,
            "jobs_by_property": by_prop,
            "recent_reviews": reviews,
        }

    # ── Check due schedules ───────────────────────────────────────────────────

    def check_due_schedules(self) -> List[MaintenanceSchedule]:
        """
        Called by scheduler daily.
        Idempotent — skips schedules that already have an active job.
        Returns list of triggered schedules.
        """
        today = date.today()
        window = today + timedelta(days=7)

        schedules = (
            self.db.query(MaintenanceSchedule)
            .filter(
                MaintenanceSchedule.owner_id == self.owner_id,
                MaintenanceSchedule.is_active == True,  # noqa: E712
                MaintenanceSchedule.next_due <= window,
            )
            .all()
        )

        triggered = []
        for sched in schedules:
            # Idempotency: skip if active job exists for this schedule in current period
            existing_job = (
                self.db.query(VendorJob)
                .filter(
                    VendorJob.schedule_id == sched.id,
                    VendorJob.status.notin_(["completed", "cancelled"]),
                )
                .first()
            )
            if existing_job:
                continue

            if sched.auto_create_job and sched.preferred_vendor_id:
                # Resolve unit/property
                unit_id = str(sched.unit_id) if sched.unit_id else None
                prop_id = str(sched.property_id) if sched.property_id else None

                if unit_id:
                    unit = self.db.query(Unit).filter(Unit.id == sched.unit_id).first()
                    if unit:
                        prop_id = prop_id or str(unit.property_id)

                if not prop_id or not unit_id:
                    # Fetch first unit from property
                    if sched.property_id:
                        unit = (
                            self.db.query(Unit)
                            .filter(Unit.property_id == sched.property_id)
                            .first()
                        )
                        if unit:
                            unit_id = str(unit.id)
                            prop_id = str(sched.property_id)

                if unit_id and prop_id:
                    try:
                        self.assign_job(
                            vendor_id=str(sched.preferred_vendor_id),
                            unit_id=unit_id,
                            property_id=prop_id,
                            title=sched.title,
                            category=sched.category,
                            description=sched.description,
                            quoted_amount=float(sched.estimated_cost) if sched.estimated_cost else None,
                            due_date=sched.next_due,
                            schedule_id=str(sched.id),
                        )
                    except Exception as exc:
                        logger.warning(f"[vendor] auto-assign job for schedule {sched.id}: {exc}")
            else:
                # Create maintenance_request and fire event
                from app.services.event_bus import event_bus, PropertyEvent
                prop = (
                    self.db.query(Property).filter(Property.id == sched.property_id).first()
                    if sched.property_id else None
                )
                event_bus.publish(PropertyEvent(
                    event_type="maintenance_request_created",
                    owner_id=str(self.owner_id),
                    payload={
                        "title": sched.title,
                        "category": sched.category,
                        "property_id": str(sched.property_id) if sched.property_id else None,
                        "unit_id": str(sched.unit_id) if sched.unit_id else None,
                        "property_name": prop.name if prop else "",
                        "priority": "normal",
                        "source": "schedule",
                        "schedule_id": str(sched.id),
                    },
                    source="maintenance_scheduler",
                ))

            # Advance next_due based on frequency
            _advance_schedule(sched)
            triggered.append(sched)

        if triggered:
            self.db.commit()

        return triggered

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_job(self, job_id: str) -> VendorJob:
        job = self.db.query(VendorJob).filter(
            VendorJob.id == uuid.UUID(job_id),
            VendorJob.owner_id == self.owner_id,
        ).first()
        if not job:
            raise ValueError(f"VendorJob {job_id} not found")
        return job


# ── Frequency helpers ─────────────────────────────────────────────────────────

_FREQUENCY_DAYS = {
    "monthly": 30,
    "quarterly": 91,
    "biannual": 182,
    "annual": 365,
    "one_time": None,
}


def _advance_schedule(sched: MaintenanceSchedule) -> None:
    today = date.today()
    sched.last_completed = today
    days = _FREQUENCY_DAYS.get(sched.frequency)
    if days is None:
        sched.is_active = False  # one_time — deactivate after triggering
    else:
        sched.next_due = today + timedelta(days=days)
