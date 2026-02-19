"""
Lease Management Schemas
Pydantic v2 models matching the frontend's Lease / LeaseClause / LeaseSignature types.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator, model_validator


# ─────────────────────── Clause ───────────────────────

class ClauseIn(BaseModel):
    """Clause as sent by the frontend (type / text naming)."""
    id: Optional[str] = None
    type: str = "custom"
    text: str
    editable: bool = True
    risk_weight: Optional[float] = 0.0


class ClauseOut(BaseModel):
    """Clause as returned to the frontend."""
    id: str
    type: str
    text: str
    editable: bool
    risk_weight: float

    class Config:
        from_attributes = True


# ─────────────────────── Signature ───────────────────────

class SignatureOut(BaseModel):
    id: str
    lease_id: str
    signer_name: str
    signer_role: str
    signature_type: str
    signed_at: Optional[str]
    otp_verified: bool
    ip_address: Optional[str]

    class Config:
        from_attributes = True


# ─────────────────────── Lease CRUD ───────────────────────

class LeaseCreate(BaseModel):
    """
    Payload from LeaseForm.buildPayload().
    property_id / unit_id / tenant_id arrive as null because the frontend
    does Number(uuid_string) → NaN → JSON null.  We accept Any and try to
    coerce to UUID; null / invalid values are stored as None.
    """
    property_id: Optional[Any] = None
    unit_id: Optional[Any] = None
    tenant_id: Optional[Any] = None

    start_date: str           # "YYYY-MM-DD"
    end_date: str             # "YYYY-MM-DD"
    rent_amount: float
    deposit_amount: float
    payment_cycle: str = "monthly"
    escalation_rate: Optional[float] = None

    clauses: List[ClauseIn] = []

    @field_validator("property_id", "unit_id", "tenant_id", mode="before")
    @classmethod
    def _coerce_uuid(cls, v: Any) -> Optional[uuid.UUID]:
        if v is None or v == 0 or v == "" or v != v:  # NaN check (NaN != NaN)
            return None
        try:
            return uuid.UUID(str(v))
        except (ValueError, AttributeError):
            return None

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _parse_date(cls, v: Any) -> str:
        if isinstance(v, (date, datetime)):
            return v.strftime("%Y-%m-%d")
        return str(v)


class LeaseUpdate(BaseModel):
    """Partial update — only draft leases can be updated."""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    rent_amount: Optional[float] = None
    deposit_amount: Optional[float] = None
    payment_cycle: Optional[str] = None
    escalation_rate: Optional[float] = None
    clauses: Optional[List[ClauseIn]] = None
    status: Optional[str] = None


class SendLeaseRequest(BaseModel):
    channels: List[str] = ["email"]


class SignRequest(BaseModel):
    """POST /leases/sign/{token}  — submitted by the tenant."""
    signature_type: str            # "typed" | "drawn"
    signature_data: str            # full name or base64 PNG
    signer_name: Optional[str] = ""
    resend: Optional[bool] = False
    ip_address: Optional[str] = None
    device_fingerprint: Optional[str] = None


class VerifyOtpRequest(BaseModel):
    otp: str


# ─────────────────────── Nested detail objects ───────────────────────

class PropertyBrief(BaseModel):
    id: str
    name: str
    address: Optional[str] = None

    class Config:
        from_attributes = True


class UnitBrief(BaseModel):
    id: str
    unit_number: str

    class Config:
        from_attributes = True


class TenantBrief(BaseModel):
    id: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

    class Config:
        from_attributes = True


# ─────────────────────── Lease Response ───────────────────────

class LeaseOut(BaseModel):
    """Full lease response matching the frontend Lease interface."""
    id: str
    owner_id: str
    property_id: Optional[str]
    unit_id: Optional[str]
    tenant_id: Optional[str]

    title: str
    status: str
    start_date: str
    end_date: str
    rent_amount: float
    deposit_amount: float
    payment_cycle: str
    escalation_rate: Optional[float]

    pdf_url: Optional[str]
    sent_at: Optional[str]
    signed_at: Optional[str]
    created_at: str
    updated_at: str

    clauses: List[ClauseOut] = []
    signatures: List[SignatureOut] = []

    # Nested detail (populated by route, not ORM relationship)
    property: Optional[PropertyBrief] = None
    unit: Optional[UnitBrief] = None
    tenant: Optional[TenantBrief] = None

    class Config:
        from_attributes = True


class LeaseListItem(BaseModel):
    """Lighter object for the list view."""
    id: str
    title: str
    status: str
    start_date: str
    end_date: str
    rent_amount: float
    deposit_amount: float
    payment_cycle: str
    pdf_url: Optional[str]
    sent_at: Optional[str]
    signed_at: Optional[str]
    created_at: str
    property_id: Optional[str]
    unit_id: Optional[str]
    tenant_id: Optional[str]
    tenant_name: Optional[str]
    tenant_email: Optional[str]
    property: Optional[PropertyBrief] = None
    unit: Optional[UnitBrief] = None
    tenant: Optional[TenantBrief] = None

    class Config:
        from_attributes = True


# ─────────────────────── Templates ───────────────────────

class ClauseTemplate(BaseModel):
    id: str
    type: str
    label: str
    text: str
    editable: bool
    risk_weight: float
