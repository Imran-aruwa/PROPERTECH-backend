"""
Vacancy Prevention Engine Models
Tables: vacancy_leads, vacancy_lead_activities, listing_syndications,
        renewal_campaigns, vacancy_prevention_settings
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


class VacancyLead(Base):
    __tablename__ = "vacancy_leads"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=True, index=True)
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=True, index=True)

    lead_name = Column(String(255), nullable=False)
    lead_phone = Column(String(50), nullable=False)
    lead_email = Column(String(255), nullable=True)

    # walk_in/whatsapp/phone/referral/listing_site/manual
    source = Column(String(50), nullable=False, default="manual")
    # new/contacted/viewing_scheduled/viewed/applied/approved/rejected/converted/lost
    status = Column(String(50), nullable=False, default="new", index=True)

    preferred_unit_type = Column(String(50), nullable=True)
    preferred_move_in = Column(Date, nullable=True)
    budget_min = Column(Numeric(12, 2), nullable=True)
    budget_max = Column(Numeric(12, 2), nullable=True)
    notes = Column(Text, nullable=True)

    last_contacted_at = Column(DateTime(timezone=True), nullable=True)
    follow_up_due_at = Column(DateTime(timezone=True), nullable=True, index=True)
    converted_tenant_id = Column(Uuid, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)


class VacancyLeadActivity(Base):
    __tablename__ = "vacancy_lead_activities"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    lead_id = Column(Uuid, ForeignKey("vacancy_leads.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False)

    # note/call/sms/email/whatsapp/viewing/status_change
    activity_type = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    performed_by = Column(Uuid, ForeignKey("users.id"), nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class ListingSyndication(Base):
    """
    Vacancy Prevention listing — richer than the Feature #1 VacancyListing.
    Tracks per-platform syndication and lead metrics.
    """
    __tablename__ = "listing_syndications"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=False, index=True)
    # Soft link to Feature #1 listings table — nullable
    listing_id = Column(Uuid, nullable=True)

    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    monthly_rent = Column(Numeric(12, 2), nullable=False)
    bedrooms = Column(Integer, nullable=True)
    bathrooms = Column(Integer, nullable=True)
    unit_type = Column(String(50), nullable=False)
    amenities = _json_col(nullable=True)   # array of strings
    photos = _json_col(nullable=True)      # array of URLs
    location_area = Column(String(200), nullable=True)

    # draft/active/paused/filled
    status = Column(String(20), nullable=False, default="draft", index=True)

    view_count = Column(Integer, default=0, nullable=False)
    enquiry_count = Column(Integer, default=0, nullable=False)

    # array of {platform_name, url, posted_at, status}
    platforms = _json_col(nullable=True)

    published_at = Column(DateTime(timezone=True), nullable=True)
    filled_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)


class RenewalCampaign(Base):
    __tablename__ = "renewal_campaigns"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    lease_id = Column(Uuid, ForeignKey("leases.id"), nullable=False, index=True)
    tenant_id = Column(Uuid, ForeignKey("users.id"), nullable=True)
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=False)

    # scheduled/active/responded/accepted/declined/expired
    campaign_status = Column(String(30), nullable=False, default="scheduled", index=True)
    trigger_days_before_expiry = Column(Integer, nullable=False)  # 60 / 30 / 7

    # standard / incentive
    offer_type = Column(String(20), nullable=False, default="standard")
    incentive_description = Column(Text, nullable=True)
    proposed_rent = Column(Numeric(12, 2), nullable=True)
    current_rent = Column(Numeric(12, 2), nullable=False)

    # accepted/declined/negotiating/no_response
    tenant_response = Column(String(30), nullable=True)
    response_received_at = Column(DateTime(timezone=True), nullable=True)

    follow_up_count = Column(Integer, default=0, nullable=False)
    last_follow_up_at = Column(DateTime(timezone=True), nullable=True)

    # renewed/vacated/pending
    outcome = Column(String(20), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)


class VacancyPreventionSettings(Base):
    __tablename__ = "vacancy_prevention_settings"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False, unique=True, index=True)

    is_enabled = Column(Boolean, default=True, nullable=False)
    auto_create_listing = Column(Boolean, default=True, nullable=False)
    auto_syndicate = Column(Boolean, default=False, nullable=False)

    # JSONB array e.g. [60, 30, 7]
    renewal_campaign_days = _json_col(nullable=True)

    lead_follow_up_hours = Column(Integer, default=24, nullable=False)
    auto_sms_new_leads = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)
