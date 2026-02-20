"""
Vacancy Listing Syndication Routes
Premium feature — all owner-facing endpoints require an active subscription.

Owner endpoints (JWT required):
  GET    /api/listings/                       list owner's listings
  POST   /api/listings/                       create listing
  GET    /api/listings/{id}                   get listing detail
  PUT    /api/listings/{id}                   update listing
  DELETE /api/listings/{id}                   delete draft listing
  POST   /api/listings/{id}/publish           activate + syndicate
  POST   /api/listings/{id}/pause             pause active listing
  POST   /api/listings/{id}/mark-filled       close listing, update unit
  POST   /api/listings/{id}/syndicate         (re)syndicate to a platform
  GET    /api/listings/{id}/leads             list leads
  PUT    /api/listings/{id}/leads/{lead_id}   update lead status/notes
  GET    /api/listings/{id}/analytics         analytics summary
  GET    /api/listings/auto-populate/{unit_id} pre-fill from unit data

Public endpoints (no auth, rate-limited):
  GET    /api/listings/public/{slug}          public listing page
  POST   /api/listings/public/{slug}/inquiry  submit lead
"""
from __future__ import annotations

import uuid
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.listing import (
    VacancyListing, ListingSyndication, ListingLead, ListingAnalytics,
    ListingStatus, SyndicationPlatform, LeadStatus, AnalyticsEventType,
)
from app.models.payment import Subscription, SubscriptionStatus
from app.models.property import Property, Unit
from app.models.user import User, UserRole
from app.schemas.listing import (
    AutoPopulateResponse,
    LeadCreate, LeadOut, LeadUpdate,
    ListingCreate, ListingOut, ListingUpdate, ListingListResponse,
    PublicListingOut, PublishRequest, SyndicateRequest,
    AnalyticsSummary, SyndicationOut,
)
from app.services.listing_service import ListingService
from app.services.syndication_service import SyndicationService
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Listings"])


# ── Rate-limit store (in-memory, per process) ──────────────────────────────────
# {(ip, slug): [timestamp, ...]}
_rate_limit_store: Dict[tuple, List[datetime]] = defaultdict(list)

_RATE_LIMIT_MAX = 3
_RATE_LIMIT_WINDOW = timedelta(hours=1)


def _check_rate_limit(ip: str, slug: str) -> None:
    key = (ip, slug)
    now = datetime.utcnow()
    window_start = now - _RATE_LIMIT_WINDOW
    # Prune old entries
    _rate_limit_store[key] = [t for t in _rate_limit_store[key] if t > window_start]
    if len(_rate_limit_store[key]) >= _RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many inquiries submitted. Please try again later.",
        )
    _rate_limit_store[key].append(now)


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Premium gate ───────────────────────────────────────────────────────────────

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
                    "Vacancy Listing Syndication is a premium feature. "
                    "Upgrade to Professional or Enterprise to unlock it."
                ),
                "upgrade_url": "/owner/subscription",
            },
        )
    return current_user


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_listing_or_404(
    listing_id: uuid.UUID,
    owner_id: uuid.UUID,
    db: Session,
) -> VacancyListing:
    listing = (
        db.query(VacancyListing)
        .filter(
            VacancyListing.id == listing_id,
            VacancyListing.owner_id == owner_id,
        )
        .first()
    )
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return listing


