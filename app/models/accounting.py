"""
Advanced Accounting + KRA Tax System Models
Tables: accounting_entries, tax_records, withholding_tax_entries
"""
from datetime import datetime
from enum import Enum
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Boolean,
    ForeignKey, Text, Enum as SQLEnum, Uuid, Index, Date,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import uuid

from app.db.base import Base


# ─────────────────── Entry Type ───────────────────

class EntryType(str, Enum):
    INCOME = "income"
    EXPENSE = "expense"


# ─────────────────── Entry Category ───────────────────

class EntryCategory(str, Enum):
    # ── Income ──
    RENTAL_INCOME = "rental_income"
    DEPOSIT_RECEIVED = "deposit_received"
    LATE_FEE = "late_fee"
    SERVICE_CHARGE = "service_charge"
    OTHER_INCOME = "other_income"

    # ── Expenses (KRA allowable deductions) ──
    MORTGAGE_INTEREST = "mortgage_interest"
    REPAIRS_MAINTENANCE = "repairs_maintenance"
    PROPERTY_MANAGEMENT_FEES = "property_management_fees"
    INSURANCE = "insurance"
    LAND_RATES = "land_rates"
    GROUND_RENT = "ground_rent"
    LEGAL_FEES = "legal_fees"
    ADVERTISING = "advertising"
    DEPRECIATION = "depreciation"
    UTILITIES = "utilities"
    CARETAKER_SALARY = "caretaker_salary"
    SECURITY = "security"
    OTHER = "other"


# ─────────────────── Tax Record Status ───────────────────

class TaxRecordStatus(str, Enum):
    DRAFT = "draft"
    FILED = "filed"
    PAID = "paid"


# ─────────────────── Accounting Entry ───────────────────

class AccountingEntry(Base):
    """Double-entry style financial record for all property income and expenses."""
    __tablename__ = "accounting_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owner (auth-protected)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False, index=True
    )

    # Linked entities (nullable — owners may not always link to a specific unit/tenant)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=True, index=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=True)

    # Entry details
    entry_type: Mapped[EntryType] = mapped_column(
        SQLEnum(EntryType), nullable=False, index=True
    )
    category: Mapped[EntryCategory] = mapped_column(
        SQLEnum(EntryCategory), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)  # KES
    description: Mapped[str] = mapped_column(String(500), nullable=True)
    reference_number: Mapped[str] = mapped_column(String(100), nullable=True)

    # Dates
    entry_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    tax_period: Mapped[str] = mapped_column(String(7), nullable=True)  # "YYYY-MM"

    # Reconciliation
    is_reconciled: Mapped[bool] = mapped_column(Boolean, default=False)
    receipt_url: Mapped[str] = mapped_column(String(1000), nullable=True)

    # Idempotent payment sync — stores the payments.id that sourced this entry
    synced_from_payment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=True, unique=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_accounting_owner_period", "owner_id", "tax_period"),
        Index("idx_accounting_owner_type", "owner_id", "entry_type"),
        Index("idx_accounting_owner_property", "owner_id", "property_id"),
    )


# ─────────────────── Tax Record ───────────────────

class TaxRecord(Base):
    """KRA rental income tax computation record (monthly or annual)."""
    __tablename__ = "tax_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False, index=True
    )

    # Period
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_period: Mapped[str] = mapped_column(String(10), nullable=False)  # "YYYY-MM" or "annual"

    # Financials
    gross_rental_income: Mapped[float] = mapped_column(Float, nullable=False)
    allowable_deductions: Mapped[float] = mapped_column(Float, default=0.0)
    net_taxable_income: Mapped[float] = mapped_column(Float, nullable=False)
    tax_liability: Mapped[float] = mapped_column(Float, nullable=False)
    tax_rate_applied: Mapped[float] = mapped_column(Float, nullable=False)

    # Landlord profile
    landlord_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="resident_individual"
    )  # resident_individual | non_resident | corporate
    kra_pin: Mapped[str] = mapped_column(String(30), nullable=True)
    above_threshold: Mapped[bool] = mapped_column(Boolean, default=False)

    # Filing
    status: Mapped[TaxRecordStatus] = mapped_column(
        SQLEnum(TaxRecordStatus), default=TaxRecordStatus.DRAFT, nullable=False
    )
    filed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_tax_records_owner_year", "owner_id", "tax_year"),
    )


# ─────────────────── Withholding Tax Entry ───────────────────

class WithholdingTaxEntry(Base):
    """
    Records cases where a corporate tenant deducts withholding tax
    before remitting rent (they become tax agents per KRA rules).
    Default withholding rate: 10% for resident corporate tenants.
    """
    __tablename__ = "withholding_tax_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=True)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=True)

    # Amounts
    amount_paid: Mapped[float] = mapped_column(Float, nullable=False)  # net received by landlord
    withholding_rate: Mapped[float] = mapped_column(Float, default=10.0)  # %
    withholding_amount: Mapped[float] = mapped_column(Float, nullable=False)  # deducted amount

    # Period and certificate
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # "YYYY-MM"
    certificate_number: Mapped[str] = mapped_column(String(100), nullable=True)
    certificate_url: Mapped[str] = mapped_column(String(1000), nullable=True)

    # Tenant info (denormalised for reporting)
    tenant_name: Mapped[str] = mapped_column(String(255), nullable=True)
    tenant_kra_pin: Mapped[str] = mapped_column(String(30), nullable=True)

    notes: Mapped[str] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_withholding_owner_period", "owner_id", "period"),
    )
