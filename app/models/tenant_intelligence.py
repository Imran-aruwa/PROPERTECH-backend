"""
Tenant Behavioral Intelligence Models
Stores computed tenant health profiles, events, references, and portfolio risk summaries.
"""
from datetime import datetime, date
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Date, Text, Boolean,
    Uuid, ForeignKey, Numeric, UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
import uuid

from app.db.base import Base


class TenantProfile(Base):
    """
    Computed health profile for a tenant-owner pair.
    One row per (tenant_id, owner_id) pair. Upserted by compute_profile().
    """
    __tablename__ = "tenant_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "owner_id", name="uq_tenant_profile_tenant_owner"),
        Index("idx_tenant_profiles_tenant", "tenant_id"),
        Index("idx_tenant_profiles_owner", "owner_id"),
        Index("idx_tenant_profiles_risk", "owner_id", "risk_level"),
        Index("idx_tenant_profiles_score", "owner_id", "health_score"),
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    owner_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    unit_id = Column(Uuid, ForeignKey("units.id", ondelete="SET NULL"), nullable=True)
    property_id = Column(Uuid, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)

    # Composite health score (0-100) and grade (A+ to F)
    health_score = Column(Integer, nullable=False, default=0)
    health_grade = Column(String(2), nullable=True)  # A+, A, B+, B, C, D, F

    # Component scores (0-100 each)
    payment_score = Column(Integer, nullable=False, default=0)
    maintenance_score = Column(Integer, nullable=False, default=0)
    compliance_score = Column(Integer, nullable=False, default=0)
    communication_score = Column(Integer, nullable=False, default=0)

    # Risk classification
    risk_level = Column(String(20), nullable=False, default="medium")  # low/medium/high/critical
    risk_flags = Column(JSONB, nullable=False, default=list)  # list of flag strings

    # AI-generated summary
    profile_summary = Column(Text, nullable=True)
    last_computed_at = Column(DateTime(timezone=True), nullable=True)

    # Payment statistics
    total_payments_made = Column(Integer, nullable=False, default=0)
    total_payments_on_time = Column(Integer, nullable=False, default=0)
    total_payments_late = Column(Integer, nullable=False, default=0)
    total_payments_missed = Column(Integer, nullable=False, default=0)
    avg_days_late = Column(Numeric(5, 2), nullable=False, default=0)

    # Maintenance statistics
    total_maintenance_requests = Column(Integer, nullable=False, default=0)
    maintenance_nuisance_score = Column(Integer, nullable=False, default=0)  # repeated minor requests

    # Compliance statistics
    lease_violations = Column(Integer, nullable=False, default=0)
    inspection_issues_caused = Column(Integer, nullable=False, default=0)

    # Tenancy duration
    months_tenanted = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TenantEvent(Base):
    """
    Individual behavioral events that affect a tenant's profile score.
    Immutable audit log — never update, only append.
    """
    __tablename__ = "tenant_events"
    __table_args__ = (
        Index("idx_tenant_events_tenant", "tenant_id"),
        Index("idx_tenant_events_owner", "owner_id"),
        Index("idx_tenant_events_type", "tenant_id", "event_type"),
        Index("idx_tenant_events_date", "tenant_id", "event_date"),
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    owner_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Event classification
    event_type = Column(String(50), nullable=False)  # e.g. payment_on_time, late_payment, maintenance_request
    event_date = Column(Date, nullable=False)
    event_data = Column(JSONB, nullable=True)  # arbitrary context dict

    # Scoring impact: positive = good, negative = bad
    impact_score = Column(Integer, nullable=False, default=0)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class TenantReference(Base):
    """
    Reference/recommendation written by an owner about a tenant after tenancy.
    Can be made public to share with prospective landlords (Tenant Passport feature).
    """
    __tablename__ = "tenant_references"
    __table_args__ = (
        Index("idx_tenant_references_tenant", "tenant_id"),
        Index("idx_tenant_references_owner", "owner_id"),
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    owner_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    property_id = Column(Uuid, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)
    unit_id = Column(Uuid, ForeignKey("units.id", ondelete="SET NULL"), nullable=True)

    # Tenancy period
    tenancy_start = Column(Date, nullable=False)
    tenancy_end = Column(Date, nullable=True)

    # Star ratings (1-5)
    overall_rating = Column(Integer, nullable=False)
    payment_rating = Column(Integer, nullable=False)
    maintenance_rating = Column(Integer, nullable=False)

    would_rent_again = Column(Boolean, nullable=False, default=True)
    reference_notes = Column(Text, nullable=True)

    # Passport visibility
    is_public = Column(Boolean, nullable=False, default=False)
    verification_code = Column(String(64), nullable=True)  # shared with prospective landlords

    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class PortfolioRiskSummary(Base):
    """
    Aggregated risk snapshot for an owner's entire tenant portfolio.
    One row per owner. Upserted by compute_portfolio_risk().
    """
    __tablename__ = "portfolio_risk_summary"
    __table_args__ = (
        UniqueConstraint("owner_id", name="uq_portfolio_risk_owner"),
        Index("idx_portfolio_risk_owner", "owner_id"),
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Counts by risk tier
    total_tenants = Column(Integer, nullable=False, default=0)
    low_risk_count = Column(Integer, nullable=False, default=0)
    medium_risk_count = Column(Integer, nullable=False, default=0)
    high_risk_count = Column(Integer, nullable=False, default=0)
    critical_risk_count = Column(Integer, nullable=False, default=0)

    # Portfolio health
    avg_health_score = Column(Numeric(5, 2), nullable=False, default=0)
    tenants_flagged_for_review = Column(JSONB, nullable=False, default=list)  # list of tenant_id strings
    estimated_churn_risk_count = Column(Integer, nullable=False, default=0)

    last_computed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
