"""
Profit Optimization Engine — Pydantic schemas
"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import date, datetime


# ── Financial Snapshots ───────────────────────────────────────────────────────

class SnapshotResponse(BaseModel):
    id: str
    owner_id: str
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    snapshot_period: str
    revenue_gross: float
    revenue_expected: float
    vacancy_loss: float
    maintenance_cost: float
    other_expenses: float
    late_fees_collected: float
    net_operating_income: float
    occupancy_rate: float
    collection_rate: float
    computed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Expenses ──────────────────────────────────────────────────────────────────

class ExpenseCreate(BaseModel):
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    category: str
    description: str
    amount: float = Field(..., gt=0)
    expense_date: date
    vendor_job_id: Optional[str] = None
    receipt_url: Optional[str] = None
    notes: Optional[str] = None


class ExpenseUpdate(BaseModel):
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = Field(None, gt=0)
    expense_date: Optional[date] = None
    receipt_url: Optional[str] = None
    notes: Optional[str] = None


class ExpenseResponse(BaseModel):
    id: str
    owner_id: str
    property_id: Optional[str] = None
    property_name: Optional[str] = None
    unit_id: Optional[str] = None
    unit_number: Optional[str] = None
    category: str
    description: str
    amount: float
    expense_date: date
    vendor_job_id: Optional[str] = None
    receipt_url: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Profit Targets ────────────────────────────────────────────────────────────

class TargetCreate(BaseModel):
    property_id: Optional[str] = None
    target_type: str  # noi/occupancy/collection_rate/yield
    target_value: float = Field(..., gt=0)
    period: str = "monthly"


class TargetUpdate(BaseModel):
    target_value: Optional[float] = Field(None, gt=0)
    period: Optional[str] = None


class TargetResponse(BaseModel):
    id: str
    owner_id: str
    property_id: Optional[str] = None
    property_name: Optional[str] = None
    target_type: str
    target_value: float
    period: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TargetStatusResponse(BaseModel):
    id: str
    target_type: str
    target_value: float
    period: str
    property_id: Optional[str] = None
    property_name: Optional[str] = None
    actual_value: float
    gap: float
    pct_achieved: float
    status: str  # on_track / at_risk / missed


# ── Financial Reports ─────────────────────────────────────────────────────────

class GenerateReportRequest(BaseModel):
    period_str: str  # "YYYY-MM"
    report_type: str = "monthly"


class ReportListResponse(BaseModel):
    id: str
    owner_id: str
    report_period: str
    report_type: str
    status: str
    generated_at: Optional[datetime] = None
    pdf_url: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReportDetailResponse(ReportListResponse):
    data: Optional[Dict[str, Any]] = None


# ── Analytics responses ────────────────────────────────────────────────────────

class PropertyRankingResponse(BaseModel):
    property_id: str
    property_name: str
    unit_count: int
    revenue_gross: float
    maintenance_cost: float
    noi: float
    yield_pct: float
    occupancy_rate: float
    collection_rate: float
    rank: int
    vs_last_month_noi_change_pct: float


class UnitProfitabilityResponse(BaseModel):
    unit_id: str
    unit_number: str
    monthly_rent: float
    revenue_collected: float
    maintenance_cost: float
    noi: float
    occupancy_days: int
    is_profitable: bool
    recommendation: str


class PortfolioPnlResponse(BaseModel):
    months: List[Dict[str, Any]]
    total_revenue_ytd: float
    total_expenses_ytd: float
    total_noi_ytd: float
    avg_occupancy_ytd: float
    avg_collection_rate_ytd: float
    best_month: Optional[str] = None
    worst_month: Optional[str] = None


# ── What-If ───────────────────────────────────────────────────────────────────

class WhatIfRequest(BaseModel):
    scenario_type: str  # rent_increase/fill_vacancy/reduce_maintenance/expense_category_shift
    params: Dict[str, Any]


class WhatIfResponse(BaseModel):
    scenario_type: str
    result: Dict[str, Any]
