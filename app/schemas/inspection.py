"""
Inspection Schemas - Pydantic validation for inspection endpoints
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from decimal import Decimal
from pydantic import BaseModel, Field


# === Request Schemas ===

class InspectionItemCreate(BaseModel):
    client_uuid: UUID
    name: str = Field(..., max_length=255)
    category: str = Field(..., pattern="^(plumbing|electrical|structure|cleanliness)$")
    condition: str = Field(..., pattern="^(good|fair|poor)$")
    comment: Optional[str] = None


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
    inspection_type: str = Field(..., pattern="^(routine|move_in|move_out|meter)$")
    inspection_date: datetime
    gps_lat: Optional[Decimal] = None
    gps_lng: Optional[Decimal] = None
    device_id: Optional[str] = None
    offline_created_at: Optional[datetime] = None
    notes: Optional[str] = None


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


# === Response Schemas ===

class InspectionItemResponse(BaseModel):
    id: UUID
    client_uuid: UUID
    name: str
    category: str
    condition: str
    comment: Optional[str] = None
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
    items: List[InspectionItemResponse] = []
    media: List[InspectionMediaResponse] = []
    meter_readings: List[InspectionMeterReadingResponse] = []


class InspectionPaginatedResponse(BaseModel):
    items: List[InspectionListResponse]
    total: int
    page: int
    size: int
    pages: int
