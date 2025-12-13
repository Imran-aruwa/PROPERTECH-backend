"""
Meter Reading Pydantic Schemas - API Request/Response Models
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from uuid import UUID

class MeterReadingBase(BaseModel):
    unit_id: UUID
    water_reading: Optional[float] = None
    electricity_reading: Optional[float] = None
    notes: Optional[str] = None

class MeterReadingCreate(MeterReadingBase):
    reading_date: datetime = Field(..., description="Date of meter reading")
    water_reading: float = Field(..., gt=0, description="Water meter reading (m³)")
    electricity_reading: float = Field(..., gt=0, description="Electricity meter reading (kWh)")

class MeterReadingResponse(MeterReadingBase):
    id: UUID
    reading_date: datetime
    water_reading: float
    electricity_reading: float
    notes: Optional[str] = None
    recorded_by: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True

class MeterReadingUpdate(BaseModel):
    water_reading: Optional[float] = Field(None, gt=0)
    electricity_reading: Optional[float] = Field(None, gt=0)
    notes: Optional[str] = None
    reading_date: Optional[datetime] = None
    