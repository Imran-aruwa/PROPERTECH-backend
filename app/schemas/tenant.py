"""
Tenant Pydantic Schemas - API Request/Response Models
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from uuid import UUID
from enum import Enum

from app.models.user import UserRole
from app.models.payment import PaymentStatus, PaymentType
from app.models.maintenance import MaintenanceStatus, MaintenancePriority


# ==================== Tenant Schemas ====================

class TenantBase(BaseModel):
    full_name: str
    email: str
    phone: str
    user_id: Optional[UUID] = None
    unit_id: Optional[UUID] = None
    property_id: Optional[UUID] = None


# Schema for creating a tenant user inline (from frontend)
class TenantUserCreate(BaseModel):
    full_name: str
    email: str
    phone: Optional[str] = None
    id_number: Optional[str] = None
    password: Optional[str] = "TempPass123!"
    role: Optional[str] = "tenant"


class TenantCreate(BaseModel):
    """
    Accepts BOTH formats:
    1. Frontend format: { user: {...}, unit_id, lease_start, lease_end, rent_amount, ... }
    2. Direct format: { full_name, email, phone, user_id, unit_id, lease_start, rent_amount, ... }
    """
    # Option 1: Nested user object (frontend sends this)
    user: Optional[TenantUserCreate] = None

    # Option 2: Direct fields
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    user_id: Optional[UUID] = None
    id_number: Optional[str] = None

    # Unit/Property assignment
    unit_id: Optional[str] = None
    property_id: Optional[str] = None

    # Lease details
    rent_amount: Optional[float] = None
    deposit_amount: Optional[float] = 0
    lease_start: Optional[str] = None
    lease_end: Optional[str] = None
    move_in_date: Optional[str] = None
    move_out_date: Optional[str] = None

    # Emergency contact
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    next_of_kin: Optional[str] = None
    nok_phone: Optional[str] = None

    # Additional
    notes: Optional[str] = None
    occupancy_type: Optional[str] = "renting"  # renting | mortgaging | buying


class TenantUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    rent_amount: Optional[float] = None
    lease_end: Optional[datetime] = None
    status: Optional[str] = None
    move_out_date: Optional[datetime] = None
    next_of_kin: Optional[str] = None
    nok_phone: Optional[str] = None
    occupancy_type: Optional[str] = None


class TenantResponse(BaseModel):
    id: UUID
    full_name: str
    email: str
    phone: Optional[str] = None
    user_id: Optional[UUID] = None
    unit_id: Optional[UUID] = None
    property_id: Optional[UUID] = None
    status: Optional[str] = "active"
    balance_due: Optional[float] = 0.0
    rent_amount: Optional[float] = None
    deposit_amount: Optional[float] = None
    lease_start: Optional[datetime] = None
    lease_end: Optional[datetime] = None
    move_in_date: Optional[datetime] = None
    move_out_date: Optional[datetime] = None
    id_number: Optional[str] = None
    next_of_kin: Optional[str] = None
    nok_phone: Optional[str] = None
    occupancy_type: Optional[str] = "renting"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==================== Payment Schemas ====================

class TenantPaymentResponse(BaseModel):
    id: UUID
    amount: float
    currency: Optional[str] = "KES"
    status: Optional[str] = None
    payment_type: Optional[str] = None
    reference: Optional[str] = None
    created_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==================== Maintenance Schemas ====================

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
    status: Optional[str] = None
    priority: Optional[str] = None
    tenant_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
