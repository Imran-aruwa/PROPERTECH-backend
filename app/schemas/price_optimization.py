"""
Price Optimization Engine — Pydantic schemas
"""
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import date, datetime
from decimal import Decimal


# ── Rent Reviews ─────────────────────────────────────────────────────────────

class RentReviewBase(BaseModel):
    unit_id: str
    trigger: str
    current_rent: float
    recommended_rent: float
    min_rent: float
    max_rent: float
    confidence_score: int
    reasoning: List[str] = []
    market_data_snapshot: Optional[Dict[str, Any]] = None
    status: str = "pending"


class RentReviewResponse(BaseModel):
    id: str
    owner_id: str
    unit_id: str
    property_id: str
    unit_number: Optional[str] = None
    property_name: Optional[str] = None
    trigger: str
    current_rent: float
    recommended_rent: float
    min_rent: float
    max_rent: float
    confidence_score: int
    reasoning: List[str] = []
    market_data_snapshot: Optional[Dict[str, Any]] = None
    status: str
    accepted_rent: Optional[float] = None
    reviewed_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AcceptReviewRequest(BaseModel):
    accepted_rent: float = Field(..., gt=0)


class GenerateReviewRequest(BaseModel):
    unit_id: str


# ── Market Comparables ────────────────────────────────────────────────────────

class MarketComparableCreate(BaseModel):
    unit_type: str
    bedrooms: Optional[int] = None
    location_area: str
    asking_rent: float = Field(..., gt=0)
    actual_rent: Optional[float] = None
    vacancy_days: Optional[int] = None
    source: str = "manual"
    data_date: date
    notes: Optional[str] = None


class MarketComparableResponse(BaseModel):
    id: str
    owner_id: str
    property_id: Optional[str] = None
    unit_type: str
    bedrooms: Optional[int] = None
    location_area: str
    asking_rent: float
    actual_rent: Optional[float] = None
    vacancy_days: Optional[int] = None
    source: str
    data_date: date
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Settings ──────────────────────────────────────────────────────────────────

class PriceOptimizationSettingsResponse(BaseModel):
    id: str
    owner_id: str
    is_enabled: bool
    auto_apply: bool
    max_increase_pct: float
    max_decrease_pct: float
    target_vacancy_days: int
    min_rent_floor: Optional[float] = None
    comparable_radius_km: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PriceOptimizationSettingsUpdate(BaseModel):
    is_enabled: Optional[bool] = None
    auto_apply: Optional[bool] = None
    max_increase_pct: Optional[float] = Field(None, ge=0, le=50)
    max_decrease_pct: Optional[float] = Field(None, ge=0, le=50)
    target_vacancy_days: Optional[int] = Field(None, ge=1, le=365)
    min_rent_floor: Optional[float] = None
    comparable_radius_km: Optional[float] = Field(None, ge=0.1, le=100)


# ── Vacancy History ───────────────────────────────────────────────────────────

class VacancyHistoryResponse(BaseModel):
    id: str
    unit_id: str
    owner_id: str
    unit_number: Optional[str] = None
    property_name: Optional[str] = None
    vacant_from: datetime
    vacant_until: Optional[datetime] = None
    days_vacant: Optional[int] = None
    rent_at_vacancy: float
    rent_when_filled: Optional[float] = None
    price_changes_count: int
    filled_by_tenant_id: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Portfolio Health ──────────────────────────────────────────────────────────

class UnitToReview(BaseModel):
    unit_id: str
    unit_number: str
    property_name: str
    days_vacant: int
    current_rent: float


class PortfolioHealthResponse(BaseModel):
    total_units: int
    occupied_count: int
    vacant_count: int
    occupancy_rate: float
    units_with_pending_review: int
    avg_days_to_fill: float
    estimated_monthly_revenue_loss: float
    top_3_units_to_review: List[UnitToReview] = []
