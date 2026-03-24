"""
Vacancy Prevention Engine Routes
Prefix: /api/vacancy
All endpoints require JWT auth + owner role.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.lease import Lease, LeaseStatus
from app.models.property import Property, Unit
from app.models.user import User, UserRole
from app.models.vacancy_prevention import (
    VacancyPreventionListing as ListingSyndication,  # renamed to avoid table conflict
    RenewalCampaign,
    VacancyLead,
    VacancyLeadActivity,
    VacancyPreventionSettings,
)
from app.schemas.vacancy_prevention import (
    CampaignRespondRequest,
    ConvertLeadRequest,
    LeadActivityCreate,
    LeadActivityResponse,
    LeadWithActivities,
    ListingSyndicationCreate,
    ListingSyndicationResponse,
    ListingSyndicationUpdate,
    PipelineStatsResponse,
    RenewalCampaignCreate,
    RenewalCampaignResponse,
    UnitAtRiskResponse,
    VacancyLeadCreate,
    VacancyLeadResponse,
    VacancyLeadUpdate,
    VacancyPreventionSettingsResponse,
    VacancyPreventionSettingsUpdate,
)
from app.services.vacancy_prevention_service import VacancyPreventionService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Vacancy Prevention"])


# ── Auth gate ─────────────────────────────────────────────────────────────────

def require_owner(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in (UserRole.OWNER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted to property owners.",
        )
    return current_user


# ── Serialiser helpers ────────────────────────────────────────────────────────

def _lead_response(lead: VacancyLead) -> VacancyLeadResponse:
    return VacancyLeadResponse(
        id=str(lead.id),
        owner_id=str(lead.owner_id),
        property_id=str(lead.property_id) if lead.property_id else None,
        unit_id=str(lead.unit_id) if lead.unit_id else None,
        lead_name=lead.lead_name,
        lead_phone=lead.lead_phone,
        lead_email=lead.lead_email,
        source=lead.source,
        status=lead.status,
        preferred_unit_type=lead.preferred_unit_type,
        preferred_move_in=lead.preferred_move_in,
        budget_min=float(lead.budget_min) if lead.budget_min else None,
        budget_max=float(lead.budget_max) if lead.budget_max else None,
        notes=lead.notes,
        last_contacted_at=lead.last_contacted_at,
        follow_up_due_at=lead.follow_up_due_at,
        converted_tenant_id=str(lead.converted_tenant_id) if lead.converted_tenant_id else None,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


def _activity_response(a: VacancyLeadActivity) -> LeadActivityResponse:
    return LeadActivityResponse(
        id=str(a.id),
        lead_id=str(a.lead_id),
        owner_id=str(a.owner_id),
        activity_type=a.activity_type,
        content=a.content,
        performed_by=str(a.performed_by),
        created_at=a.created_at,
    )


def _syndication_response(s: ListingSyndication) -> ListingSyndicationResponse:
    return ListingSyndicationResponse(
        id=str(s.id),
        owner_id=str(s.owner_id),
        unit_id=str(s.unit_id),
        listing_id=str(s.listing_id) if s.listing_id else None,
        title=s.title,
        description=s.description,
        monthly_rent=float(s.monthly_rent),
        bedrooms=s.bedrooms,
        bathrooms=s.bathrooms,
        unit_type=s.unit_type,
        amenities=s.amenities or [],
        photos=s.photos or [],
        location_area=s.location_area,
        status=s.status,
        view_count=s.view_count or 0,
        enquiry_count=s.enquiry_count or 0,
        platforms=s.platforms or [],
        published_at=s.published_at,
        filled_at=s.filled_at,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _campaign_response(c: RenewalCampaign, db: Session) -> RenewalCampaignResponse:
    unit = db.query(Unit).filter(Unit.id == c.unit_id).first() if c.unit_id else None
    prop = (
        db.query(Property).filter(Property.id == unit.property_id).first()
        if unit and unit.property_id else None
    )
    lease = db.query(Lease).filter(Lease.id == c.lease_id).first() if c.lease_id else None
    days_left = None
    if lease and lease.end_date:
        end = lease.end_date
        if hasattr(end, "tzinfo") and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        days_left = max(0, (end - datetime.now(timezone.utc)).days)

    return RenewalCampaignResponse(
        id=str(c.id),
        owner_id=str(c.owner_id),
        lease_id=str(c.lease_id),
        tenant_id=str(c.tenant_id) if c.tenant_id else None,
        unit_id=str(c.unit_id),
        tenant_name=lease.tenant_name if lease else None,
        unit_number=unit.unit_number if unit else None,
        property_name=prop.name if prop else None,
        days_until_expiry=days_left,
        campaign_status=c.campaign_status,
        trigger_days_before_expiry=c.trigger_days_before_expiry,
        offer_type=c.offer_type,
        incentive_description=c.incentive_description,
        proposed_rent=float(c.proposed_rent) if c.proposed_rent else None,
        current_rent=float(c.current_rent),
        tenant_response=c.tenant_response,
        response_received_at=c.response_received_at,
        follow_up_count=c.follow_up_count or 0,
        last_follow_up_at=c.last_follow_up_at,
        outcome=c.outcome,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _settings_response(s: VacancyPreventionSettings) -> VacancyPreventionSettingsResponse:
    return VacancyPreventionSettingsResponse(
        id=str(s.id),
        owner_id=str(s.owner_id),
        is_enabled=s.is_enabled,
        auto_create_listing=s.auto_create_listing,
        auto_syndicate=s.auto_syndicate,
        renewal_campaign_days=s.renewal_campaign_days or [60, 30, 7],
        lead_follow_up_hours=s.lead_follow_up_hours,
        auto_sms_new_leads=s.auto_sms_new_leads,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# LEADS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/leads", response_model=List[VacancyLeadResponse])
def list_leads(
    status_filter: Optional[str] = Query(None, alias="status"),
    unit_id: Optional[str] = Query(None),
    property_id: Optional[str] = Query(None),
    overdue_only: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    q = db.query(VacancyLead).filter(VacancyLead.owner_id == current_user.id)
    if status_filter:
        q = q.filter(VacancyLead.status == status_filter)
    if unit_id:
        try:
            q = q.filter(VacancyLead.unit_id == uuid.UUID(unit_id))
        except ValueError:
            pass
    if property_id:
        try:
            q = q.filter(VacancyLead.property_id == uuid.UUID(property_id))
        except ValueError:
            pass
    if overdue_only:
        q = q.filter(VacancyLead.follow_up_due_at < now)
    leads = q.order_by(VacancyLead.created_at.desc()).offset(skip).limit(limit).all()
    return [_lead_response(l) for l in leads]


@router.post("/leads", response_model=VacancyLeadResponse, status_code=201)
def create_lead(
    body: VacancyLeadCreate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    svc = VacancyPreventionService(db, current_user.id)
    lead = svc.create_lead(body.model_dump())
    return _lead_response(lead)


@router.get("/leads/{lead_id}", response_model=LeadWithActivities)
def get_lead(
    lead_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        lid = uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead ID")

    lead = db.query(VacancyLead).filter(
        VacancyLead.id == lid,
        VacancyLead.owner_id == current_user.id,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    activities = (
        db.query(VacancyLeadActivity)
        .filter(VacancyLeadActivity.lead_id == lid)
        .order_by(VacancyLeadActivity.created_at.asc())
        .all()
    )
    resp = LeadWithActivities(
        **_lead_response(lead).model_dump(),
        activities=[_activity_response(a) for a in activities],
    )
    return resp


@router.put("/leads/{lead_id}", response_model=VacancyLeadResponse)
def update_lead(
    lead_id: str,
    body: VacancyLeadUpdate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        lid = uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead ID")

    lead = db.query(VacancyLead).filter(
        VacancyLead.id == lid,
        VacancyLead.owner_id == current_user.id,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "unit_id" and value:
            try:
                setattr(lead, field, uuid.UUID(value))
            except ValueError:
                pass
        elif field == "property_id" and value:
            try:
                setattr(lead, field, uuid.UUID(value))
            except ValueError:
                pass
        else:
            setattr(lead, field, value)

    db.commit()
    db.refresh(lead)
    return _lead_response(lead)


@router.post("/leads/{lead_id}/activity", response_model=LeadActivityResponse, status_code=201)
def log_activity(
    lead_id: str,
    body: LeadActivityCreate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        svc = VacancyPreventionService(db, current_user.id)
        activity = svc.log_activity(
            lead_id=lead_id,
            activity_type=body.activity_type,
            content=body.content,
            performed_by=current_user.id,
        )
        return _activity_response(activity)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/leads/{lead_id}/convert", response_model=VacancyLeadResponse)
def convert_lead(
    lead_id: str,
    body: ConvertLeadRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        lid = uuid.UUID(lead_id)
        tenant_uuid = uuid.UUID(body.tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID")

    lead = db.query(VacancyLead).filter(
        VacancyLead.id == lid,
        VacancyLead.owner_id == current_user.id,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead.status = "converted"
    lead.converted_tenant_id = tenant_uuid

    # Increment enquiry count on matching syndication
    if lead.unit_id:
        syndication = db.query(ListingSyndication).filter(
            ListingSyndication.unit_id == lead.unit_id,
            ListingSyndication.owner_id == current_user.id,
            ListingSyndication.status == "active",
        ).first()
        if syndication:
            syndication.enquiry_count = (syndication.enquiry_count or 0) + 1

    db.commit()
    db.refresh(lead)
    return _lead_response(lead)


# ═══════════════════════════════════════════════════════════════════════════════
# LISTINGS (SYNDICATIONS)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/listings", response_model=List[ListingSyndicationResponse])
def list_syndications(
    status_filter: Optional[str] = Query(None, alias="status"),
    unit_id: Optional[str] = Query(None),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    q = db.query(ListingSyndication).filter(
        ListingSyndication.owner_id == current_user.id
    )
    if status_filter:
        q = q.filter(ListingSyndication.status == status_filter)
    if unit_id:
        try:
            q = q.filter(ListingSyndication.unit_id == uuid.UUID(unit_id))
        except ValueError:
            pass
    synds = q.order_by(ListingSyndication.created_at.desc()).all()
    return [_syndication_response(s) for s in synds]


@router.post("/listings", response_model=ListingSyndicationResponse, status_code=201)
def create_syndication(
    body: ListingSyndicationCreate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
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

    synd = ListingSyndication(
        id=uuid.uuid4(),
        owner_id=current_user.id,
        unit_id=unit_uuid,
        title=body.title,
        description=body.description,
        monthly_rent=body.monthly_rent,
        bedrooms=body.bedrooms,
        bathrooms=body.bathrooms,
        unit_type=body.unit_type,
        amenities=body.amenities,
        photos=body.photos,
        location_area=body.location_area,
        status="draft",
        view_count=0,
        enquiry_count=0,
        platforms=[],
    )
    db.add(synd)
    db.commit()
    db.refresh(synd)
    return _syndication_response(synd)


@router.put("/listings/{listing_id}", response_model=ListingSyndicationResponse)
def update_syndication(
    listing_id: str,
    body: ListingSyndicationUpdate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        lid = uuid.UUID(listing_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid listing ID")

    synd = db.query(ListingSyndication).filter(
        ListingSyndication.id == lid,
        ListingSyndication.owner_id == current_user.id,
    ).first()
    if not synd:
        raise HTTPException(status_code=404, detail="Listing not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(synd, field, value)

    db.commit()
    db.refresh(synd)
    return _syndication_response(synd)


@router.post("/listings/{listing_id}/publish", response_model=ListingSyndicationResponse)
def publish_syndication(
    listing_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        lid = uuid.UUID(listing_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid listing ID")

    synd = db.query(ListingSyndication).filter(
        ListingSyndication.id == lid,
        ListingSyndication.owner_id == current_user.id,
    ).first()
    if not synd:
        raise HTTPException(status_code=404, detail="Listing not found")

    synd.status = "active"
    synd.published_at = datetime.now(timezone.utc)

    # Check auto_syndicate setting — placeholder only, logs intent
    svc = VacancyPreventionService(db, current_user.id)
    settings = svc.get_or_create_settings()
    if settings.auto_syndicate:
        _log_syndication_intent(listing_id, str(current_user.id), db)

    db.commit()
    db.refresh(synd)
    return _syndication_response(synd)


@router.post("/listings/{listing_id}/pause", response_model=ListingSyndicationResponse)
def pause_syndication(
    listing_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        lid = uuid.UUID(listing_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid listing ID")

    synd = db.query(ListingSyndication).filter(
        ListingSyndication.id == lid,
        ListingSyndication.owner_id == current_user.id,
    ).first()
    if not synd:
        raise HTTPException(status_code=404, detail="Listing not found")

    synd.status = "paused"
    db.commit()
    db.refresh(synd)
    return _syndication_response(synd)


@router.post("/listings/{listing_id}/record-enquiry", response_model=ListingSyndicationResponse)
def record_enquiry(
    listing_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        lid = uuid.UUID(listing_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid listing ID")

    synd = db.query(ListingSyndication).filter(
        ListingSyndication.id == lid,
        ListingSyndication.owner_id == current_user.id,
    ).first()
    if not synd:
        raise HTTPException(status_code=404, detail="Listing not found")

    synd.enquiry_count = (synd.enquiry_count or 0) + 1
    db.commit()
    db.refresh(synd)
    return _syndication_response(synd)


# ═══════════════════════════════════════════════════════════════════════════════
# RENEWAL CAMPAIGNS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/campaigns", response_model=List[RenewalCampaignResponse])
def list_campaigns(
    campaign_status: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    q = db.query(RenewalCampaign).filter(
        RenewalCampaign.owner_id == current_user.id
    )
    if campaign_status:
        q = q.filter(RenewalCampaign.campaign_status == campaign_status)
    if outcome:
        q = q.filter(RenewalCampaign.outcome == outcome)
    campaigns = q.order_by(RenewalCampaign.created_at.desc()).all()
    return [_campaign_response(c, db) for c in campaigns]


@router.post("/campaigns/{campaign_id}/respond", response_model=RenewalCampaignResponse)
def respond_campaign(
    campaign_id: str,
    body: CampaignRespondRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        cid = uuid.UUID(campaign_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid campaign ID")

    campaign = db.query(RenewalCampaign).filter(
        RenewalCampaign.id == cid,
        RenewalCampaign.owner_id == current_user.id,
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign.tenant_response = body.tenant_response
    campaign.response_received_at = datetime.now(timezone.utc)
    campaign.campaign_status = "responded"

    if body.proposed_counter_rent:
        campaign.proposed_rent = body.proposed_counter_rent

    if body.tenant_response == "accepted":
        campaign.campaign_status = "accepted"
        campaign.outcome = "renewed"
    elif body.tenant_response == "declined":
        campaign.campaign_status = "declined"
        campaign.outcome = "vacated"

    db.commit()
    db.refresh(campaign)
    return _campaign_response(campaign, db)


@router.post("/campaigns/trigger", response_model=RenewalCampaignResponse, status_code=201)
def trigger_campaign(
    body: RenewalCampaignCreate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    svc = VacancyPreventionService(db, current_user.id)
    campaign = svc.handle_lease_expiring(
        lease_id=body.lease_id,
        days_before=body.days_before,
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="Lease not found or unit missing")

    # Allow overriding offer details if provided
    if body.offer_type:
        campaign.offer_type = body.offer_type
    if body.incentive_description:
        campaign.incentive_description = body.incentive_description
    if body.proposed_rent:
        campaign.proposed_rent = body.proposed_rent
    db.commit()
    db.refresh(campaign)
    return _campaign_response(campaign, db)


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE STATS + AT RISK
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/pipeline-stats", response_model=PipelineStatsResponse)
def pipeline_stats(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        svc = VacancyPreventionService(db, current_user.id)
        stats = svc.get_pipeline_stats()
        return PipelineStatsResponse(**stats)
    except Exception as e:
        logger.error(f"[vacancy] pipeline_stats failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to compute pipeline stats")


@router.get("/units-at-risk", response_model=List[UnitAtRiskResponse])
def units_at_risk(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        svc = VacancyPreventionService(db, current_user.id)
        items = svc.get_units_at_risk()
        return [UnitAtRiskResponse(**i) for i in items]
    except Exception as e:
        logger.error(f"[vacancy] units_at_risk failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to compute units at risk")


# ═══════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/settings", response_model=VacancyPreventionSettingsResponse)
def get_settings(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    svc = VacancyPreventionService(db, current_user.id)
    s = svc.get_or_create_settings()
    return _settings_response(s)


@router.put("/settings", response_model=VacancyPreventionSettingsResponse)
def update_settings(
    body: VacancyPreventionSettingsUpdate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    svc = VacancyPreventionService(db, current_user.id)
    s = svc.get_or_create_settings()
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(s, field, value)
    db.commit()
    db.refresh(s)
    return _settings_response(s)


# ── Internal helper ───────────────────────────────────────────────────────────

def _log_syndication_intent(listing_id: str, owner_id: str, db: Session) -> None:
    """
    Placeholder — logs syndication intent to automation_actions_log.
    Real platform API integrations are out of scope.
    """
    import uuid as _uuid
    from app.models.automation import AutomationActionLog
    try:
        log = AutomationActionLog(
            id=_uuid.uuid4(),
            execution_id=_uuid.UUID(int=0),
            owner_id=_uuid.UUID(owner_id),
            action_type="syndicate_listing_intent",
            action_payload={"listing_id": listing_id},
            result_status="success",
            result_data={
                "message": (
                    "Syndication intent logged. "
                    "Add your platform URLs in the listing to track syndication."
                )
            },
            executed_at=datetime.now(timezone.utc),
            reversible=False,
        )
        db.add(log)
        db.commit()
    except Exception as exc:
        logger.warning(f"[vacancy] Failed to log syndication intent: {exc}")
        db.rollback()
