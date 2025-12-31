"""
Viewing Model - Property Viewing Management
"""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, Uuid, Enum
from sqlalchemy.orm import Mapped, mapped_column
import uuid
import enum

from app.db.base import Base


class ViewingStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class Viewing(Base):
    """
    Viewing model for property showing appointments
    """
    __tablename__ = "viewings"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Agent who scheduled this viewing
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)

    # Property/Unit being viewed
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=True)

    # Client details
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    client_email: Mapped[str] = mapped_column(String(255), nullable=True)

    # Viewing details
    viewing_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[ViewingStatus] = mapped_column(
        Enum(ViewingStatus, name="viewing_status"),
        default=ViewingStatus.SCHEDULED,
        index=True
    )
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    feedback: Mapped[str] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
