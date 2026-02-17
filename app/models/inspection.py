"""
Inspection Models - Universal Inspection Engine
Supports internal + external inspections, templates, scoring, signatures, audit trails.
Offline-first, subscription-gated, legally defensible.
"""
from datetime import datetime
from enum import Enum
from sqlalchemy import (
    Column, String, DateTime, Integer, Float, Text, Uuid, Boolean,
    ForeignKey, Numeric, Index, JSON
)
from sqlalchemy.orm import relationship
import uuid

from app.db.base import Base


# ============================================
# ENUMS
# ============================================

class InspectionType(str, Enum):
    ROUTINE = "routine"
    MOVE_IN = "move_in"
    MOVE_OUT = "move_out"
    METER = "meter"
    PRE_PURCHASE = "pre_purchase"
    INSURANCE = "insurance"
    VALUATION = "valuation"
    FIRE_SAFETY = "fire_safety"
    EMERGENCY_DAMAGE = "emergency_damage"


class InspectionStatus(str, Enum):
    SUBMITTED = "submitted"
    REVIEWED = "reviewed"
    LOCKED = "locked"


class InspectionItemCategory(str, Enum):
    PLUMBING = "plumbing"
    ELECTRICAL = "electrical"
    STRUCTURE = "structure"
    CLEANLINESS = "cleanliness"
    SAFETY = "safety"
    EXTERIOR = "exterior"
    APPLIANCES = "appliances"
    FIXTURES = "fixtures"


class InspectionItemCondition(str, Enum):
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"


class InspectionMediaType(str, Enum):
    PHOTO = "photo"
    VIDEO = "video"


class MeterType(str, Enum):
    WATER = "water"
    ELECTRICITY = "electricity"


class SeverityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================
# INSPECTION TEMPLATE
# ============================================

class InspectionTemplate(Base):
    __tablename__ = "inspection_templates"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    inspection_type = Column(String(30), nullable=False)
    is_external = Column(Boolean, default=False, nullable=False)
    categories = Column(JSON, nullable=True)  # list of category strings
    default_items = Column(JSON, nullable=True)  # [{name, category, required_photo}]
    scoring_enabled = Column(Boolean, default=True, nullable=False)
    pass_threshold = Column(Float, nullable=True, default=3.0)  # min avg score to pass
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    owner = relationship("User")
    inspections = relationship("Inspection", back_populates="template")

    __table_args__ = (
        Index("idx_templates_owner", "owner_id"),
        Index("idx_templates_type", "inspection_type"),
    )


# ============================================
# INSPECTION (Enhanced)
# ============================================

class Inspection(Base):
    __tablename__ = "inspections"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    client_uuid = Column(Uuid, unique=True, nullable=False)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=False)
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=False)
    performed_by_id = Column(Uuid, ForeignKey("users.id"), nullable=False)
    performed_by_role = Column(String(20), nullable=False)
    inspection_type = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False, default=InspectionStatus.SUBMITTED.value)
    inspection_date = Column(DateTime(timezone=True), nullable=False)
    gps_lat = Column(Numeric(10, 8), nullable=True)
    gps_lng = Column(Numeric(11, 8), nullable=True)
    device_id = Column(String(255), nullable=True)
    offline_created_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)

    # New: Universal engine fields
    is_external = Column(Boolean, default=False, nullable=False)
    template_id = Column(Uuid, ForeignKey("inspection_templates.id"), nullable=True)
    overall_score = Column(Float, nullable=True)  # computed avg of item scores
    pass_fail = Column(String(10), nullable=True)  # 'pass' | 'fail' | null
    inspector_name = Column(String(255), nullable=True)  # for external inspectors
    inspector_credentials = Column(String(500), nullable=True)
    inspector_company = Column(String(255), nullable=True)
    report_url = Column(String(500), nullable=True)  # PDF report URL

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    items = relationship("InspectionItem", back_populates="inspection", cascade="all, delete-orphan")
    media = relationship("InspectionMedia", back_populates="inspection", cascade="all, delete-orphan")
    meter_readings = relationship("InspectionMeterReading", back_populates="inspection")
    signatures = relationship("InspectionSignature", back_populates="inspection", cascade="all, delete-orphan")
    template = relationship("InspectionTemplate", back_populates="inspections")
    property = relationship("Property")
    unit = relationship("Unit")
    performed_by = relationship("User")

    __table_args__ = (
        Index("idx_inspections_property", "property_id"),
        Index("idx_inspections_performed_by", "performed_by_id"),
        Index("idx_inspections_status", "status"),
        Index("idx_inspections_is_external", "is_external"),
    )


