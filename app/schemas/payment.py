"""
Payment Request/Response Schemas
Pydantic models for payment API validation
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class PaymentGatewayEnum(str, Enum):
    PAYSTACK = "paystack"


class PaymentMethodEnum(str, Enum):
    MPESA = "mpesa"
    KES_CARD = "kes_card"
    USD_CARD = "usd_card"
    APPLE_PAY = "apple_pay"
    GOOGLE_PAY = "google_pay"


class CurrencyEnum(str, Enum):
    KES = "KES"
    USD = "USD"
    UGX = "UGX"
    NGN = "NGN"
    GHS = "GHS"
    TZS = "TZS"


class BillingCycleEnum(str, Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class PlanEnum(str, Enum):
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


# ==================== Gateway Detection ====================

class DetectGatewayRequest(BaseModel):
    country_code: Optional[str] = None
    phone_number: Optional[str] = None
    ip_address: Optional[str] = None


class DetectGatewayResponse(BaseModel):
    success: bool
    data: dict = Field(
        example={
            "country_code": "KE",
            "currency": "KES",
            "gateway": "paystack",
            "method": "mpesa"
        }
    )
    available_methods: List[str]


# ==================== Payment Initiation ====================

class InitiatePaymentRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Payment amount")
    plan_id: Optional[str] = Field(None, description="Plan ID (starter, professional, enterprise)")
    gateway: Optional[PaymentGatewayEnum] = None
    currency: Optional[CurrencyEnum] = None
    method: Optional[PaymentMethodEnum] = None
    country_code: Optional[str] = None
    ip_address: Optional[str] = None
    description: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "amount": 2900,
                "plan_id": "starter",
                "description": "Starter plan subscription"
            }
        }


class InitiatePaymentResponse(BaseModel):
    success: bool
    payment_id: str
    reference: str
    gateway: str
    authorization_url: str
    access_code: Optional[str] = None
    amount: float
    currency: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "payment_id": "550e8400-e29b-41d4-a716-446655440000",
                "reference": "propertech_abc123def456",
                "gateway": "paystack",
                "authorization_url": "https://checkout.paystack.com/...",
                "access_code": "access_code_here",
                "amount": 2900,
                "currency": "KES"
            }
        }


# ==================== Payment Verification ====================

class VerifyPaymentRequest(BaseModel):
    reference: str = Field(..., description="Payment reference from initiation")
    gateway_transaction_id: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "reference": "propertech_abc123def456"
            }
        }


class PaymentResponse(BaseModel):
    id: str
    user_id: str
    amount: float
    currency: str
    gateway: str
    method: str
    reference: str
    status: str
    plan_id: Optional[str] = None
    created_at: datetime
    paid_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# ==================== Subscription ====================

class SubscriptionRequest(BaseModel):
    plan: PlanEnum = Field(..., description="Subscription plan")
    billing_cycle: BillingCycleEnum = Field(..., description="monthly or yearly")
    gateway: Optional[PaymentGatewayEnum] = None
    currency: Optional[CurrencyEnum] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "plan": "professional",
                "billing_cycle": "monthly"
            }
        }


class SubscriptionResponse(BaseModel):
    id: str
    user_id: str
    plan: str
    billing_cycle: str
    amount: float
    currency: str
    status: str
    gateway: str
    start_date: datetime
    next_billing_date: Optional[datetime] = None
    payment_count: int
    
    class Config:
        from_attributes = True


class SubscriptionListResponse(BaseModel):
    success: bool
    subscriptions: List[SubscriptionResponse]


# ==================== Payment History ====================

class PaymentHistoryResponse(BaseModel):
    success: bool
    payments: List[PaymentResponse]
    total: int = 0


# ==================== Invoice ====================

class InvoiceResponse(BaseModel):
    id: str
    invoice_number: str
    amount: float
    currency: str
    status: str
    issue_date: datetime
    due_date: Optional[datetime] = None
    paid_date: Optional[datetime] = None
    description: Optional[str] = None
    
    class Config:
        from_attributes = True


# ==================== Webhook ====================

class WebhookPaystackRequest(BaseModel):
    event: str
    data: dict


class WebhookFlutterwaveRequest(BaseModel):
    event: str
    data: dict


class WebhookResponse(BaseModel):
    success: bool
    message: str


# ==================== Error Response ====================

class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": False,
                "error": "Payment failed",
                "detail": "Insufficient funds"
            }
        }


# ==================== Cancel Subscription ====================

class CancelSubscriptionResponse(BaseModel):
    success: bool
    message: str
    subscription_id: Optional[str] = None


# ==================== Payment Status ====================

class PaymentStatusResponse(BaseModel):
    success: bool
    payment_id: str
    status: str
    reference: str
    amount: float
    currency: str
    gateway: str
    created_at: datetime
    paid_at: Optional[datetime] = None