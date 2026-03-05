"""
Vendor & Maintenance Intelligence Engine Models
Tables: vendors, vendor_jobs, maintenance_schedules, maintenance_cost_budgets
"""
from datetime import datetime
from sqlalchemy import (
    Column, String, ForeignKey, DateTime, Integer, Boolean, Text, Uuid,
    Numeric, Date,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
import uuid

from app.db.base import Base


def _json_col(**kwargs):
    return Column(JSONB().with_variant(JSON(), "sqlite"), **kwargs)


class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    # plumbing/electrical/carpentry/painting/cleaning/security/hvac/general/other
    category = Column(String(50), nullable=False, index=True)
    phone = Column(String(50), nullable=False)
    email = Column(String(255), nullable=True)
    location_area = Column(String(200), nullable=True)

    # Computed metrics
    rating = Column(Numeric(3, 2), nullable=True)          # 1.00–5.00, avg of job ratings
    total_jobs = Column(Integer, default=0, nullable=False)
    completed_jobs = Column(Integer, default=0, nullable=False)
    avg_response_hours = Column(Numeric(6, 2), nullable=True)
    avg_completion_days = Column(Numeric(6, 2), nullable=True)
    total_paid = Column(Numeric(14, 2), default=0, nullable=False)

    is_preferred = Column(Boolean, default=False, nullable=False)
    is_blacklisted = Column(Boolean, default=False, nullable=False)
    blacklist_reason = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)


class VendorJob(Base):
    __tablename__ = "vendor_jobs"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    vendor_id = Column(Uuid, ForeignKey("vendors.id"), nullable=False, index=True)
    maintenance_request_id = Column(
        Uuid, ForeignKey("maintenance_requests.id"), nullable=True, index=True
    )
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=False)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=False)

    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=False)
    # low/normal/urgent/emergency
    priority = Column(String(20), nullable=False, default="normal")
    # assigned/in_progress/completed/cancelled/disputed
    status = Column(String(20), nullable=False, default="assigned", index=True)

    quoted_amount = Column(Numeric(12, 2), nullable=True)
    final_amount = Column(Numeric(12, 2), nullable=True)
    paid = Column(Boolean, default=False, nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    payment_method = Column(String(50), nullable=True)

    assigned_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    due_date = Column(Date, nullable=True)

    owner_rating = Column(Integer, nullable=True)   # 1–5
    owner_review = Column(Text, nullable=True)
    rated_at = Column(DateTime(timezone=True), nullable=True)

    photos_before = _json_col(nullable=True)   # array of URLs
    photos_after = _json_col(nullable=True)    # array of URLs
    notes = Column(Text, nullable=True)

    # FK to schedule that generated this job (optional)
    schedule_id = Column(Uuid, ForeignKey("maintenance_schedules.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)


class MaintenanceSchedule(Base):
    __tablename__ = "maintenance_schedules"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=True, index=True)
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=True)

    title = Column(String(500), nullable=False)
    category = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    # monthly/quarterly/biannual/annual/one_time
    frequency = Column(String(20), nullable=False)

    next_due = Column(Date, nullable=False, index=True)
    last_completed = Column(Date, nullable=True)
    estimated_cost = Column(Numeric(12, 2), nullable=True)
    preferred_vendor_id = Column(Uuid, ForeignKey("vendors.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    auto_create_job = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)


class MaintenanceCostBudget(Base):
    __tablename__ = "maintenance_cost_budgets"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=True, index=True)

    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=True)   # null = annual budget

    budget_amount = Column(Numeric(14, 2), nullable=False)
    actual_amount = Column(Numeric(14, 2), default=0, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)
