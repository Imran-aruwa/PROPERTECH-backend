"""
Vacancy Listing Syndication Models
Covers: VacancyListing, ListingSyndication, ListingLead, ListingAnalytics
"""
import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Integer, Float, Text, DateTime, Boolean,
    ForeignKey, Enum, JSON, Index
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship

from app.db.base import Base


# ── Enums ──────────────────────────────────────────────────────────────────────

class ListingStatus(str, PyEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    FILLED = "filled"


class SyndicationPlatform(str, PyEnum):
    WHATSAPP = "whatsapp"
    FACEBOOK = "facebook"
    TWITTER = "twitter"
    PROPERTY24 = "property24"
    BUYRENTKENYA = "buyrentkenya"
    JIJI = "jiji"
    DIRECT_LINK = "direct_link"


class SyndicationStatus(str, PyEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"
    EXPIRED = "expired"


class LeadStatus(str, PyEnum):
    NEW = "new"
    CONTACTED = "contacted"
    VIEWING_SCHEDULED = "viewing_scheduled"
    APPROVED = "approved"
    REJECTED = "rejected"


class AnalyticsEventType(str, PyEnum):
    VIEW = "view"
    INQUIRY = "inquiry"
    SHARE = "share"
    CLICK = "click"


# ── Models ─────────────────────────────────────────────────────────────────────

class VacancyListing(Base):
    __tablename__ = "vacancy_listings"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(PG_UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"), nullable=True, index=True)
    unit_id = Column(PG_UUID(as_uuid=True), ForeignKey("units.id", ondelete="SET NULL"), nullable=True, index=True)

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    monthly_rent = Column(Float, nullable=False, default=0.0)
    deposit_amount = Column(Float, nullable=True, default=0.0)
    available_from = Column(DateTime, nullable=True)

    # Structured data stored as JSON (compatible with SQLite + PostgreSQL)
    amenities = Column(JSON, nullable=True, default=list)   # ["WiFi", "Parking", ...]
    photos = Column(JSON, nullable=True, default=list)       # [url, url, ...]

    status = Column(
        Enum(ListingStatus, name="listingstatus", create_type=True),
        nullable=False,
        default=ListingStatus.DRAFT,
        index=True,
    )
    slug = Column(String(200), unique=True, nullable=False, index=True)
    view_count = Column(Integer, nullable=False, default=0)

    published_at = Column(DateTime, nullable=True)
    filled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    syndications = relationship("ListingSyndication", back_populates="listing", cascade="all, delete-orphan")
    leads = relationship("ListingLead", back_populates="listing", cascade="all, delete-orphan")
    analytics = relationship("ListingAnalytics", back_populates="listing", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_vacancy_listings_owner_status", "owner_id", "status"),
    )


class ListingSyndication(Base):
    __tablename__ = "listing_syndications"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id = Column(PG_UUID(as_uuid=True), ForeignKey("vacancy_listings.id", ondelete="CASCADE"), nullable=False, index=True)

    platform = Column(
        Enum(SyndicationPlatform, name="syndicationplatform", create_type=True),
        nullable=False,
    )
    status = Column(
        Enum(SyndicationStatus, name="syndicationstatus", create_type=True),
        nullable=False,
        default=SyndicationStatus.PENDING,
    )
    external_url = Column(String(1000), nullable=True)
    share_url = Column(String(1000), nullable=True)   # pre-filled share link
    published_at = Column(DateTime, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    listing = relationship("VacancyListing", back_populates="syndications")

    __table_args__ = (
        Index("ix_listing_syndications_listing_platform", "listing_id", "platform", unique=True),
    )


class ListingLead(Base):
    __tablename__ = "listing_leads"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id = Column(PG_UUID(as_uuid=True), ForeignKey("vacancy_listings.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    message = Column(Text, nullable=True)
    source_platform = Column(String(50), nullable=True)   # whatsapp, facebook, direct, etc.

    status = Column(
        Enum(LeadStatus, name="leadstatus_listing", create_type=True),
        nullable=False,
        default=LeadStatus.NEW,
        index=True,
    )
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    listing = relationship("VacancyListing", back_populates="leads")

    __table_args__ = (
        Index("ix_listing_leads_listing_status", "listing_id", "status"),
    )


class ListingAnalytics(Base):
    __tablename__ = "listing_analytics"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id = Column(PG_UUID(as_uuid=True), ForeignKey("vacancy_listings.id", ondelete="CASCADE"), nullable=False, index=True)

    platform = Column(String(50), nullable=True)   # which channel drove this event
    event_type = Column(
        Enum(AnalyticsEventType, name="analyticseventtype", create_type=True),
        nullable=False,
        index=True,
    )
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    occurred_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    listing = relationship("VacancyListing", back_populates="analytics")

    __table_args__ = (
        Index("ix_listing_analytics_listing_event", "listing_id", "event_type"),
    )
