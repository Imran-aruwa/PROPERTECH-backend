"""
Inspection Models - Offline-first property inspection system
Supports routine, move-in, move-out, and meter inspections
"""
from datetime import datetime
from enum import Enum
from sqlalchemy import (
    Column, String, DateTime, Integer, Float, Text, Uuid,
    ForeignKey, Numeric, Index
)
from sqlalchemy.orm import relationship
import uuid

from app.db.base import Base


class InspectionType(str, Enum):
    ROUTINE = "routine"
    MOVE_IN = "move_in"
    MOVE_OUT = "move_out"
    METER = "meter"


class InspectionStatus(str, Enum):
    SUBMITTED = "submitted"
    REVIEWED = "reviewed"
    LOCKED = "locked"


class InspectionItemCategory(str, Enum):
    PLUMBING = "plumbing"
    ELECTRICAL = "electrical"
    STRUCTURE = "structure"
    CLEANLINESS = "cleanliness"


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


class Inspection(Base):
    __tablename__ = "inspections"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    client_uuid = Column(Uuid, unique=True, nullable=False)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=False)
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=False)
    performed_by_id = Column(Uuid, ForeignKey("users.id"), nullable=False)
    performed_by_role = Column(String(20), nullable=False)
    inspection_type = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default=InspectionStatus.SUBMITTED.value)
    inspection_date = Column(DateTime(timezone=True), nullable=False)
    gps_lat = Column(Numeric(10, 8), nullable=True)
    gps_lng = Column(Numeric(11, 8), nullable=True)
    device_id = Column(String(255), nullable=True)
    offline_created_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    items = relationship("InspectionItem", back_populates="inspection", cascade="all, delete-orphan")
    media = relationship("InspectionMedia", back_populates="inspection", cascade="all, delete-orphan")
    meter_readings = relationship("InspectionMeterReading", back_populates="inspection")
    property = relationship("Property")
    unit = relationship("Unit")
    performed_by = relationship("User")

    __table_args__ = (
        Index("idx_inspections_property", "property_id"),
        Index("idx_inspections_performed_by", "performed_by_id"),
        Index("idx_inspections_status", "status"),
    )


class InspectionItem(Base):
    __tablename__ = "inspection_items"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    inspection_id = Column(Uuid, ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False)
    client_uuid = Column(Uuid, unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    category = Column(String(20), nullable=False)
    condition = Column(String(10), nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    inspection = relationship("Inspection", back_populates="items")

    __table_args__ = (
        Index("idx_inspection_items_inspection", "inspection_id"),
    )


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
