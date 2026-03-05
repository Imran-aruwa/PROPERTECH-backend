"""
Vacancy Prevention Engine — Pydantic schemas
"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import date, datetime


# ── Leads ─────────────────────────────────────────────────────────────────────

class VacancyLeadCreate(BaseModel):
    lead_name: str
    lead_phone: str
    lead_email: Optional[str] = None
    source: str = "manual"
    unit_id: Optional[str] = None
    property_id: Optional[str] = None
    preferred_unit_type: Optional[str] = None
    preferred_move_in: Optional[date] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    notes: Optional[str] = None


class VacancyLeadUpdate(BaseModel):
    status: Optional[str] = None
    unit_id: Optional[str] = None
    property_id: Optional[str] = None
    notes: Optional[str] = None
    follow_up_due_at: Optional[datetime] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    preferred_unit_type: Optional[str] = None
    preferred_move_in: Optional[date] = None


class VacancyLeadResponse(BaseModel):
    id: str
    owner_id: str
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    lead_name: str
    lead_phone: str
    lead_email: Optional[str] = None
    source: str
    status: str
    preferred_unit_type: Optional[str] = None
    preferred_move_in: Optional[date] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    notes: Optional[str] = None
    last_contacted_at: Optional[datetime] = None
    follow_up_due_at: Optional[datetime] = None
    converted_tenant_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeadActivityCreate(BaseModel):
    activity_type: str  # note/call/sms/email/whatsapp/viewing/status_change
    content: str


class LeadActivityResponse(BaseModel):
    id: str
    lead_id: str
    owner_id: str
    activity_type: str
    content: str
    performed_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class LeadWithActivities(VacancyLeadResponse):
    activities: List[LeadActivityResponse] = []


class ConvertLeadRequest(BaseModel):
    tenant_id: str


# ── Listing Syndications ──────────────────────────────────────────────────────

class ListingSyndicationCreate(BaseModel):
    unit_id: str
    title: str
    description: Optional[str] = None
    monthly_rent: float = Field(..., gt=0)
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    unit_type: str
    amenities: List[str] = []
    photos: List[str] = []
    location_area: Optional[str] = None


class ListingSyndicationUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    monthly_rent: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    unit_type: Optional[str] = None
    amenities: Optional[List[str]] = None
    photos: Optional[List[str]] = None
    location_area: Optional[str] = None


class ListingSyndicationResponse(BaseModel):
    id: str
    owner_id: str
    unit_id: str
    listing_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    monthly_rent: float
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    unit_type: str
    amenities: List[str] = []
    photos: List[str] = []
    location_area: Optional[str] = None
    status: str
    view_count: int
    enquiry_count: int
    platforms: List[Dict[str, Any]] = []
    published_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Renewal Campaigns ─────────────────────────────────────────────────────────

class RenewalCampaignCreate(BaseModel):
    lease_id: str
    days_before: int = Field(..., ge=1)
    offer_type: str = "standard"
    incentive_description: Optional[str] = None
    proposed_rent: Optional[float] = None


class CampaignRespondRequest(BaseModel):
    tenant_response: str  # accepted/declined/negotiating/no_response
    proposed_counter_rent: Optional[float] = None


class RenewalCampaignResponse(BaseModel):
    id: str
    owner_id: str
    lease_id: str
    tenant_id: Optional[str] = None
    unit_id: str
    tenant_name: Optional[str] = None
    unit_number: Optional[str] = None
    property_name: Optional[str] = None
    days_until_expiry: Optional[int] = None
    campaign_status: str
    trigger_days_before_expiry: int
    offer_type: str
    incentive_description: Optional[str] = None
    proposed_rent: Optional[float] = None
    current_rent: float
    tenant_response: Optional[str] = None
    response_received_at: Optional[datetime] = None
    follow_up_count: int
    last_follow_up_at: Optional[datetime] = None
    outcome: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Settings ──────────────────────────────────────────────────────────────────

class VacancyPreventionSettingsResponse(BaseModel):
    id: str
    owner_id: str
    is_enabled: bool
    auto_create_listing: bool
    auto_syndicate: bool
    renewal_campaign_days: List[int] = [60, 30, 7]
    lead_follow_up_hours: int
    auto_sms_new_leads: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VacancyPreventionSettingsUpdate(BaseModel):
    is_enabled: Optional[bool] = None
    auto_create_listing: Optional[bool] = None
    auto_syndicate: Optional[bool] = None
    renewal_campaign_days: Optional[List[int]] = None
    lead_follow_up_hours: Optional[int] = Field(None, ge=1, le=168)
    auto_sms_new_leads: Optional[bool] = None


# ── Pipeline Stats + At-Risk ──────────────────────────────────────────────────

class PipelineStatsResponse(BaseModel):
    total_active_leads: int
    leads_by_status: Dict[str, int]
    overdue_follow_ups: int
    avg_days_lead_to_conversion: float
    active_listings: int
    total_listing_views: int
    total_listing_enquiries: int
    active_renewal_campaigns: int
    renewals_at_risk: int


class UnitAtRiskResponse(BaseModel):
    unit_id: str
    unit_number: str
    property_name: str
    tenant_name: str
    expiry_date: str
    days_until_expiry: int
    has_active_campaign: bool
    campaign_status: Optional[str] = None
