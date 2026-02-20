"""
Mpesa Payment Intelligence Engine — Pydantic Schemas
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator


# ── Config ────────────────────────────────────────────────────────────────────

class MpesaConfigCreate(BaseModel):
    shortcode: str
    shortcode_type: str  # paybill | till
    consumer_key: str
    consumer_secret: str
    passkey: Optional[str] = None
    account_reference_format: Optional[str] = "UNIT-{unit_number}"
    environment: Optional[str] = "sandbox"  # sandbox | production

    @field_validator("shortcode_type")
    @classmethod
    def validate_shortcode_type(cls, v):
        if v not in ("paybill", "till"):
            raise ValueError("shortcode_type must be 'paybill' or 'till'")
        return v

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v):
        if v not in ("sandbox", "production"):
            raise ValueError("environment must be 'sandbox' or 'production'")
        return v


class MpesaConfigOut(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    shortcode: str
    shortcode_type: str
    account_reference_format: Optional[str]
    is_active: bool
    environment: str
    callback_url: Optional[str]
    created_at: datetime
    updated_at: datetime

    # Never expose secrets in API responses
    model_config = {"from_attributes": True}


class MpesaTestConnectionRequest(BaseModel):
    phone: str  # Owner's own phone to receive the test STK push


# ── STK Push ──────────────────────────────────────────────────────────────────

class STKPushRequest(BaseModel):
    tenant_id: uuid.UUID
    amount: Optional[int] = None  # Override; defaults to tenant's rent_amount
    description: Optional[str] = "Rent Payment"

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v):
        if v is not None and v <= 0:
            raise ValueError("amount must be a positive integer (KES)")
        return v


class STKPushResponse(BaseModel):
    success: bool
    checkout_request_id: Optional[str] = None
    merchant_request_id: Optional[str] = None
    message: str


# ── Transactions ──────────────────────────────────────────────────────────────

class MpesaTransactionOut(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    property_id: Optional[uuid.UUID]
    unit_id: Optional[uuid.UUID]
    tenant_id: Optional[uuid.UUID]
    mpesa_receipt_number: str
    transaction_type: str
    phone_number: str
    amount: float
    account_reference: Optional[str]
    transaction_desc: Optional[str]
    transaction_date: datetime
    reconciliation_status: str
    reconciliation_confidence: int
    matched_payment_id: Optional[uuid.UUID]
    created_at: datetime

    # Denormalised for UI (resolved from FK lookups)
    tenant_name: Optional[str] = None
    unit_number: Optional[str] = None
    property_name: Optional[str] = None

    model_config = {"from_attributes": True}


class MpesaTransactionListResponse(BaseModel):
    transactions: List[MpesaTransactionOut]
    total: int
    unmatched_count: int
    matched_count: int


class ManualMatchRequest(BaseModel):
    tenant_id: uuid.UUID
    unit_id: uuid.UUID
    property_id: uuid.UUID
    payment_month: Optional[str] = None  # "2025-01" — defaults to current month


class DisputeRequest(BaseModel):
    reason: str


# ── CSV Import ────────────────────────────────────────────────────────────────

class CsvImportResponse(BaseModel):
    success: bool
    imported: int
    skipped_duplicates: int
    errors: List[str]


# ── Reminder Rules ────────────────────────────────────────────────────────────

class ReminderRuleUpdate(BaseModel):
    is_active: Optional[bool] = None
    pre_due_days: Optional[int] = None
    # {reminder_type: channel}
    channels: Optional[Dict[str, str]] = None
    # {reminder_type: message_template}
    escalation_rules: Optional[Dict[str, str]] = None
    # {reminder_type: bool}
    enabled_types: Optional[Dict[str, bool]] = None


class ReminderRuleOut(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    is_active: bool
    pre_due_days: int
    channels: Optional[Dict[str, str]]
    escalation_rules: Optional[Dict[str, str]]
    enabled_types: Optional[Dict[str, bool]]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Reminder Dispatch ─────────────────────────────────────────────────────────

class ReminderOut(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    tenant_id: uuid.UUID
    unit_id: Optional[uuid.UUID]
    reminder_type: str
    channel: str
    message: str
    status: str
    scheduled_for: datetime
    sent_at: Optional[datetime]
    reference_month: Optional[str]
    created_at: datetime

    # Denormalised
    tenant_name: Optional[str] = None
    tenant_phone: Optional[str] = None

    model_config = {"from_attributes": True}


class ReminderListResponse(BaseModel):
    reminders: List[ReminderOut]
    total: int
    pending_count: int
    sent_count: int
    failed_count: int


class TriggerReminderRequest(BaseModel):
    tenant_id: Optional[uuid.UUID] = None   # None = all overdue tenants
    reminder_type: Optional[str] = None     # Override type; None = auto by days_overdue
    channel: Optional[str] = None           # Override channel


# ── Analytics ─────────────────────────────────────────────────────────────────

class CollectionRateResponse(BaseModel):
    month: str                    # "2025-01"
    expected_count: int           # number of active tenants
    paid_count: int
    partial_count: int
    unpaid_count: int
    collection_rate_pct: float    # 0-100
    total_expected_kes: float
    total_collected_kes: float

    # Per-property breakdown
    by_property: List[Dict[str, Any]]


class PaymentTimingResponse(BaseModel):
    month: str
    # day_number -> count of payments received on that day
    distribution: Dict[str, int]
    avg_payment_day: Optional[float]
    on_time_pct: float   # paid by day 10


class RiskTenantItem(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    unit_number: Optional[str]
    property_name: Optional[str]
    consecutive_late_months: int
    total_overdue_kes: float
    last_payment_date: Optional[datetime]
    risk_level: str   # "medium" | "high" | "critical"


class RiskResponse(BaseModel):
    flagged_tenants: List[RiskTenantItem]
    total_at_risk_kes: float


# ── Dashboard summary ─────────────────────────────────────────────────────────

class MpesaDashboardSummary(BaseModel):
    month: str
    collection_rate_pct: float
    total_collected_kes: float
    unmatched_count: int
    reminders_sent_this_month: int

    # Payment status board — one row per active tenant/unit
    payment_status_board: List[Dict[str, Any]]

    # Unmatched transactions needing manual resolution
    unmatched_transactions: List[MpesaTransactionOut]

    # Recent activity (payments, reminders, reconciliation events)
    recent_activity: List[Dict[str, Any]]


# ── Webhook payloads (Safaricom → backend) ────────────────────────────────────

class STKCallbackItem(BaseModel):
    Name: str
    Value: Any


class STKCallbackMetadata(BaseModel):
    Item: List[STKCallbackItem]


class STKCallbackBody(BaseModel):
    MerchantRequestID: str
    CheckoutRequestID: str
    ResultCode: int
    ResultDesc: str
    CallbackMetadata: Optional[STKCallbackMetadata] = None


class STKCallbackPayload(BaseModel):
    Body: Dict[str, Any]


class C2BValidationPayload(BaseModel):
    TransactionType: str
    TransID: str
    TransTime: str
    TransAmount: str
    BusinessShortCode: str
    BillRefNumber: str
    InvoiceNumber: Optional[str] = None
    OrgAccountBalance: Optional[str] = None
    ThirdPartyTransID: Optional[str] = None
    MSISDN: str
    FirstName: Optional[str] = None
    MiddleName: Optional[str] = None
    LastName: Optional[str] = None


class C2BConfirmationPayload(BaseModel):
    TransactionType: str
    TransID: str
    TransTime: str
    TransAmount: str
    BusinessShortCode: str
    BillRefNumber: str
    InvoiceNumber: Optional[str] = None
    OrgAccountBalance: Optional[str] = None
    ThirdPartyTransID: Optional[str] = None
    MSISDN: str
    FirstName: Optional[str] = None
    MiddleName: Optional[str] = None
    LastName: Optional[str] = None
