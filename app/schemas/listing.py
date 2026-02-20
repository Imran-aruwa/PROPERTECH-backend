"""
Pydantic schemas for Vacancy Listing Syndication feature.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Enum mirrors (string literals, keeps JSON serialisation clean) ─────────────

class ListingStatus(str):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    FILLED = "filled"


# ── Syndication schemas ────────────────────────────────────────────────────────

class SyndicationOut(BaseModel):
    id: uuid.UUID
    listing_id: uuid.UUID
    platform: str
    status: str
    external_url: Optional[str] = None
    share_url: Optional[str] = None
    published_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Lead schemas ───────────────────────────────────────────────────────────────

class LeadCreate(BaseModel):
    """Public-facing lead submission (no auth required)."""
    name: str = Field(..., min_length=2, max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    message: Optional[str] = Field(None, max_length=2000)
    source_platform: Optional[str] = Field(None, max_length=50)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v and "@" not in v:
            raise ValueError("Invalid email address")
        return v

    @field_validator("phone", "email")
    @classmethod
    def at_least_one_contact(cls, v: Optional[str], info: Any) -> Optional[str]:
        return v  # cross-field check done in route


class LeadUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


class LeadOut(BaseModel):
    id: uuid.UUID
    listing_id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    message: Optional[str] = None
    source_platform: Optional[str] = None
    status: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Analytics schemas ──────────────────────────────────────────────────────────

class AnalyticsSummary(BaseModel):
    total_views: int = 0
    total_inquiries: int = 0
    total_shares: int = 0
    days_on_market: Optional[int] = None
    conversion_rate: float = 0.0   # inquiries / views
    views_by_platform: Dict[str, int] = {}
    inquiries_by_platform: Dict[str, int] = {}
    leads_by_status: Dict[str, int] = {}


# ── Listing schemas ────────────────────────────────────────────────────────────

class ListingCreate(BaseModel):
    title: str = Field(..., min_length=5, max_length=255)
    description: Optional[str] = None
    monthly_rent: float = Field(..., ge=0)
    deposit_amount: Optional[float] = Field(None, ge=0)
    available_from: Optional[datetime] = None
    amenities: Optional[List[str]] = []
    photos: Optional[List[str]] = []
    # Optional — triggers auto-population
    property_id: Optional[uuid.UUID] = None
    unit_id: Optional[uuid.UUID] = None


class ListingUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=5, max_length=255)
    description: Optional[str] = None
    monthly_rent: Optional[float] = Field(None, ge=0)
    deposit_amount: Optional[float] = Field(None, ge=0)
    available_from: Optional[datetime] = None
    amenities: Optional[List[str]] = None
    photos: Optional[List[str]] = None


class PublishRequest(BaseModel):
    """Platforms to syndicate to when publishing."""
    platforms: List[str] = Field(
        default=["direct_link"],
        description="List of platform keys to syndicate to",
    )


class SyndicateRequest(BaseModel):
    platform: str


class AutoPopulateResponse(BaseModel):
    title: str
    description: str
    monthly_rent: float
    deposit_amount: float
    available_from: Optional[datetime]
    amenities: List[str]
    photos: List[str]
    property_name: Optional[str] = None
    unit_number: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    area: Optional[str] = None


class ListingOut(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    property_id: Optional[uuid.UUID] = None
    unit_id: Optional[uuid.UUID] = None
    title: str
    description: Optional[str] = None
    monthly_rent: float
    deposit_amount: Optional[float] = None
    available_from: Optional[datetime] = None
    amenities: List[str] = []
    photos: List[str] = []
    status: str
    slug: str
    view_count: int
    published_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # Computed / joined
    syndications: List[SyndicationOut] = []
    lead_count: int = 0
    days_on_market: Optional[int] = None
    # Property/unit info (denormalised for convenience)
    property_name: Optional[str] = None
    unit_number: Optional[str] = None

    class Config:
        from_attributes = True


class PublicListingOut(BaseModel):
    """Listing response for public (unauthenticated) pages."""
    id: uuid.UUID
    title: str
    description: Optional[str] = None
    monthly_rent: float
    deposit_amount: Optional[float] = None
    available_from: Optional[datetime] = None
    amenities: List[str] = []
    photos: List[str] = []
    slug: str
    view_count: int
    published_at: Optional[datetime] = None
    # Denormalised (no sensitive owner data)
    property_name: Optional[str] = None
    unit_number: Optional[str] = None
    area: Optional[str] = None
    city: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None

    class Config:
        from_attributes = True


class ListingListResponse(BaseModel):
    listings: List[ListingOut]
    total: int
    active_count: int
    draft_count: int
    filled_this_month: int
    avg_days_on_market: Optional[float] = None
    total_leads_this_month: int = 0