# ============================================
# INSPECTION ITEM (Enhanced with scoring)
# ============================================

class InspectionItem(Base):
    __tablename__ = "inspection_items"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    inspection_id = Column(Uuid, ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False)
    client_uuid = Column(Uuid, unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    category = Column(String(30), nullable=False)
    condition = Column(String(10), nullable=False)
    comment = Column(Text, nullable=True)

    # New: Scoring & severity
    score = Column(Integer, nullable=True)  # 1-5 scoring
    severity = Column(String(10), nullable=True)  # low|medium|high|critical
    pass_fail = Column(String(10), nullable=True)  # 'pass' | 'fail' | null
    requires_followup = Column(Boolean, default=False, nullable=False)
    photo_required = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    inspection = relationship("Inspection", back_populates="items")

    __table_args__ = (
        Index("idx_inspection_items_inspection", "inspection_id"),
    )


# ============================================
# INSPECTION MEDIA
# ============================================

class InspectionMedia(Base):
    __tablename__ = "inspection_media"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    inspection_id = Column(Uuid, ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False)
    client_uuid = Column(Uuid, unique=True, nullable=False)
    file_url = Column(String(500), nullable=False)
    file_type = Column(String(10), nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    inspection = relationship("Inspection", back_populates="media")

    __table_args__ = (
        Index("idx_inspection_media_inspection", "inspection_id"),
    )


# ============================================
# INSPECTION METER READING
# ============================================

class InspectionMeterReading(Base):
    __tablename__ = "inspection_meter_readings"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    inspection_id = Column(Uuid, ForeignKey("inspections.id", ondelete="SET NULL"), nullable=True)
    client_uuid = Column(Uuid, unique=True, nullable=False)
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=False)
    meter_type = Column(String(20), nullable=False)
    previous_reading = Column(Numeric(10, 2), nullable=False)
    current_reading = Column(Numeric(10, 2), nullable=False)
    reading_date = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    inspection = relationship("Inspection", back_populates="meter_readings")
    unit = relationship("Unit")

    __table_args__ = (
        Index("idx_meter_readings_unit", "unit_id"),
    )


# ============================================
# INSPECTION SIGNATURE (Digital signing)
# ============================================

class InspectionSignature(Base):
    __tablename__ = "inspection_signatures"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    inspection_id = Column(Uuid, ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False)
    signer_id = Column(Uuid, ForeignKey("users.id"), nullable=True)  # null for external
    signer_name = Column(String(255), nullable=False)
    signer_role = Column(String(50), nullable=False)  # inspector | owner | tenant
    signature_type = Column(String(20), nullable=False)  # typed | drawn
    signature_data = Column(Text, nullable=False)  # name or base64 image
    signed_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Audit trail
    ip_address = Column(String(45), nullable=True)
    device_fingerprint = Column(String(255), nullable=True)
    gps_lat = Column(Numeric(10, 8), nullable=True)
    gps_lng = Column(Numeric(11, 8), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    inspection = relationship("Inspection", back_populates="signatures")
    signer = relationship("User")

    __table_args__ = (
        Index("idx_signatures_inspection", "inspection_id"),
    )
