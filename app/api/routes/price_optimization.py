"""
Price Optimization Engine Routes
All endpoints require JWT auth + owner role.

Prefix: /api/price-optimization
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
from app.models.price_optimization import (
    MarketComparable,
    PriceOptimizationSettings,
    RentReview,
    VacancyHistory,
)
from app.models.property import Property, Unit
from app.models.user import User, UserRole
from app.schemas.price_optimization import (
    AcceptReviewRequest,
    GenerateReviewRequest,
    MarketComparableCreate,
    MarketComparableResponse,
    PortfolioHealthResponse,
    PriceOptimizationSettingsResponse,
    PriceOptimizationSettingsUpdate,
    RentReviewResponse,
    VacancyHistoryResponse,
)
from app.services.price_optimization_service import PriceOptimizationService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Rent Optimizer"])


# ── Auth gate ─────────────────────────────────────────────────────────────────

def require_owner(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in (UserRole.OWNER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted to property owners.",
        )
    return current_user


# ── Helper: enrich reviews with unit/property names ───────────────────────────

def _enrich_review(review: RentReview, db: Session) -> RentReviewResponse:
    unit = db.query(Unit).filter(Unit.id == review.unit_id).first()
    prop = (
        db.query(Property).filter(Property.id == review.property_id).first()
        if review.property_id else None
    )
    data = {
        "id": str(review.id),
        "owner_id": str(review.owner_id),
        "unit_id": str(review.unit_id),
        "property_id": str(review.property_id) if review.property_id else "",
        "unit_number": unit.unit_number if unit else None,
        "property_name": prop.name if prop else None,
        "trigger": review.trigger,
        "current_rent": float(review.current_rent),
        "recommended_rent": float(review.recommended_rent),
        "min_rent": float(review.min_rent),
        "max_rent": float(review.max_rent),
        "confidence_score": review.confidence_score,
        "reasoning": review.reasoning or [],
        "market_data_snapshot": review.market_data_snapshot,
        "status": review.status,
        "accepted_rent": float(review.accepted_rent) if review.accepted_rent else None,
        "reviewed_at": review.reviewed_at,
        "applied_at": review.applied_at,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
    }
    return RentReviewResponse(**data)


# ═══════════════════════════════════════════════════════════════════════════════
# REVIEWS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/reviews", response_model=List[RentReviewResponse])
def list_reviews(
    status_filter: Optional[str] = Query(None, alias="status"),
    property_id: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    q = db.query(RentReview).filter(RentReview.owner_id == current_user.id)
    if status_filter:
        q = q.filter(RentReview.status == status_filter)
    if property_id:
        try:
            q = q.filter(RentReview.property_id == uuid.UUID(property_id))
        except ValueError:
            pass
    reviews = q.order_by(RentReview.created_at.desc()).offset(skip).limit(limit).all()
    return [_enrich_review(r, db) for r in reviews]


@router.get("/reviews/{review_id}", response_model=RentReviewResponse)
def get_review(
    review_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        rid = uuid.UUID(review_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid review ID")

    review = db.query(RentReview).filter(
        RentReview.id == rid,
        RentReview.owner_id == current_user.id,
    ).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return _enrich_review(review, db)


@router.post("/reviews/{review_id}/accept", response_model=RentReviewResponse)
def accept_review(
    review_id: str,
    body: AcceptReviewRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        svc = PriceOptimizationService(db, current_user.id)
        review = svc.apply_recommendation(
            review_id=review_id,
            accepted_rent=body.accepted_rent,
            reviewed_by=current_user.id,
        )
        return _enrich_review(review, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"[price_opt] accept_review failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to accept review")


@router.post("/reviews/{review_id}/reject", response_model=RentReviewResponse)
def reject_review(
    review_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        rid = uuid.UUID(review_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid review ID")

    review = db.query(RentReview).filter(
        RentReview.id == rid,
        RentReview.owner_id == current_user.id,
    ).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.status not in ("pending",):
        raise HTTPException(status_code=400, detail=f"Cannot reject review with status '{review.status}'")

    review.status = "rejected"
    review.reviewed_by = current_user.id
    review.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(review)
    return _enrich_review(review, db)


@router.post("/reviews/generate", response_model=RentReviewResponse)
def generate_review(
    body: GenerateReviewRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    # Verify unit belongs to owner
    unit_uuid: Optional[uuid.UUID] = None
    try:
        unit_uuid = uuid.UUID(body.unit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid unit_id")

    unit = db.query(Unit).filter(Unit.id == unit_uuid).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    prop = db.query(Property).filter(
        Property.id == unit.property_id,
        Property.user_id == current_user.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=403, detail="Unit does not belong to your portfolio")

    try:
        svc = PriceOptimizationService(db, current_user.id)
        review = svc.create_review(unit_id=body.unit_id, trigger="manual")
        return _enrich_review(review, db)
    except Exception as e:
        logger.error(f"[price_opt] generate_review failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate review: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO HEALTH
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/portfolio-health", response_model=PortfolioHealthResponse)
def portfolio_health(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        svc = PriceOptimizationService(db, current_user.id)
        health = svc.get_portfolio_health()
        return PortfolioHealthResponse(**health)
    except Exception as e:
        logger.error(f"[price_opt] portfolio_health failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to compute portfolio health")


# ═══════════════════════════════════════════════════════════════════════════════
# MARKET COMPARABLES
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/comparables", response_model=List[MarketComparableResponse])
def list_comparables(
    unit_type: Optional[str] = Query(None),
    location_area: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    q = db.query(MarketComparable).filter(
        MarketComparable.owner_id == current_user.id
    )
    if unit_type:
        q = q.filter(MarketComparable.unit_type == unit_type)
    if location_area:
        q = q.filter(MarketComparable.location_area.ilike(f"%{location_area}%"))
    if date_from:
        q = q.filter(MarketComparable.data_date >= date_from)
    comps = q.order_by(MarketComparable.data_date.desc()).all()
    return [
        MarketComparableResponse(
            id=str(c.id),
            owner_id=str(c.owner_id),
            property_id=str(c.property_id) if c.property_id else None,
            unit_type=c.unit_type,
            bedrooms=c.bedrooms,
            location_area=c.location_area,
            asking_rent=float(c.asking_rent),
            actual_rent=float(c.actual_rent) if c.actual_rent else None,
            vacancy_days=c.vacancy_days,
            source=c.source,
            data_date=c.data_date,
            notes=c.notes,
            created_at=c.created_at,
        )
        for c in comps
    ]


@router.post("/comparables", response_model=MarketComparableResponse, status_code=201)
def add_comparable(
    body: MarketComparableCreate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    comp = MarketComparable(
        id=uuid.uuid4(),
        owner_id=current_user.id,
        unit_type=body.unit_type,
        bedrooms=body.bedrooms,
        location_area=body.location_area,
        asking_rent=body.asking_rent,
        actual_rent=body.actual_rent,
        vacancy_days=body.vacancy_days,
        source=body.source,
        data_date=body.data_date,
        notes=body.notes,
    )
    db.add(comp)
    db.commit()
    db.refresh(comp)
    return MarketComparableResponse(
        id=str(comp.id),
        owner_id=str(comp.owner_id),
        property_id=None,
        unit_type=comp.unit_type,
        bedrooms=comp.bedrooms,
        location_area=comp.location_area,
        asking_rent=float(comp.asking_rent),
        actual_rent=float(comp.actual_rent) if comp.actual_rent else None,
        vacancy_days=comp.vacancy_days,
        source=comp.source,
        data_date=comp.data_date,
        notes=comp.notes,
        created_at=comp.created_at,
    )


@router.delete("/comparables/{comparable_id}", status_code=204)
def delete_comparable(
    comparable_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        cid = uuid.UUID(comparable_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid comparable ID")

    comp = db.query(MarketComparable).filter(
        MarketComparable.id == cid,
        MarketComparable.owner_id == current_user.id,
    ).first()
    if not comp:
        raise HTTPException(status_code=404, detail="Comparable not found")
    db.delete(comp)
    db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/settings", response_model=PriceOptimizationSettingsResponse)
def get_settings(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    svc = PriceOptimizationService(db, current_user.id)
    settings = svc._get_settings()
    return PriceOptimizationSettingsResponse(
        id=str(settings.id),
        owner_id=str(settings.owner_id),
        is_enabled=settings.is_enabled,
        auto_apply=settings.auto_apply,
        max_increase_pct=float(settings.max_increase_pct),
        max_decrease_pct=float(settings.max_decrease_pct),
        target_vacancy_days=settings.target_vacancy_days,
        min_rent_floor=float(settings.min_rent_floor) if settings.min_rent_floor else None,
        comparable_radius_km=float(settings.comparable_radius_km),
        created_at=settings.created_at,
        updated_at=settings.updated_at,
    )


@router.put("/settings", response_model=PriceOptimizationSettingsResponse)
def update_settings(
    body: PriceOptimizationSettingsUpdate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    svc = PriceOptimizationService(db, current_user.id)
    settings = svc._get_settings()

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(settings, field, value)

    db.commit()
    db.refresh(settings)
    return PriceOptimizationSettingsResponse(
        id=str(settings.id),
        owner_id=str(settings.owner_id),
        is_enabled=settings.is_enabled,
        auto_apply=settings.auto_apply,
        max_increase_pct=float(settings.max_increase_pct),
        max_decrease_pct=float(settings.max_decrease_pct),
        target_vacancy_days=settings.target_vacancy_days,
        min_rent_floor=float(settings.min_rent_floor) if settings.min_rent_floor else None,
        comparable_radius_km=float(settings.comparable_radius_km),
        created_at=settings.created_at,
        updated_at=settings.updated_at,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# VACANCY HISTORY
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/vacancy-history", response_model=List[VacancyHistoryResponse])
def list_vacancy_history(
    unit_id: Optional[str] = Query(None),
    filled: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    q = db.query(VacancyHistory).filter(
        VacancyHistory.owner_id == current_user.id
    )
    if unit_id:
        try:
            q = q.filter(VacancyHistory.unit_id == uuid.UUID(unit_id))
        except ValueError:
            pass
    if filled is True:
        q = q.filter(VacancyHistory.vacant_until != None)  # noqa: E711
    elif filled is False:
        q = q.filter(VacancyHistory.vacant_until == None)  # noqa: E711

    records = q.order_by(VacancyHistory.vacant_from.desc()).offset(skip).limit(limit).all()

    result = []
    for r in records:
        unit = db.query(Unit).filter(Unit.id == r.unit_id).first()
        prop = (
            db.query(Property).filter(Property.id == unit.property_id).first()
            if unit else None
        )
        result.append(VacancyHistoryResponse(
            id=str(r.id),
            unit_id=str(r.unit_id),
            owner_id=str(r.owner_id),
            unit_number=unit.unit_number if unit else None,
            property_name=prop.name if prop else None,
            vacant_from=r.vacant_from,
            vacant_until=r.vacant_until,
            days_vacant=r.days_vacant,
            rent_at_vacancy=float(r.rent_at_vacancy),
            rent_when_filled=float(r.rent_when_filled) if r.rent_when_filled else None,
            price_changes_count=r.price_changes_count,
            filled_by_tenant_id=str(r.filled_by_tenant_id) if r.filled_by_tenant_id else None,
            created_at=r.created_at,
        ))
    return result
