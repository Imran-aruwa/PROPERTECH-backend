"""
Lead Model - Agent Lead Management
"""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Float, Text, Uuid, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
import uuid
import enum

from app.db.base import Base


class LeadStatus(str, enum.Enum):
    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    NEGOTIATING = "negotiating"
    CONVERTED = "converted"
    LOST = "lost"


class Lead(Base):
    """
    Lead model for agent lead tracking
    """
    __tablename__ = "leads"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Agent who owns this lead
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False, index=True)

    # Lead details
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)

    # Interest details
    property_interest: Mapped[str] = mapped_column(String(500), nullable=True)  # What type of property they're looking for
    budget: Mapped[float] = mapped_column(Float, nullable=True)

    # Lead tracking
    status: Mapped[LeadStatus] = mapped_column(
        SQLEnum(LeadStatus, name="lead_status"),
        default=LeadStatus.NEW,
        index=True
    )
    source: Mapped[str] = mapped_column(String(100), nullable=True)  # referral, website, walk-in, etc.
    notes: Mapped[str] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_contacted_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # Relationships
    agent = relationship("User", backref="leads")