def _enrich_listing(listing: VacancyListing, db: Session) -> Dict[str, Any]:
    """Add denormalised fields for API response."""
    d = {
        "id": listing.id,
        "owner_id": listing.owner_id,
        "property_id": listing.property_id,
        "unit_id": listing.unit_id,
        "title": listing.title,
        "description": listing.description,
        "monthly_rent": listing.monthly_rent,
        "deposit_amount": listing.deposit_amount,
        "available_from": listing.available_from,
        "amenities": listing.amenities or [],
        "photos": listing.photos or [],
        "status": listing.status.value if hasattr(listing.status, "value") else listing.status,
        "slug": listing.slug,
        "view_count": listing.view_count or 0,
        "published_at": listing.published_at,
        "filled_at": listing.filled_at,
        "created_at": listing.created_at,
        "updated_at": listing.updated_at,
        "syndications": [
            {
                "id": s.id,
                "listing_id": s.listing_id,
                "platform": s.platform.value if hasattr(s.platform, "value") else s.platform,
                "status": s.status.value if hasattr(s.status, "value") else s.status,
                "external_url": s.external_url,
                "share_url": s.share_url,
                "published_at": s.published_at,
                "last_synced_at": s.last_synced_at,
                "error_message": s.error_message,
                "created_at": s.created_at,
            }
            for s in (listing.syndications or [])
        ],
        "lead_count": len(listing.leads or []),
        "property_name": None,
        "unit_number": None,
        "days_on_market": None,
    }

    if listing.published_at:
        end = listing.filled_at or datetime.utcnow()
        d["days_on_market"] = max(0, (end - listing.published_at).days)

    if listing.property_id:
        prop = db.query(Property).filter(Property.id == listing.property_id).first()
        if prop:
            d["property_name"] = prop.name

    if listing.unit_id:
        unit = db.query(Unit).filter(Unit.id == listing.unit_id).first()
        if unit:
            d["unit_number"] = unit.unit_number

    return d


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC ENDPOINTS (no auth required)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/public/{slug}", response_model=PublicListingOut)
def get_public_listing(
    slug: str,
    ref: Optional[str] = Query(None, description="Referral source platform"),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Return a public listing by slug. Increments view count and records analytics."""
    listing = (
        db.query(VacancyListing)
        .filter(
            VacancyListing.slug == slug,
            VacancyListing.status == ListingStatus.ACTIVE,
        )
        .first()
    )
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found or no longer available")

    svc = ListingService(db)
    svc.increment_view_count(listing)

    ip = _get_client_ip(request) if request else None
    ua = request.headers.get("user-agent") if request else None
    svc.record_event(
        listing_id=listing.id,
        event_type=AnalyticsEventType.VIEW,
        platform=ref,
        ip_address=ip,
        user_agent=ua,
    )

    prop = db.query(Property).filter(Property.id == listing.property_id).first() if listing.property_id else None
    unit = db.query(Unit).filter(Unit.id == listing.unit_id).first() if listing.unit_id else None

    return {
        "id": listing.id,
        "title": listing.title,
        "description": listing.description,
        "monthly_rent": listing.monthly_rent,
        "deposit_amount": listing.deposit_amount,
        "available_from": listing.available_from,
        "amenities": listing.amenities or [],
        "photos": listing.photos or [],
        "slug": listing.slug,
        "view_count": listing.view_count,
        "published_at": listing.published_at,
        "property_name": prop.name if prop else None,
        "unit_number": unit.unit_number if unit else None,
        "area": getattr(prop, "area", None) if prop else None,
        "city": getattr(prop, "city", None) if prop else None,
        "bedrooms": unit.bedrooms if unit else None,
        "bathrooms": unit.bathrooms if unit else None,
    }


@router.post("/public/{slug}/inquiry", status_code=201)
def submit_inquiry(
    slug: str,
    payload: LeadCreate,
    ref: Optional[str] = Query(None),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Submit an inquiry for a listing. Rate-limited to 3 per IP per listing per hour."""
    ip = _get_client_ip(request) if request else "unknown"
    _check_rate_limit(ip, slug)

    listing = (
        db.query(VacancyListing)
        .filter(
            VacancyListing.slug == slug,
            VacancyListing.status == ListingStatus.ACTIVE,
        )
        .first()
    )
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found or no longer available")

    if not payload.email and not payload.phone:
        raise HTTPException(
            status_code=422,
            detail="Please provide at least an email or phone number.",
        )

    source = ref or payload.source_platform or "direct"
    lead = ListingLead(
        listing_id=listing.id,
        owner_id=listing.owner_id,
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        message=payload.message,
        source_platform=source,
        status=LeadStatus.NEW,
    )
    db.add(lead)
    db.commit()

    # Record inquiry analytics event
    ua = request.headers.get("user-agent") if request else None
    svc = ListingService(db)
    svc.record_event(
        listing_id=listing.id,
        event_type=AnalyticsEventType.INQUIRY,
        platform=source,
        ip_address=ip,
        user_agent=ua,
    )

    # Notify owner (best-effort)
    from app.models.user import User as UserModel
    owner = db.query(UserModel).filter(UserModel.id == listing.owner_id).first()
    if owner and owner.email:
        svc.notify_owner_new_lead(
            owner_email=owner.email,
            lead_name=payload.name,
            listing_title=listing.title,
            listing_slug=slug,
            phone=payload.phone,
            message=payload.message,
            frontend_url=settings.FRONTEND_URL,
        )

    return {"success": True, "message": "Inquiry submitted successfully. The landlord will be in touch soon."}


# ══════════════════════════════════════════════════════════════════════════════
# OWNER ENDPOINTS (JWT + premium required)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/auto-populate/{unit_id}", response_model=AutoPopulateResponse)
def auto_populate(
    unit_id: uuid.UUID,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Pre-fill a new listing draft from existing unit/property data."""
    svc = ListingService(db)
    data = svc.auto_populate_from_unit(unit_id, current_user.id)
    if not data:
        raise HTTPException(status_code=404, detail="Unit not found")
    return data


@router.get("/", response_model=ListingListResponse)
def list_listings(
    status_filter: Optional[str] = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """List all listings for the authenticated owner."""
    q = db.query(VacancyListing).filter(VacancyListing.owner_id == current_user.id)
    if status_filter:
        try:
            q = q.filter(VacancyListing.status == ListingStatus(status_filter))
        except ValueError:
            pass
    total = q.count()
    listings = q.order_by(VacancyListing.created_at.desc()).offset(skip).limit(limit).all()

    # Summary counts
    all_listings = db.query(VacancyListing).filter(VacancyListing.owner_id == current_user.id).all()
    active_count = sum(1 for l in all_listings if l.status == ListingStatus.ACTIVE)
    draft_count = sum(1 for l in all_listings if l.status == ListingStatus.DRAFT)

    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    filled_this_month = sum(
        1 for l in all_listings
        if l.status == ListingStatus.FILLED and l.filled_at and l.filled_at >= month_start
    )

    # Avg days on market (filled listings)
    dom_vals = []
    for l in all_listings:
        if l.status == ListingStatus.FILLED and l.published_at and l.filled_at:
            dom_vals.append((l.filled_at - l.published_at).days)
    avg_dom = (sum(dom_vals) / len(dom_vals)) if dom_vals else None

    # Leads this month
    total_leads_this_month = (
        db.query(ListingLead)
        .filter(
            ListingLead.owner_id == current_user.id,
            ListingLead.created_at >= month_start,
        )
        .count()
    )

    enriched = [_enrich_listing(l, db) for l in listings]

    return {
        "listings": enriched,
        "total": total,
        "active_count": active_count,
        "draft_count": draft_count,
        "filled_this_month": filled_this_month,
        "avg_days_on_market": avg_dom,
        "total_leads_this_month": total_leads_this_month,
    }


@router.post("/", status_code=201)
def create_listing(
    payload: ListingCreate,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Create a new listing (optionally auto-populate from unit_id)."""
    svc = ListingService(db)

    # Build slug from title
    slug_base = payload.title
    if payload.unit_id:
        unit = db.query(Unit).filter(Unit.id == payload.unit_id).first()
        prop = (
            db.query(Property).filter(Property.id == unit.property_id).first()
            if unit else None
        )
        pname = prop.name if prop else "property"
        uname = unit.unit_number if unit else "unit"
        slug = svc.generate_slug(pname, uname)
    else:
        slug = svc.generate_slug(slug_base, "")

    listing = VacancyListing(
        owner_id=current_user.id,
        property_id=payload.property_id,
        unit_id=payload.unit_id,
        title=payload.title,
        description=payload.description,
        monthly_rent=payload.monthly_rent,
        deposit_amount=payload.deposit_amount or 0.0,
        available_from=payload.available_from,
        amenities=payload.amenities or [],
        photos=payload.photos or [],
        status=ListingStatus.DRAFT,
        slug=slug,
        view_count=0,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)

    logger.info(f"[listing] Created listing {listing.id} slug={slug} owner={current_user.email}")
    return _enrich_listing(listing, db)


@router.get("/{listing_id}")
def get_listing(
    listing_id: uuid.UUID,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Get a single listing with syndications and lead count."""
    listing = _get_listing_or_404(listing_id, current_user.id, db)
    return _enrich_listing(listing, db)


@router.put("/{listing_id}")
def update_listing(
    listing_id: uuid.UUID,
    payload: ListingUpdate,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Update a listing's details."""
    listing = _get_listing_or_404(listing_id, current_user.id, db)

    updates = payload.model_dump(exclude_none=True)
    for field, value in updates.items():
        setattr(listing, field, value)
    listing.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(listing)
    return _enrich_listing(listing, db)


@router.delete("/{listing_id}", status_code=204)
def delete_listing(
    listing_id: uuid.UUID,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Delete a draft listing. Cannot delete active/filled listings."""
    listing = _get_listing_or_404(listing_id, current_user.id, db)
    if listing.status not in (ListingStatus.DRAFT, ListingStatus.PAUSED):
        raise HTTPException(
            status_code=400,
            detail="Only draft or paused listings can be deleted. Pause or mark as filled first.",
        )
    db.delete(listing)
    db.commit()


@router.post("/{listing_id}/publish")
def publish_listing(
    listing_id: uuid.UUID,
    payload: PublishRequest,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Activate a listing and syndicate to selected platforms."""
    listing = _get_listing_or_404(listing_id, current_user.id, db)

    if listing.status == ListingStatus.FILLED:
        raise HTTPException(status_code=400, detail="Cannot re-publish a filled listing.")

    listing.status = ListingStatus.ACTIVE
    if not listing.published_at:
        listing.published_at = datetime.utcnow()
    listing.updated_at = datetime.utcnow()
    db.commit()

    # Syndicate to platforms
    synd_svc = SyndicationService(db)
    syndications = synd_svc.syndicate_all(listing, payload.platforms)

    db.refresh(listing)
    result = _enrich_listing(listing, db)
    logger.info(f"[listing] Published {listing_id} to platforms: {payload.platforms}")
    return result


@router.post("/{listing_id}/pause")
def pause_listing(
    listing_id: uuid.UUID,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Pause an active listing."""
    listing = _get_listing_or_404(listing_id, current_user.id, db)
    if listing.status != ListingStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Only active listings can be paused.")

    listing.status = ListingStatus.PAUSED
    listing.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(listing)
    return _enrich_listing(listing, db)


@router.post("/{listing_id}/mark-filled")
def mark_filled(
    listing_id: uuid.UUID,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Mark a listing as filled and update the linked unit to occupied."""
    listing = _get_listing_or_404(listing_id, current_user.id, db)
    svc = ListingService(db)
    result = svc.mark_listing_filled(listing_id)
    if not result:
        raise HTTPException(status_code=404, detail="Listing not found")
    return _enrich_listing(result, db)


@router.post("/{listing_id}/syndicate")
def syndicate_platform(
    listing_id: uuid.UUID,
    payload: SyndicateRequest,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """(Re)syndicate a listing to a specific platform."""
    listing = _get_listing_or_404(listing_id, current_user.id, db)
    if listing.status not in (ListingStatus.ACTIVE, ListingStatus.DRAFT):
        raise HTTPException(status_code=400, detail="Listing must be active or draft to syndicate.")

    synd_svc = SyndicationService(db)
    try:
        syndication = synd_svc.syndicate(listing, payload.platform)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "id": str(syndication.id),
        "platform": syndication.platform.value if hasattr(syndication.platform, "value") else syndication.platform,
        "status": syndication.status.value if hasattr(syndication.status, "value") else syndication.status,
        "share_url": syndication.share_url,
        "external_url": syndication.external_url,
        "error_message": syndication.error_message,
        "last_synced_at": syndication.last_synced_at,
    }


# ── Leads ──────────────────────────────────────────────────────────────────────

@router.get("/{listing_id}/leads")
def list_leads(
    listing_id: uuid.UUID,
    status_filter: Optional[str] = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """List all leads for a listing."""
    _get_listing_or_404(listing_id, current_user.id, db)

    q = db.query(ListingLead).filter(ListingLead.listing_id == listing_id)
    if status_filter:
        try:
            q = q.filter(ListingLead.status == LeadStatus(status_filter))
        except ValueError:
            pass

    total = q.count()
    leads = q.order_by(ListingLead.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "leads": [
            {
                "id": str(l.id),
                "listing_id": str(l.listing_id),
                "owner_id": str(l.owner_id),
                "name": l.name,
                "email": l.email,
                "phone": l.phone,
                "message": l.message,
                "source_platform": l.source_platform,
                "status": l.status.value if hasattr(l.status, "value") else l.status,
                "notes": l.notes,
                "created_at": l.created_at,
                "updated_at": l.updated_at,
            }
            for l in leads
        ],
        "total": total,
    }


@router.put("/{listing_id}/leads/{lead_id}")
def update_lead(
    listing_id: uuid.UUID,
    lead_id: uuid.UUID,
    payload: LeadUpdate,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Update a lead's status or notes."""
    _get_listing_or_404(listing_id, current_user.id, db)

    lead = (
        db.query(ListingLead)
        .filter(
            ListingLead.id == lead_id,
            ListingLead.listing_id == listing_id,
        )
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if payload.status is not None:
        try:
            lead.status = LeadStatus(payload.status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid lead status: {payload.status}")
    if payload.notes is not None:
        lead.notes = payload.notes
    lead.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(lead)
    return {
        "id": str(lead.id),
        "status": lead.status.value if hasattr(lead.status, "value") else lead.status,
        "notes": lead.notes,
        "updated_at": lead.updated_at,
    }


# ── Analytics ──────────────────────────────────────────────────────────────────

@router.get("/{listing_id}/analytics", response_model=AnalyticsSummary)
def get_analytics(
    listing_id: uuid.UUID,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Get analytics summary for a listing."""
    _get_listing_or_404(listing_id, current_user.id, db)
    svc = ListingService(db)
    return svc.get_analytics_summary(listing_id)
