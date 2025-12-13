"""
Tenant Pydantic Schemas - API Request/Response Models
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from uuid import UUID
from enum import Enum

from app.models.user import UserRole
from app.models.payment import PaymentStatus, PaymentType
from app.models.maintenance import MaintenanceStatus, MaintenancePriority

# Tenant Schemas
class TenantBase(BaseModel):
    full_name: str
    email: str
    phone: str
    user_id: UUID
    unit_id: Optional[UUID] = None
    property_id: Optional[UUID] = None

class TenantCreate(TenantBase):
    rent_amount: float
    lease_start: datetime
    move_in_date: datetime

class TenantUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    rent_amount: Optional[float] = None
    lease_end: Optional[datetime] = None

class TenantResponse(TenantBase):
    id: UUID
    status: str
    balance_due: float
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

# Payment Schemas
class TenantPaymentResponse(BaseModel):
    id: UUID
    amount: float
    currency: str
    status: PaymentStatus
    payment_type: PaymentType
    gateway_reference: str
    created_at: datetime
    paid_at: Optional[datetime]
    
    class Config:
        from_attributes = True

# Maintenance Schemas
class MaintenancePriorityEnum(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"

class MaintenanceRequestCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=10)
    priority: MaintenancePriorityEnum = "medium"

class TenantMaintenanceResponse(BaseModel):
    id: UUID
    title: str
    description: str
    status: MaintenanceStatus
    priority: MaintenancePriorityEnum
    tenant_id: UUID
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True
