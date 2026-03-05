"""
Vendor & Maintenance Intelligence Routes
Prefixes: /api/vendors, /api/vendor-jobs, /api/maintenance-schedules,
          /api/maintenance-budgets, /api/vendor-analytics
All endpoints require JWT auth + owner role.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.property import Property, Unit
from app.models.user import User, UserRole
from app.models.vendor_intelligence import (
    MaintenanceCostBudget,
    MaintenanceSchedule,
    Vendor,
    VendorJob,
)
from app.schemas.vendor_intelligence import (
    AnalyticsSummaryResponse,
    AssignJobRequest,
    BlacklistRequest,
    BudgetCreate,
    BudgetResponse,
    BudgetUpdate,
    CompleteJobRequest,
    CostAnalyticsResponse,
    MaintenanceScheduleCreate,
    MaintenanceScheduleResponse,
    MaintenanceScheduleUpdate,
    MarkPaidRequest,
    RateJobRequest,
    ScorecardResponse,
    VendorCreate,
    VendorJobCreate,
    VendorJobResponse,
    VendorJobUpdate,
    VendorResponse,
    VendorUpdate,
)
from app.services.vendor_service import VendorService, _compute_vendor_score

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Vendor Intelligence"])


# ── Auth gate ─────────────────────────────────────────────────────────────────

def require_owner(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in (UserRole.OWNER, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Access restricted to property owners.")
    return current_user


# ── Serialisers ───────────────────────────────────────────────────────────────

def _vendor_resp(v: Vendor, score: Optional[float] = None) -> VendorResponse:
    return VendorResponse(
        id=str(v.id), owner_id=str(v.owner_id), name=v.name, category=v.category,
        phone=v.phone, email=v.email, location_area=v.location_area,
        rating=float(v.rating) if v.rating else None,
        total_jobs=v.total_jobs or 0, completed_jobs=v.completed_jobs or 0,
        avg_response_hours=float(v.avg_response_hours) if v.avg_response_hours else None,
        avg_completion_days=float(v.avg_completion_days) if v.avg_completion_days else None,
        total_paid=float(v.total_paid or 0),
        is_preferred=v.is_preferred, is_blacklisted=v.is_blacklisted,
        blacklist_reason=v.blacklist_reason, notes=v.notes,
        score=score if score is not None else _compute_vendor_score(v),
        created_at=v.created_at, updated_at=v.updated_at,
    )


def _job_resp(j: VendorJob, db: Session) -> VendorJobResponse:
    vendor = db.query(Vendor).filter(Vendor.id == j.vendor_id).first()
    unit = db.query(Unit).filter(Unit.id == j.unit_id).first() if j.unit_id else None
    prop = db.query(Property).filter(Property.id == j.property_id).first() if j.property_id else None
    return VendorJobResponse(
        id=str(j.id), owner_id=str(j.owner_id),
        vendor_id=str(j.vendor_id),
        vendor_name=vendor.name if vendor else None,
        vendor_phone=vendor.phone if vendor else None,
        vendor_rating=float(vendor.rating) if vendor and vendor.rating else None,
        maintenance_request_id=str(j.maintenance_request_id) if j.maintenance_request_id else None,
        unit_id=str(j.unit_id),
        unit_number=unit.unit_number if unit else None,
        property_id=str(j.property_id),
        property_name=prop.name if prop else None,
        title=j.title, description=j.description, category=j.category,
        priority=j.priority, status=j.status,
        quoted_amount=float(j.quoted_amount) if j.quoted_amount else None,
        final_amount=float(j.final_amount) if j.final_amount else None,
        paid=j.paid or False, paid_at=j.paid_at, payment_method=j.payment_method,
        assigned_at=j.assigned_at, started_at=j.started_at, completed_at=j.completed_at,
        due_date=j.due_date,
        owner_rating=j.owner_rating, owner_review=j.owner_review, rated_at=j.rated_at,
        photos_before=j.photos_before or [], photos_after=j.photos_after or [],
        notes=j.notes,
        schedule_id=str(j.schedule_id) if j.schedule_id else None,
        created_at=j.created_at, updated_at=j.updated_at,
    )


def _schedule_resp(s: MaintenanceSchedule, db: Session) -> MaintenanceScheduleResponse:
    prop = db.query(Property).filter(Property.id == s.property_id).first() if s.property_id else None
    unit = db.query(Unit).filter(Unit.id == s.unit_id).first() if s.unit_id else None
    vendor = db.query(Vendor).filter(Vendor.id == s.preferred_vendor_id).first() if s.preferred_vendor_id else None
    return MaintenanceScheduleResponse(
        id=str(s.id), owner_id=str(s.owner_id),
        property_id=str(s.property_id) if s.property_id else None,
        property_name=prop.name if prop else None,
        unit_id=str(s.unit_id) if s.unit_id else None,
        unit_number=unit.unit_number if unit else None,
        title=s.title, category=s.category, description=s.description,
        frequency=s.frequency, next_due=s.next_due, last_completed=s.last_completed,
        estimated_cost=float(s.estimated_cost) if s.estimated_cost else None,
        preferred_vendor_id=str(s.preferred_vendor_id) if s.preferred_vendor_id else None,
        preferred_vendor_name=vendor.name if vendor else None,
        is_active=s.is_active, auto_create_job=s.auto_create_job,
        created_at=s.created_at, updated_at=s.updated_at,
    )


def _budget_resp(b: MaintenanceCostBudget, db: Session) -> BudgetResponse:
    prop = db.query(Property).filter(Property.id == b.property_id).first() if b.property_id else None
    return BudgetResponse(
        id=str(b.id), owner_id=str(b.owner_id),
        property_id=str(b.property_id) if b.property_id else None,
        property_name=prop.name if prop else None,
        year=b.year, month=b.month,
        budget_amount=float(b.budget_amount),
        actual_amount=float(b.actual_amount or 0),
        created_at=b.created_at, updated_at=b.updated_at,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# VENDORS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/vendors", response_model=List[VendorResponse])
def list_vendors(
    category: Optional[str] = Query(None),
    is_preferred: Optional[bool] = Query(None),
    is_blacklisted: Optional[bool] = Query(None),
    sort_by: str = Query("rating", enum=["rating", "jobs", "spend"]),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    q = db.query(Vendor).filter(Vendor.owner_id == current_user.id)
    if category:
        q = q.filter(Vendor.category == category)
    if is_preferred is not None:
        q = q.filter(Vendor.is_preferred == is_preferred)
    if is_blacklisted is not None:
        q = q.filter(Vendor.is_blacklisted == is_blacklisted)
    vendors = q.all()

    scored = [_vendor_resp(v) for v in vendors]
    if sort_by == "rating":
        scored.sort(key=lambda x: (x.rating or 0), reverse=True)
    elif sort_by == "jobs":
        scored.sort(key=lambda x: x.total_jobs, reverse=True)
    elif sort_by == "spend":
        scored.sort(key=lambda x: x.total_paid, reverse=True)
    return scored


@router.post("/vendors", response_model=VendorResponse, status_code=201)
def create_vendor(
    body: VendorCreate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    v = Vendor(
        id=uuid.uuid4(), owner_id=current_user.id,
        name=body.name, category=body.category, phone=body.phone,
        email=body.email, location_area=body.location_area,
        notes=body.notes, is_preferred=body.is_preferred,
        total_jobs=0, completed_jobs=0, total_paid=0,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return _vendor_resp(v)


@router.get("/vendors/recommend", response_model=List[dict])
def recommend_vendors(
    category: str = Query(...),
    unit_id: Optional[str] = Query(None),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    svc = VendorService(db, current_user.id)
    return svc.get_recommended_vendors(category, unit_id)


@router.get("/vendors/{vendor_id}", response_model=VendorResponse)
def get_vendor(
    vendor_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    v = _fetch_vendor(vendor_id, current_user.id, db)
    return _vendor_resp(v)


@router.put("/vendors/{vendor_id}", response_model=VendorResponse)
def update_vendor(
    vendor_id: str,
    body: VendorUpdate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    v = _fetch_vendor(vendor_id, current_user.id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(v, field, value)
    db.commit()
    db.refresh(v)
    return _vendor_resp(v)


@router.post("/vendors/{vendor_id}/blacklist", response_model=VendorResponse)
def blacklist_vendor(
    vendor_id: str,
    body: BlacklistRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    v = _fetch_vendor(vendor_id, current_user.id, db)
    v.is_blacklisted = True
    v.blacklist_reason = body.reason
    v.is_preferred = False
    db.commit()
    db.refresh(v)
    return _vendor_resp(v)


@router.post("/vendors/{vendor_id}/unblacklist", response_model=VendorResponse)
def unblacklist_vendor(
    vendor_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    v = _fetch_vendor(vendor_id, current_user.id, db)
    v.is_blacklisted = False
    v.blacklist_reason = None
    db.commit()
    db.refresh(v)
    return _vendor_resp(v)


@router.get("/vendors/{vendor_id}/scorecard", response_model=ScorecardResponse)
def vendor_scorecard(
    vendor_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    svc = VendorService(db, current_user.id)
    try:
        return ScorecardResponse(**svc.get_vendor_scorecard(vendor_id))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# VENDOR JOBS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/vendor-jobs", response_model=List[VendorJobResponse])
def list_jobs(
    status_filter: Optional[str] = Query(None, alias="status"),
    vendor_id: Optional[str] = Query(None),
    property_id: Optional[str] = Query(None),
    unit_id: Optional[str] = Query(None),
    paid: Optional[bool] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    q = db.query(VendorJob).filter(VendorJob.owner_id == current_user.id)
    if status_filter:
        q = q.filter(VendorJob.status == status_filter)
    if vendor_id:
        try:
            q = q.filter(VendorJob.vendor_id == uuid.UUID(vendor_id))
        except ValueError:
            pass
    if property_id:
        try:
            q = q.filter(VendorJob.property_id == uuid.UUID(property_id))
        except ValueError:
            pass
    if unit_id:
        try:
            q = q.filter(VendorJob.unit_id == uuid.UUID(unit_id))
        except ValueError:
            pass
    if paid is not None:
        q = q.filter(VendorJob.paid == paid)
    if date_from:
        q = q.filter(VendorJob.assigned_at >= datetime(date_from.year, date_from.month, date_from.day, tzinfo=timezone.utc))
    if date_to:
        q = q.filter(VendorJob.assigned_at <= datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=timezone.utc))
    jobs = q.order_by(VendorJob.created_at.desc()).offset(skip).limit(limit).all()
    return [_job_resp(j, db) for j in jobs]


@router.post("/vendor-jobs", response_model=VendorJobResponse, status_code=201)
def create_job(
    body: VendorJobCreate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    # Resolve property_id from unit
    try:
        unit_uuid = uuid.UUID(body.unit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid unit_id")
    unit = db.query(Unit).filter(Unit.id == unit_uuid).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    prop = db.query(Property).filter(
        Property.id == unit.property_id, Property.user_id == current_user.id
    ).first()
    if not prop:
        raise HTTPException(status_code=403, detail="Unit not in your portfolio")

    svc = VendorService(db, current_user.id)
    try:
        job = svc.assign_job(
            vendor_id=body.vendor_id,
            unit_id=body.unit_id,
            property_id=str(unit.property_id),
            title=body.title,
            description=body.description,
            category=body.category,
            priority=body.priority,
            quoted_amount=body.quoted_amount,
            due_date=body.due_date,
            maintenance_request_id=body.maintenance_request_id,
            notes=body.notes,
        )
        return _job_resp(job, db)
    except Exception as e:
        logger.error(f"[vendor] create_job failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vendor-jobs/{job_id}", response_model=VendorJobResponse)
def get_job(
    job_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    job = _fetch_job(job_id, current_user.id, db)
    return _job_resp(job, db)


@router.put("/vendor-jobs/{job_id}", response_model=VendorJobResponse)
def update_job(
    job_id: str,
    body: VendorJobUpdate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    job = _fetch_job(job_id, current_user.id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(job, field, value)
    db.commit()
    db.refresh(job)
    return _job_resp(job, db)


@router.post("/vendor-jobs/{job_id}/assign", response_model=VendorJobResponse)
def assign_job(
    job_id: str,
    body: AssignJobRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    job = _fetch_job(job_id, current_user.id, db)
    try:
        vendor_uuid = uuid.UUID(body.vendor_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid vendor_id")
    vendor = db.query(Vendor).filter(
        Vendor.id == vendor_uuid, Vendor.owner_id == current_user.id
    ).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    job.vendor_id = vendor_uuid
    job.quoted_amount = body.quoted_amount or job.quoted_amount
    job.due_date = body.due_date or job.due_date
    job.status = "assigned"
    job.assigned_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return _job_resp(job, db)


@router.post("/vendor-jobs/{job_id}/start", response_model=VendorJobResponse)
def start_job(
    job_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    job = _fetch_job(job_id, current_user.id, db)
    job.status = "in_progress"
    job.started_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return _job_resp(job, db)


@router.post("/vendor-jobs/{job_id}/complete", response_model=VendorJobResponse)
def complete_job(
    job_id: str,
    body: CompleteJobRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    svc = VendorService(db, current_user.id)
    try:
        job = svc.complete_job(job_id, body.final_amount, body.photos_after)
        return _job_resp(job, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/vendor-jobs/{job_id}/rate", response_model=VendorJobResponse)
def rate_job(
    job_id: str,
    body: RateJobRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    svc = VendorService(db, current_user.id)
    try:
        job = svc.rate_vendor(job_id, body.rating, body.review)
        return _job_resp(job, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/vendor-jobs/{job_id}/mark-paid", response_model=VendorJobResponse)
def mark_paid(
    job_id: str,
    body: MarkPaidRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    svc = VendorService(db, current_user.id)
    try:
        job = svc.mark_paid(job_id, body.payment_method)
        return _job_resp(job, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/vendor-jobs/{job_id}/dispute", response_model=VendorJobResponse)
def dispute_job(
    job_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    job = _fetch_job(job_id, current_user.id, db)
    job.status = "disputed"
    db.commit()
    db.refresh(job)
    # Alert owner
    _send_owner_alert(current_user, job, db)
    return _job_resp(job, db)


# ═══════════════════════════════════════════════════════════════════════════════
# MAINTENANCE SCHEDULES
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/maintenance-schedules", response_model=List[MaintenanceScheduleResponse])
def list_schedules(
    property_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    frequency: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    q = db.query(MaintenanceSchedule).filter(MaintenanceSchedule.owner_id == current_user.id)
    if property_id:
        try:
            q = q.filter(MaintenanceSchedule.property_id == uuid.UUID(property_id))
        except ValueError:
            pass
    if category:
        q = q.filter(MaintenanceSchedule.category == category)
    if frequency:
        q = q.filter(MaintenanceSchedule.frequency == frequency)
    if is_active is not None:
        q = q.filter(MaintenanceSchedule.is_active == is_active)
    schedules = q.order_by(MaintenanceSchedule.next_due.asc()).all()
    return [_schedule_resp(s, db) for s in schedules]


@router.post("/maintenance-schedules", response_model=MaintenanceScheduleResponse, status_code=201)
def create_schedule(
    body: MaintenanceScheduleCreate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    s = MaintenanceSchedule(
        id=uuid.uuid4(), owner_id=current_user.id,
        property_id=uuid.UUID(body.property_id) if body.property_id else None,
        unit_id=uuid.UUID(body.unit_id) if body.unit_id else None,
        title=body.title, category=body.category, description=body.description,
        frequency=body.frequency, next_due=body.next_due,
        estimated_cost=body.estimated_cost,
        preferred_vendor_id=uuid.UUID(body.preferred_vendor_id) if body.preferred_vendor_id else None,
        auto_create_job=body.auto_create_job, is_active=True,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _schedule_resp(s, db)


@router.put("/maintenance-schedules/{schedule_id}", response_model=MaintenanceScheduleResponse)
def update_schedule(
    schedule_id: str,
    body: MaintenanceScheduleUpdate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    s = _fetch_schedule(schedule_id, current_user.id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "preferred_vendor_id" and value:
            try:
                value = uuid.UUID(value)
            except ValueError:
                continue
        setattr(s, field, value)
    db.commit()
    db.refresh(s)
    return _schedule_resp(s, db)


@router.delete("/maintenance-schedules/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    s = _fetch_schedule(schedule_id, current_user.id, db)
    s.is_active = False
    db.commit()


@router.post("/maintenance-schedules/{schedule_id}/complete", response_model=MaintenanceScheduleResponse)
def complete_schedule(
    schedule_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    from app.services.vendor_service import _advance_schedule
    s = _fetch_schedule(schedule_id, current_user.id, db)
    _advance_schedule(s)
    db.commit()
    db.refresh(s)
    return _schedule_resp(s, db)


# ═══════════════════════════════════════════════════════════════════════════════
# BUDGETS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/maintenance-budgets", response_model=List[BudgetResponse])
def list_budgets(
    property_id: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    q = db.query(MaintenanceCostBudget).filter(MaintenanceCostBudget.owner_id == current_user.id)
    if property_id:
        try:
            q = q.filter(MaintenanceCostBudget.property_id == uuid.UUID(property_id))
        except ValueError:
            pass
    if year:
        q = q.filter(MaintenanceCostBudget.year == year)
    budgets = q.order_by(MaintenanceCostBudget.year.desc(), MaintenanceCostBudget.month.asc()).all()
    return [_budget_resp(b, db) for b in budgets]


@router.post("/maintenance-budgets", response_model=BudgetResponse, status_code=201)
def create_budget(
    body: BudgetCreate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    b = MaintenanceCostBudget(
        id=uuid.uuid4(), owner_id=current_user.id,
        property_id=uuid.UUID(body.property_id) if body.property_id else None,
        year=body.year, month=body.month,
        budget_amount=body.budget_amount, actual_amount=0,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return _budget_resp(b, db)


@router.put("/maintenance-budgets/{budget_id}", response_model=BudgetResponse)
def update_budget(
    budget_id: str,
    body: BudgetUpdate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        bid = uuid.UUID(budget_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid budget ID")
    b = db.query(MaintenanceCostBudget).filter(
        MaintenanceCostBudget.id == bid,
        MaintenanceCostBudget.owner_id == current_user.id,
    ).first()
    if not b:
        raise HTTPException(status_code=404, detail="Budget not found")
    b.budget_amount = body.budget_amount
    db.commit()
    db.refresh(b)
    return _budget_resp(b, db)


# ═══════════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/vendor-analytics/costs", response_model=CostAnalyticsResponse)
def cost_analytics(
    property_id: Optional[str] = Query(None),
    months: int = Query(12, ge=1, le=60),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    svc = VendorService(db, current_user.id)
    data = svc.get_cost_analytics(property_id=property_id, months=months)
    return CostAnalyticsResponse(**data)


@router.get("/vendor-analytics/summary", response_model=AnalyticsSummaryResponse)
def analytics_summary(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    from datetime import date as _date
    today = _date.today()
    owner_id = current_user.id

    total_vendors = db.query(Vendor).filter(Vendor.owner_id == owner_id).count()
    preferred = db.query(Vendor).filter(
        Vendor.owner_id == owner_id, Vendor.is_preferred == True  # noqa: E712
    ).count()
    blacklisted = db.query(Vendor).filter(
        Vendor.owner_id == owner_id, Vendor.is_blacklisted == True  # noqa: E712
    ).count()
    active_jobs = db.query(VendorJob).filter(
        VendorJob.owner_id == owner_id,
        VendorJob.status.in_(["assigned", "in_progress"]),
    ).count()

    month_start = datetime(today.year, today.month, 1, tzinfo=timezone.utc)
    completed_month = db.query(VendorJob).filter(
        VendorJob.owner_id == owner_id,
        VendorJob.status == "completed",
        VendorJob.completed_at >= month_start,
    ).count()

    spend_month_rows = db.query(VendorJob).filter(
        VendorJob.owner_id == owner_id,
        VendorJob.paid == True,  # noqa: E712
        VendorJob.completed_at >= month_start,
    ).all()
    spend_month = sum(float(j.final_amount or 0) for j in spend_month_rows)

    year_start = datetime(today.year, 1, 1, tzinfo=timezone.utc)
    spend_year_rows = db.query(VendorJob).filter(
        VendorJob.owner_id == owner_id,
        VendorJob.paid == True,  # noqa: E712
        VendorJob.completed_at >= year_start,
    ).all()
    spend_year = sum(float(j.final_amount or 0) for j in spend_year_rows)

    # Budget utilisation for current month
    budgets = db.query(MaintenanceCostBudget).filter(
        MaintenanceCostBudget.owner_id == owner_id,
        MaintenanceCostBudget.year == today.year,
        MaintenanceCostBudget.month == today.month,
    ).all()
    total_budget = sum(float(b.budget_amount) for b in budgets)
    budget_util = round(spend_month / total_budget * 100, 1) if total_budget > 0 else 0.0

    return AnalyticsSummaryResponse(
        total_vendors=total_vendors,
        preferred_count=preferred,
        blacklisted_count=blacklisted,
        active_jobs_count=active_jobs,
        jobs_completed_this_month=completed_month,
        total_spend_this_month=round(spend_month, 2),
        total_spend_this_year=round(spend_year, 2),
        budget_utilisation_pct=budget_util,
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _fetch_vendor(vendor_id: str, owner_id, db: Session) -> Vendor:
    try:
        vid = uuid.UUID(vendor_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid vendor ID")
    v = db.query(Vendor).filter(Vendor.id == vid, Vendor.owner_id == owner_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return v


def _fetch_job(job_id: str, owner_id, db: Session) -> VendorJob:
    try:
        jid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID")
    j = db.query(VendorJob).filter(VendorJob.id == jid, VendorJob.owner_id == owner_id).first()
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    return j


def _fetch_schedule(schedule_id: str, owner_id, db: Session) -> MaintenanceSchedule:
    try:
        sid = uuid.UUID(schedule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid schedule ID")
    s = db.query(MaintenanceSchedule).filter(
        MaintenanceSchedule.id == sid,
        MaintenanceSchedule.owner_id == owner_id,
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return s


def _send_owner_alert(owner: User, job: VendorJob, db: Session) -> None:
    from app.services.vendor_service import _send_sms
    phone = getattr(owner, "phone", None)
    if phone:
        _send_sms(phone, f"PROPERTECH: Job '{job.title}' has been disputed. Log in to review.")
