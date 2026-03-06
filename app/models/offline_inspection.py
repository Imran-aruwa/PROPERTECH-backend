"""
Offline Inspection Extension Models
New tables that extend the existing inspection system for offline-first PWA support.
"""
from datetime import datetime
from sqlalchemy import (
    Column, String, DateTime, Integer, Text, Uuid, Boolean,
    ForeignKey, Index, JSON
)
from sqlalchemy.orm import relationship
import uuid

from app.db.base import Base


# ============================================
# INSPECTION ROOM
# Represents a room/area within an inspection.
# Items link to rooms via inspection_items.room_id (ALTER TABLE in startup).
# ============================================

class InspectionRoom(Base):
    __tablename__ = "inspection_rooms"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    inspection_id = Column(
        Uuid, ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False
    )
    client_uuid = Column(Uuid, unique=True, nullable=False)
    name = Column(String(255), nullable=False)           # e.g. "Living Room", "Kitchen"
    order_index = Column(Integer, default=0, nullable=False)
    condition_summary = Column(String(20), nullable=True)  # good|fair|poor
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationship back to Inspection (string ref — lazy resolved)
    inspection = relationship("Inspection", foreign_keys=[inspection_id])

    __table_args__ = (
        Index("idx_inspection_rooms_inspection", "inspection_id"),
    )


# ============================================
# SYNC QUEUE
# Stores raw device payloads for async processing.
# Status: pending → processing → done | error
# ============================================

class SyncQueue(Base):
    __tablename__ = "sync_queue"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    device_id = Column(String(255), nullable=False)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False)
    payload = Column(JSON, nullable=False)               # full sync payload from device
    status = Column(String(20), nullable=False, default="pending")  # pending|processing|done|error
    attempts = Column(Integer, default=0, nullable=False)
    result = Column(JSON, nullable=True)                 # {synced, skipped, errors}
    error_detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)

    owner = relationship("User", foreign_keys=[owner_id])

    __table_args__ = (
        Index("idx_sync_queue_device", "device_id"),
        Index("idx_sync_queue_owner", "owner_id"),
        Index("idx_sync_queue_status", "status"),
    )
