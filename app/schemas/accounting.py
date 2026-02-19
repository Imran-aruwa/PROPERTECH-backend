"""
Accounting + KRA Tax System Schemas
Pydantic v2 models for the accounting API.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator


# ─────────────────── Entry ───────────────────

class AccountingEntryCreate(BaseModel):
    entry_type: str               # "income" | "expense"
    category: str
    amount: float
    description: Optional[str] = None
    reference_number: Optional[str] = None
    entry_date: str               # "YYYY-MM-DD"
    tax_period: Optional[str] = None   # "YYYY-MM" — auto-derived if omitted
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    tenant_id: Optional[str] = None
    is_reconciled: bool = False
    receipt_url: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def _positive_amount(cls, v: float) -> float:
        if v < 0:
            raise ValueError("amount must be non-negative")
        return v

    @field_validator("entry_date", mode="before")
    @classmethod
    def _normalise_date(cls, v: Any) -> str:
        if isinstance(v, (date, datetime)):
            return v.strftime("%Y-%m-%d")
        return str(v)


class AccountingEntryUpdate(BaseModel):
    entry_type: Optional[str] = None
    category: Optional[str] = None
    amount: Optional[float] = None
    description: Optional[str] = None
    reference_number: Optional[str] = None
    entry_date: Optional[str] = None
    tax_period: Optional[str] = None
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    tenant_id: Optional[str] = None
    is_reconciled: Optional[bool] = None
    receipt_url: Optional[str] = None


class AccountingEntryOut(BaseModel):
    id: str
    owner_id: str
    property_id: Optional[str]
    unit_id: Optional[str]
    tenant_id: Optional[str]
    entry_type: str
    category: str
    amount: float
    description: Optional[str]
    reference_number: Optional[str]
    entry_date: str
    tax_period: Optional[str]
    is_reconciled: bool
    receipt_url: Optional[str]
    synced_from_payment_id: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ─────────────────── Bulk import ───────────────────

class BulkEntryRow(BaseModel):
    entry_type: str
    category: str
    amount: float
    description: Optional[str] = None
    reference_number: Optional[str] = None
    entry_date: str
    property_id: Optional[str] = None
    tenant_id: Optional[str] = None


class BulkImportRequest(BaseModel):
    entries: List[BulkEntryRow]


# ─────────────────── Tax Record ───────────────────

class TaxRecordCreate(BaseModel):
    tax_year: int
    tax_period: str              # "YYYY-MM" for monthly, "annual" for full year
    gross_rental_income: float
    allowable_deductions: float = 0.0
    net_taxable_income: float
    tax_liability: float
    tax_rate_applied: float
    landlord_type: str = "resident_individual"
    kra_pin: Optional[str] = None
    above_threshold: bool = False
    status: str = "draft"
    notes: Optional[str] = None


class TaxRecordUpdate(BaseModel):
    status: Optional[str] = None
    kra_pin: Optional[str] = None
    notes: Optional[str] = None
    filed_at: Optional[str] = None


class TaxRecordOut(BaseModel):
    id: str
    owner_id: str
    tax_year: int
    tax_period: str
    gross_rental_income: float
    allowable_deductions: float
    net_taxable_income: float
    tax_liability: float
    tax_rate_applied: float
    landlord_type: str
    kra_pin: Optional[str]
    above_threshold: bool
    status: str
    filed_at: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ─────────────────── Withholding Tax ───────────────────

class WithholdingEntryCreate(BaseModel):
    tenant_id: Optional[str] = None
    property_id: Optional[str] = None
    amount_paid: float
    withholding_rate: float = 10.0
    period: str                   # "YYYY-MM"
    certificate_number: Optional[str] = None
    certificate_url: Optional[str] = None
    tenant_name: Optional[str] = None
    tenant_kra_pin: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("withholding_rate")
    @classmethod
    def _valid_rate(cls, v: float) -> float:
        if not (0 < v <= 100):
            raise ValueError("withholding_rate must be between 0 and 100")
        return v


class WithholdingEntryOut(BaseModel):
    id: str
    owner_id: str
    tenant_id: Optional[str]
    property_id: Optional[str]
    amount_paid: float
    withholding_rate: float
    withholding_amount: float
    period: str
    certificate_number: Optional[str]
    certificate_url: Optional[str]
    tenant_name: Optional[str]
    tenant_kra_pin: Optional[str]
    notes: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


# ─────────────────── Report Schemas ───────────────────

class PnLReport(BaseModel):
    period: str
    property_id: Optional[str]
    gross_income: float
    total_expenses: float
    net_profit: float
    net_margin_pct: float
    income_breakdown: Dict[str, float]
    expense_breakdown: Dict[str, float]


class CashFlowMonth(BaseModel):
    month: str        # "YYYY-MM"
    income: float
    expenses: float
    net: float


class PropertyPerformance(BaseModel):
    property_id: str
    property_name: str
    gross_income: float
    total_expenses: float
    net_profit: float
    occupancy_rate: float
    gross_yield_pct: Optional[float]


class ExpenseBreakdownItem(BaseModel):
    category: str
    amount: float
    pct_of_income: float


class TaxSummaryResponse(BaseModel):
    period: str
    landlord_type: str
    gross_rental_income: float
    allowable_deductions: float
    net_taxable_income: float
    tax_rate_applied: float
    tax_liability: float
    above_mri_threshold: bool
    calculation_method: str
    breakdown: Dict[str, Any]
    mri_threshold: float
