from pydantic import BaseModel, field_validator
from uuid import UUID
from datetime import datetime
from typing import Optional, List
from enum import Enum


class UnitStatusEnum(str, Enum):
    """Valid unit status values for API validation"""
    VACANT = "vacant"
    OCCUPIED = "occupied"
    RENTED = "rented"
    BOUGHT = "bought"
    MORTGAGED = "mortgaged"
    MAINTENANCE = "maintenance"


class UnitBase(BaseModel):
    unit_number: str
    bedrooms: Optional[int] = 1
    bathrooms: Optional[float] = 1.0
    toilets: Optional[int] = 1
    square_feet: Optional[int] = 500
    monthly_rent: Optional[float] = 0
    status: str = "vacant"

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        valid_statuses = [s.value for s in UnitStatusEnum]
        if v and v.lower() not in valid_statuses:
            # Allow the value but normalize to lowercase
            pass
        return v.lower() if v else "vacant"
    # Master bedroom
    has_master_bedroom: Optional[bool] = False
    # Servant Quarters
    has_servant_quarters: Optional[bool] = False
    sq_bathrooms: Optional[int] = 0  # Bathrooms in servant quarters
    # Occupancy type
    occupancy_type: Optional[str] = "available"
    # Description/notes
    description: Optional[str] = None

class UnitCreate(UnitBase):
    pass

class UnitUpdate(BaseModel):
    unit_number: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    toilets: Optional[int] = None
    square_feet: Optional[int] = None
    monthly_rent: Optional[float] = None
    status: Optional[str] = None
    occupancy_type: Optional[str] = None
    has_master_bedroom: Optional[bool] = None
    has_servant_quarters: Optional[bool] = None
    sq_bathrooms: Optional[int] = None
    description: Optional[str] = None

class UnitResponse(UnitBase):
    id: UUID
    property_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

class PropertyBase(BaseModel):
    name: str
    address: str
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = "Kenya"
    property_type: Optional[str] = None
    description: Optional[str] = None
    purchase_price: Optional[float] = None
    purchase_date: Optional[datetime] = None
    image_url: Optional[str] = None

class PropertyCreate(PropertyBase):
    # Unit generation fields (optional - for automatic unit creation)
    total_units: Optional[int] = None  # If set, auto-generates this many units
    unit_prefix: Optional[str] = "Unit"  # Prefix for unit numbers (e.g., "Unit", "Apt", "Suite")
    default_bedrooms: Optional[int] = 1
    default_bathrooms: Optional[float] = 1.0
    default_toilets: Optional[int] = 0  # Separate toilets
    default_rent: Optional[float] = 15000
    default_square_feet: Optional[int] = 500
    # Master bedroom
    default_has_master_bedroom: Optional[bool] = False
    # Servant Quarters defaults
    default_has_servant_quarters: Optional[bool] = False
    default_sq_bathrooms: Optional[int] = 0  # Bathrooms in SQ
    # Unit description template
    default_unit_description: Optional[str] = None  # Description for all generated units

class PropertyUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    property_type: Optional[str] = None
    description: Optional[str] = None
    purchase_price: Optional[float] = None
    purchase_date: Optional[datetime] = None
    image_url: Optional[str] = None

class PropertyResponse(PropertyBase):
    id: UUID
    user_id: UUID
    image_url: Optional[str] = None
    photos: Optional[List[str]] = []
    total_units: Optional[int] = 0
    occupied_units: Optional[int] = 0  # Set by endpoint based on units
    created_at: datetime
    units: List[UnitResponse] = []

    class Config:
        from_attributes = True