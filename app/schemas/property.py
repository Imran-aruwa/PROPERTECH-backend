from pydantic import BaseModel, model_validator
from uuid import UUID
from datetime import datetime
from typing import Optional, List, Any

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
    default_rent: Optional[float] = None
    default_square_feet: Optional[int] = None

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
    occupied_units: Optional[int] = 0  # Computed from units with status="occupied"
    created_at: datetime
    units: List[UnitResponse] = []

    class Config:
        from_attributes = True

    @model_validator(mode='before')
    @classmethod
    def compute_occupied_units(cls, data: Any) -> Any:
        """Compute occupied_units from units list"""
        if hasattr(data, '__dict__'):
            # SQLAlchemy model
            if hasattr(data, 'units') and data.units:
                occupied = sum(1 for u in data.units if u.status == "occupied")
                # Create a dict to modify
                data_dict = {key: getattr(data, key) for key in dir(data) if not key.startswith('_')}
                data_dict['occupied_units'] = occupied
                return data_dict
        elif isinstance(data, dict):
            units = data.get('units', [])
            if units:
                data['occupied_units'] = sum(1 for u in units if (u.get('status') if isinstance(u, dict) else u.status) == "occupied")
        return data