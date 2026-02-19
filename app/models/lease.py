"""
Digital Lease Management Models
Tables: leases, lease_clauses, lease_signatures
"""
from datetime import datetime
from enum import Enum
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Boolean,
    ForeignKey, Text, Enum as SQLEnum, Uuid, Index, Numeric,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import uuid

from app.db.base import Base


class LeaseStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    SIGNED = "signed"
    ACTIVE = "active"
    EXPIRED = "expired"
    TERMINATED = "terminated"


class PaymentCycle(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUALLY = "annually"


class Lease(Base):
    """Core lease agreement record."""
    __tablename__ = "leases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owner (protected by auth)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False, index=True
    )

    # Linked entities — nullable because the frontend sends null (NaN→null)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=True, index=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=True, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=True, index=True)

    # Denormalised tenant contact — populated on create from resolved Tenant row
    tenant_name: Mapped[str] = mapped_column(String(255), nullable=True)
    tenant_email: Mapped[str] = mapped_column(String(255), nullable=True)
    tenant_phone: Mapped[str] = mapped_column(String(50), nullable=True)

    # Lease metadata
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[LeaseStatus] = mapped_column(
        SQLEnum(LeaseStatus), default=LeaseStatus.DRAFT, nullable=False, index=True
    )

    # Financial terms
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    rent_amount: Mapped[float] = mapped_column(Float, nullable=False)
    deposit_amount: Mapped[float] = mapped_column(Float, nullable=False)
    payment_cycle: Mapped[PaymentCycle] = mapped_column(
        SQLEnum(PaymentCycle), default=PaymentCycle.MONTHLY, nullable=False
    )
    escalation_rate: Mapped[float] = mapped_column(Float, nullable=True)

    # E-signature token (UUID, single-use, time-limited)
    signing_token: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=True, unique=True, index=True
    )
    token_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # Output
    pdf_url: Mapped[str] = mapped_column(String(1000), nullable=True)

    # Event timestamps
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    signed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    clauses = relationship(
        "LeaseClause",
        back_populates="lease",
        cascade="all, delete-orphan",
        order_by="LeaseClause.order",
    )
    signatures = relationship(
        "LeaseSignature",
        back_populates="lease",
        cascade="all, delete-orphan",
    )
    owner = relationship("User", foreign_keys=[owner_id])

    __table_args__ = (
        Index("idx_leases_owner_status", "owner_id", "status"),
    )


class LeaseClause(Base):
    """Individual clause within a lease agreement."""
    __tablename__ = "lease_clauses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    lease_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("leases.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Stored using frontend field names so the API response is a pass-through
    clause_type: Mapped[str] = mapped_column(String(50), nullable=False, default="custom")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_weight: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lease = relationship("Lease", back_populates="clauses")


class LeaseSignature(Base):
    """
    E-signature record for a lease.
    Modelled after InspectionSignature with OTP verification added.
    """
    __tablename__ = "lease_signatures"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    lease_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("leases.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Signer identity
    signer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    signer_email: Mapped[str] = mapped_column(String(255), nullable=True)
    signer_phone: Mapped[str] = mapped_column(String(50), nullable=True)
    signer_role: Mapped[str] = mapped_column(String(50), default="tenant")

    # Signature payload
    signature_type: Mapped[str] = mapped_column(String(20), nullable=False)  # typed | drawn
    signature_data: Mapped[str] = mapped_column(Text, nullable=False)        # name or base64 PNG

    # OTP verification
    otp_code_hash: Mapped[str] = mapped_column(String(255), nullable=True)   # bcrypt hash
    otp_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    otp_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    otp_attempts: Mapped[int] = mapped_column(Integer, default=0)

    # Audit trail
    ip_address: Mapped[str] = mapped_column(String(45), nullable=True)
    device_fingerprint: Mapped[str] = mapped_column(String(255), nullable=True)

    signed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lease = relationship("Lease", back_populates="signatures")

    __table_args__ = (
        Index("idx_lease_signatures_lease", "lease_id"),
    )
