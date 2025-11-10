from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional, List

class UnitBase(BaseModel):
    unit_number: str
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    square_feet: Optional[int] = None
    monthly_rent: Optional[float] = None
    status: str = "vacant"

class UnitCreate(UnitBase):
    pass

class UnitUpdate(BaseModel):
    unit_number: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    square_feet: Optional[int] = None
    monthly_rent: Optional[float] = None
    status: Optional[str] = None

class UnitResponse(UnitBase):
    id: UUID
    property_id: UUID
    created_at: datetime
    
    class Config:
        from_attributes = True

class PropertyBase(BaseModel):
    name: str
    address: str
    property_type: Optional[str] = None
    description: Optional[str] = None
    purchase_price: Optional[float] = None
    purchase_date: Optional[datetime] = None

class PropertyCreate(PropertyBase):
    pass

class PropertyUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    property_type: Optional[str] = None
    description: Optional[str] = None
    purchase_price: Optional[float] = None
    purchase_date: Optional[datetime] = None

class PropertyResponse(PropertyBase):
    id: UUID
    user_id: UUID
    photos: Optional[List[str]] = []
    created_at: datetime
    units: List[UnitResponse] = []
    
    class Config:
        from_attributes = True