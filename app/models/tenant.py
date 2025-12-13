"""
Tenant Model - Property Management
"""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Float, Text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import uuid

from app.db.base import Base
from app.models.user import User

class Tenant(Base):
    """
    Tenant model for property management
    Linked to User via user_id
    """
    __tablename__ = "tenants"

    # Primary keys
    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    
    # Property/Unit relationship
    property_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    unit_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    
    # Tenant details
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    id_number: Mapped[str] = mapped_column(String(50), nullable=True)  # National ID
    next_of_kin: Mapped[str] = mapped_column(String(255), nullable=True)
    nok_phone: Mapped[str] = mapped_column(String(20), nullable=True)
    
    # Lease details
    rent_amount: Mapped[float] = mapped_column(Float, nullable=False)
    deposit_amount: Mapped[float] = mapped_column(Float, default=0.0)
    lease_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    lease_end: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    lease_duration_months: Mapped[int] = mapped_column(Integer, default=12)
    
    # Status
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active, inactive, evicted
    move_in_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    move_out_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    
    # Payment tracking
    balance_due: Mapped[float] = mapped_column(Float, default=0.0)
    last_payment_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    
    # Documents
    id_front_url: Mapped[str] = mapped_column(String(500), nullable=True)
    id_back_url: Mapped[str] = mapped_column(String(500), nullable=True)
    lease_agreement_url: Mapped[str] = mapped_column(String(500), nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="tenants")
    payments = relationship("Payment", back_populates="tenant")
    property = relationship("Property", back_populates="tenants")
    unit = relationship("Unit", back_populates="tenants")           
    