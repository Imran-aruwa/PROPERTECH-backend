"""
Vendor & Maintenance Intelligence Engine — Pydantic schemas
"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import date, datetime


# ── Vendors ───────────────────────────────────────────────────────────────────

class VendorCreate(BaseModel):
    name: str
    category: str
    phone: str
    email: Optional[str] = None
    location_area: Optional[str] = None
    notes: Optional[str] = None
    is_preferred: bool = False


class VendorUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    location_area: Optional[str] = None
    notes: Optional[str] = None
    is_preferred: Optional[bool] = None


class VendorResponse(BaseModel):
    id: str
    owner_id: str
    name: str
    category: str
    phone: str
    email: Optional[str] = None
    location_area: Optional[str] = None
    rating: Optional[float] = None
    total_jobs: int
    completed_jobs: int
    avg_response_hours: Optional[float] = None
    avg_completion_days: Optional[float] = None
    total_paid: float
    is_preferred: bool
    is_blacklisted: bool
    blacklist_reason: Optional[str] = None
    notes: Optional[str] = None
    score: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BlacklistRequest(BaseModel):
    reason: str


class ScorecardResponse(BaseModel):
    vendor_id: str
    name: str
    total_jobs: int
    completed_jobs: int
    cancelled_jobs: int
    avg_response_hours: Optional[float]
    avg_completion_days: Optional[float]
    on_time_rate: float
    avg_rating: Optional[float]
    total_paid: float
    jobs_by_category: Dict[str, int]
    jobs_by_property: Dict[str, int]
    recent_reviews: List[Dict[str, Any]]


# ── Vendor Jobs ───────────────────────────────────────────────────────────────

class VendorJobCreate(BaseModel):
    vendor_id: str
    unit_id: str
    title: str
    description: Optional[str] = None
    category: str
    priority: str = "normal"
    quoted_amount: Optional[float] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None
    maintenance_request_id: Optional[str] = None


class AssignJobRequest(BaseModel):
    vendor_id: str
    quoted_amount: Optional[float] = None
    due_date: Optional[date] = None


class CompleteJobRequest(BaseModel):
    final_amount: float = Field(..., gt=0)
    photos_after: List[str] = []


class RateJobRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    review: Optional[str] = None


class MarkPaidRequest(BaseModel):
    payment_method: str = "cash"


class VendorJobUpdate(BaseModel):
    quoted_amount: Optional[float] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None


class VendorJobResponse(BaseModel):
    id: str
    owner_id: str
    vendor_id: str
    vendor_name: Optional[str] = None
    vendor_phone: Optional[str] = None
    vendor_rating: Optional[float] = None
    maintenance_request_id: Optional[str] = None
    unit_id: str
    unit_number: Optional[str] = None
    property_id: str
    property_name: Optional[str] = None
    title: str
    description: Optional[str] = None
    category: str
    priority: str
    status: str
    quoted_amount: Optional[float] = None
    final_amount: Optional[float] = None
    paid: bool
    paid_at: Optional[datetime] = None
    payment_method: Optional[str] = None
    assigned_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    due_date: Optional[date] = None
    owner_rating: Optional[int] = None
    owner_review: Optional[str] = None
    rated_at: Optional[datetime] = None
    photos_before: List[str] = []
    photos_after: List[str] = []
    notes: Optional[str] = None
    schedule_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Maintenance Schedules ─────────────────────────────────────────────────────

class MaintenanceScheduleCreate(BaseModel):
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    title: str
    category: str
    description: Optional[str] = None
    frequency: str
    next_due: date
    estimated_cost: Optional[float] = None
    preferred_vendor_id: Optional[str] = None
    auto_create_job: bool = False


class MaintenanceScheduleUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    frequency: Optional[str] = None
    next_due: Optional[date] = None
    estimated_cost: Optional[float] = None
    preferred_vendor_id: Optional[str] = None
    is_active: Optional[bool] = None
    auto_create_job: Optional[bool] = None


class MaintenanceScheduleResponse(BaseModel):
    id: str
    owner_id: str
    property_id: Optional[str] = None
    property_name: Optional[str] = None
    unit_id: Optional[str] = None
    unit_number: Optional[str] = None
    title: str
    category: str
    description: Optional[str] = None
    frequency: str
    next_due: date
    last_completed: Optional[date] = None
    estimated_cost: Optional[float] = None
    preferred_vendor_id: Optional[str] = None
    preferred_vendor_name: Optional[str] = None
    is_active: bool
    auto_create_job: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Budgets ───────────────────────────────────────────────────────────────────

class BudgetCreate(BaseModel):
    property_id: Optional[str] = None
    year: int = Field(..., ge=2020, le=2099)
    month: Optional[int] = Field(None, ge=1, le=12)
    budget_amount: float = Field(..., gt=0)


class BudgetUpdate(BaseModel):
    budget_amount: float = Field(..., gt=0)


class BudgetResponse(BaseModel):
    id: str
    owner_id: str
    property_id: Optional[str] = None
    property_name: Optional[str] = None
    year: int
    month: Optional[int] = None
    budget_amount: float
    actual_amount: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Analytics ─────────────────────────────────────────────────────────────────

class CostAnalyticsResponse(BaseModel):
    total_spend: float
    spend_by_category: Dict[str, float]
    spend_by_property: Dict[str, float]
    spend_by_vendor: List[Dict[str, Any]]
    avg_monthly_spend: float
    most_expensive_month: str
    budget_vs_actual: List[Dict[str, Any]]


class AnalyticsSummaryResponse(BaseModel):
    total_vendors: int
    preferred_count: int
    blacklisted_count: int
    active_jobs_count: int
    jobs_completed_this_month: int
    total_spend_this_month: float
    total_spend_this_year: float
    budget_utilisation_pct: float
