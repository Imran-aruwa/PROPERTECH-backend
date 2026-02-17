"""
Inspection Schemas - Pydantic validation for Universal Inspection Engine
Supports templates, scoring, signatures, external inspections, audit trails.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from decimal import Decimal
from pydantic import BaseModel, Field


# ============================================
# REQUEST SCHEMAS
# ============================================

class InspectionItemCreate(BaseModel):
    client_uuid: UUID
    name: str = Field(..., max_length=255)
    category: str = Field(..., pattern="^(plumbing|electrical|structure|cleanliness|safety|exterior|appliances|fixtures)$")
    condition: str = Field(..., pattern="^(good|fair|poor)$")
    comment: Optional[str] = None
    score: Optional[int] = Field(None, ge=1, le=5)
    severity: Optional[str] = Field(None, pattern="^(low|medium|high|critical)$")
    pass_fail: Optional[str] = Field(None, pattern="^(pass|fail)$")
    requires_followup: Optional[bool] = False
    photo_required: Optional[bool] = False


class InspectionMeterReadingCreate(BaseModel):
    client_uuid: UUID
    unit_id: UUID
    meter_type: str = Field(..., pattern="^(water|electricity)$")
    previous_reading: Decimal = Field(..., ge=0)
    current_reading: Decimal = Field(..., ge=0)
    reading_date: datetime


class InspectionDataCreate(BaseModel):
    property_id: UUID
    unit_id: UUID
    inspection_type: str = Field(..., pattern="^(routine|move_in|move_out|meter|pre_purchase|insurance|valuation|fire_safety|emergency_damage)$")
    inspection_date: datetime
    gps_lat: Optional[Decimal] = None
    gps_lng: Optional[Decimal] = None
    device_id: Optional[str] = None
    offline_created_at: Optional[datetime] = None
    notes: Optional[str] = None
    is_external: Optional[bool] = False
    template_id: Optional[UUID] = None
    inspector_name: Optional[str] = None
    inspector_credentials: Optional[str] = None
    inspector_company: Optional[str] = None


class InspectionCreateRequest(BaseModel):
    client_uuid: UUID
    inspection: InspectionDataCreate
    items: List[InspectionItemCreate] = []
    meter_readings: List[InspectionMeterReadingCreate] = []


class InspectionMediaUpload(BaseModel):
    client_uuid: UUID
    file_data: str  # base64 encoded
    file_type: str = Field(..., pattern="^(photo|video)$")
    captured_at: Optional[datetime] = None


class InspectionReviewRequest(BaseModel):
    notes: Optional[str] = None


# --- Template Schemas ---

class InspectionTemplateCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    inspection_type: str = Field(..., pattern="^(routine|move_in|move_out|meter|pre_purchase|insurance|valuation|fire_safety|emergency_damage)$")
    is_external: Optional[bool] = False
    categories: Optional[List[str]] = None
    default_items: Optional[List[dict]] = None
    scoring_enabled: Optional[bool] = True
    pass_threshold: Optional[float] = 3.0


class InspectionTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    inspection_type: Optional[str] = None
    is_external: Optional[bool] = None
    categories: Optional[List[str]] = None
    default_items: Optional[List[dict]] = None
    scoring_enabled: Optional[bool] = None
    pass_threshold: Optional[float] = None
    is_active: Optional[bool] = None


# --- Signature Schemas ---

class InspectionSignatureCreate(BaseModel):
    signer_name: str = Field(..., max_length=255)
    signer_role: str = Field(..., pattern="^(inspector|owner|tenant)$")
    signature_type: str = Field(..., pattern="^(typed|drawn)$")
    signature_data: str
    ip_address: Optional[str] = None
    device_fingerprint: Optional[str] = None
    gps_lat: Optional[Decimal] = None
    gps_lng: Optional[Decimal] = None


# ============================================
# RESPONSE SCHEMAS
# ============================================

class InspectionItemResponse(BaseModel):
    id: UUID
    client_uuid: UUID
    name: str
    category: str
    condition: str
    comment: Optional[str] = None
    score: Optional[int] = None
    severity: Optional[str] = None
    pass_fail: Optional[str] = None
    requires_followup: Optional[bool] = False
    photo_required: Optional[bool] = False
    created_at: datetime

    class Config:
        from_attributes = True


class InspectionMediaResponse(BaseModel):
    id: UUID
    client_uuid: UUID
    file_url: str
    file_type: str
    captured_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class InspectionMeterReadingResponse(BaseModel):
    id: UUID
    client_uuid: UUID
    unit_id: UUID
    meter_type: str
    previous_reading: Decimal
    current_reading: Decimal
    reading_date: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class InspectionSignatureResponse(BaseModel):
    id: UUID
    signer_name: str
    signer_role: str
    signature_type: str
    signed_at: datetime
    ip_address: Optional[str] = None
    device_fingerprint: Optional[str] = None
    gps_lat: Optional[Decimal] = None
    gps_lng: Optional[Decimal] = None
    created_at: datetime

    class Config:
        from_attributes = True


class InspectionTemplateResponse(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    description: Optional[str] = None
    inspection_type: str
    is_external: bool
    categories: Optional[List[str]] = None
    default_items: Optional[List[dict]] = None
    scoring_enabled: bool
    pass_threshold: Optional[float] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InspectionListResponse(BaseModel):
    id: UUID
    client_uuid: UUID
    property_id: UUID
    unit_id: UUID
    performed_by_id: UUID
    performed_by_role: str
    inspection_type: str
    status: str
    inspection_date: datetime
    notes: Optional[str] = None
    is_external: Optional[bool] = False
    overall_score: Optional[float] = None
    pass_fail: Optional[str] = None
    inspector_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Display fields
    property_name: Optional[str] = None
    unit_number: Optional[str] = None
    performed_by_name: Optional[str] = None

    class Config:
        from_attributes = True


class InspectionDetailResponse(InspectionListResponse):
    gps_lat: Optional[Decimal] = None
    gps_lng: Optional[Decimal] = None
    device_id: Optional[str] = None
    offline_created_at: Optional[datetime] = None
    template_id: Optional[UUID] = None
    inspector_credentials: Optional[str] = None
    inspector_company: Optional[str] = None
    report_url: Optional[str] = None
    items: List[InspectionItemResponse] = []
    media: List[InspectionMediaResponse] = []
    meter_readings: List[InspectionMeterReadingResponse] = []
    signatures: List[InspectionSignatureResponse] = []


class InspectionPaginatedResponse(BaseModel):
    items: List[InspectionListResponse]
    total: int
    page: int
    size: int
    pages: int
