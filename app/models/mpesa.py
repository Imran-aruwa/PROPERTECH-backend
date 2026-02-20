"""
Mpesa Payment Intelligence Engine — Database Models

Tables:
  mpesa_configs              — per-owner Daraja credentials & configuration
  mpesa_transactions         — every inbound Mpesa payment event
  mpesa_reminders            — individual reminder dispatch records
  mpesa_reminder_rules       — per-owner reminder schedule & templates
  mpesa_reconciliation_logs  — audit trail for every reconciliation action
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index,
    Integer, String, Text, Uuid,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ── Enum definitions ──────────────────────────────────────────────────────────

class ShortcodeType(str, Enum):
    PAYBILL = "paybill"
    TILL    = "till"


class MpesaEnvironment(str, Enum):
    SANDBOX    = "sandbox"
    PRODUCTION = "production"


class TransactionType(str, Enum):
    PAYBILL   = "paybill"
    TILL      = "till"
    STK_PUSH  = "stk_push"


class ReconciliationStatus(str, Enum):
    UNMATCHED = "unmatched"
    MATCHED   = "matched"
    PARTIAL   = "partial"
    DUPLICATE = "duplicate"
    DISPUTED  = "disputed"


class ReminderType(str, Enum):
    PRE_DUE      = "pre_due"
    DUE_TODAY    = "due_today"
    DAY_1        = "day_1"
    DAY_3        = "day_3"
    DAY_7        = "day_7"
    DAY_14       = "day_14"
    FINAL_NOTICE = "final_notice"


class ReminderChannel(str, Enum):
    SMS       = "sms"
    WHATSAPP  = "whatsapp"


class ReminderStatus(str, Enum):
    PENDING   = "pending"
    SENT      = "sent"
    FAILED    = "failed"
    DELIVERED = "delivered"


class ReconciliationAction(str, Enum):
    AUTO_MATCHED   = "auto_matched"
    MANUAL_MATCHED = "manual_matched"
    FLAGGED        = "flagged"
    DISPUTED       = "disputed"


# ── Models ────────────────────────────────────────────────────────────────────

class MpesaConfig(Base):
    """
    Stores one Mpesa/Daraja integration profile per owner.
    Credentials are encrypted-at-rest at the application layer (stored as-is
    here; owners must ensure the DB is access-controlled).
    """
    __tablename__ = "mpesa_configs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False, unique=True, index=True)

    # Daraja Paybill / Till
    shortcode: Mapped[str] = mapped_column(String(20), nullable=False)
    shortcode_type: Mapped[ShortcodeType] = mapped_column(SQLEnum(ShortcodeType), nullable=False)

    # Daraja API credentials (owner-supplied from Safaricom portal)
    consumer_key: Mapped[str] = mapped_column(String(255), nullable=False)
    consumer_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    passkey: Mapped[str] = mapped_column(String(500), nullable=True)  # STK only

    # Callback base URL — set to Railway backend URL automatically
    callback_url: Mapped[str] = mapped_column(String(500), nullable=True)

    # Pattern used to match incoming account references to units/tenants
    # e.g. "UNIT-{unit_number}" or "{tenant_name}"
    account_reference_format: Mapped[str] = mapped_column(String(100), nullable=True, default="UNIT-{unit_number}")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    environment: Mapped[MpesaEnvironment] = mapped_column(SQLEnum(MpesaEnvironment), default=MpesaEnvironment.SANDBOX, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MpesaTransaction(Base):
    """
    One row per incoming Mpesa payment event (STK callback or C2B confirmation).
    Initially unmatched; reconciliation engine links it to a tenant/payment.
    """
    __tablename__ = "mpesa_transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False, index=True)

    # Resolved after reconciliation (nullable until matched)
    property_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, ForeignKey("properties.id"), nullable=True)
    unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)

    # Mpesa fields
    mpesa_receipt_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    transaction_type: Mapped[TransactionType] = mapped_column(SQLEnum(TransactionType), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    account_reference: Mapped[str] = mapped_column(String(255), nullable=True)
    transaction_desc: Mapped[str] = mapped_column(String(500), nullable=True)
    transaction_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Reconciliation
    reconciliation_status: Mapped[ReconciliationStatus] = mapped_column(
        SQLEnum(ReconciliationStatus), default=ReconciliationStatus.UNMATCHED, nullable=False, index=True
    )
    reconciliation_confidence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    matched_payment_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, ForeignKey("payments.id"), nullable=True)

    # Raw Safaricom payload stored as JSON text
    raw_payload: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    reconciliation_logs = relationship("MpesaReconciliationLog", back_populates="transaction")
    matched_payment = relationship("Payment", foreign_keys=[matched_payment_id])

    __table_args__ = (
        Index("ix_mpesa_txn_owner_status", "owner_id", "reconciliation_status"),
        Index("ix_mpesa_txn_phone_date", "phone_number", "transaction_date"),
    )


class MpesaReminder(Base):
    """
    One row per reminder dispatch (scheduled or manual).
    """
    __tablename__ = "mpesa_reminders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)

    reminder_type: Mapped[ReminderType] = mapped_column(SQLEnum(ReminderType), nullable=False)
    channel: Mapped[ReminderChannel] = mapped_column(SQLEnum(ReminderChannel), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ReminderStatus] = mapped_column(SQLEnum(ReminderStatus), default=ReminderStatus.PENDING, nullable=False, index=True)

    scheduled_for: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Africa's Talking cost tracking (optional)
    mpesa_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Reference month so we can cancel correctly (e.g. "2025-01")
    reference_month: Mapped[str] = mapped_column(String(7), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_mpesa_reminder_owner_status", "owner_id", "status"),
        Index("ix_mpesa_reminder_tenant_month", "tenant_id", "reference_month"),
    )


class MpesaReminderRule(Base):
    """
    Per-owner reminder schedule configuration.
    channels and escalation_rules stored as JSON text.
    """
    __tablename__ = "mpesa_reminder_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False, unique=True, index=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    pre_due_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    # JSON: {"pre_due": "sms", "due_today": "sms", "day_1": "whatsapp", ...}
    channels: Mapped[str] = mapped_column(Text, nullable=True)

    # JSON: {reminder_type: "message template with {placeholders}"}
    escalation_rules: Mapped[str] = mapped_column(Text, nullable=True)

    # Enabled flags per reminder type (stored as JSON: {"pre_due": true, ...})
    enabled_types: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MpesaReconciliationLog(Base):
    """
    Immutable audit trail for every reconciliation action taken on a transaction.
    """
    __tablename__ = "mpesa_reconciliation_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("mpesa_transactions.id"), nullable=False, index=True)

    action: Mapped[ReconciliationAction] = mapped_column(SQLEnum(ReconciliationAction), nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    match_reason: Mapped[str] = mapped_column(Text, nullable=True)

    # "system" for automatic, user UUID string for manual
    performed_by: Mapped[str] = mapped_column(String(50), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    transaction = relationship("MpesaTransaction", back_populates="reconciliation_logs")
