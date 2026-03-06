"""
Profit Optimization Engine Models
Tables: financial_snapshots, expense_records, profit_targets, financial_reports
"""
from datetime import datetime
from sqlalchemy import (
    Column, String, ForeignKey, DateTime, Boolean, Text, Uuid,
    Numeric, Date, Integer, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
import uuid

from app.db.base import Base


def _json_col(**kwargs):
    return Column(JSONB().with_variant(JSON(), "sqlite"), **kwargs)


class FinancialSnapshot(Base):
    __tablename__ = "financial_snapshots"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=True, index=True)
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=True)

    # "YYYY-MM" — e.g. "2025-01"
    snapshot_period = Column(String(7), nullable=False, index=True)

    # Revenue
    revenue_gross = Column(Numeric(14, 2), default=0, nullable=False)
    revenue_expected = Column(Numeric(14, 2), default=0, nullable=False)
    vacancy_loss = Column(Numeric(14, 2), default=0, nullable=False)

    # Costs
    maintenance_cost = Column(Numeric(14, 2), default=0, nullable=False)
    other_expenses = Column(Numeric(14, 2), default=0, nullable=False)
    late_fees_collected = Column(Numeric(14, 2), default=0, nullable=False)

    # Bottom line
    net_operating_income = Column(Numeric(14, 2), default=0, nullable=False)

    # Rates (%)
    occupancy_rate = Column(Numeric(5, 2), default=0, nullable=False)
    collection_rate = Column(Numeric(5, 2), default=0, nullable=False)

    computed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Ensure one snapshot per owner+period+property+unit
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "snapshot_period", "property_id", "unit_id",
            name="uq_financial_snapshot",
        ),
    )


class ExpenseRecord(Base):
    __tablename__ = "expense_records"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=True, index=True)
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=True)

    # maintenance/utilities/insurance/tax/management_fee/loan_repayment/other
    category = Column(String(50), nullable=False, index=True)
    description = Column(String(500), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    expense_date = Column(Date, nullable=False, index=True)

    # Optional link to a VendorJob if this is a maintenance expense
    vendor_job_id = Column(Uuid, ForeignKey("vendor_jobs.id"), nullable=True)
    receipt_url = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)


class ProfitTarget(Base):
    __tablename__ = "profit_targets"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=True)

    # noi / occupancy / collection_rate / yield
    target_type = Column(String(30), nullable=False)
    target_value = Column(Numeric(10, 2), nullable=False)
    # monthly / annual
    period = Column(String(10), nullable=False, default="monthly")

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)


class FinancialReport(Base):
    __tablename__ = "financial_reports"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)

    # "YYYY-MM"
    report_period = Column(String(7), nullable=False)
    # monthly / quarterly / annual
    report_type = Column(String(20), nullable=False, default="monthly")
    # generating / complete / failed
    status = Column(String(20), nullable=False, default="generating")

    generated_at = Column(DateTime(timezone=True), nullable=True)
    data = _json_col(nullable=True)      # full report payload
    pdf_url = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
