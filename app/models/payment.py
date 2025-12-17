"""
Payment Models
Database models for payments, subscriptions, invoices, and gateway logs
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, ForeignKey, Text, Enum as SQLEnum, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
import uuid

from app.db.base import Base

class PaymentStatus(str, Enum):
    """Payment status enum"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"

class PaymentGateway(str, Enum):
    """Payment gateway enum"""
    PAYSTACK = "paystack"
    FLUTTERWAVE = "flutterwave"

class PaymentCurrency(str, Enum):
    """Supported currencies"""
    KES = "KES"
    USD = "USD"
    UGX = "UGX"
    NGN = "NGN"

class PaymentMethod(str, Enum):
    """Payment method enum"""
    MPESA = "mpesa"
    KES_CARD = "kes_card"
    USD_CARD = "usd_card"
    APPLE_PAY = "apple_pay"
    GOOGLE_PAY = "google_pay"

# ✅ ADDED: PaymentType - fixes tenants.py import
class PaymentType(str, Enum):
    """Payment type enum"""
    RENT = "rent"
    DEPOSIT = "deposit"
    MAINTENANCE = "maintenance"
    PENALTY = "penalty"
    SUBSCRIPTION = "subscription"
    ONE_OFF = "one_off"

class SubscriptionStatus(str, Enum):
    """Subscription status enum"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    CANCELLED = "cancelled"
    PENDING = "pending"
    EXPIRED = "expired"

class SubscriptionPlan(str, Enum):
    """Subscription plan types"""
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"

class Payment(Base):
    """Payment transaction record"""
    __tablename__ = "payments"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    
    # User info
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    user_email: Mapped[str] = mapped_column(String(255), nullable=False)
    user_phone: Mapped[str] = mapped_column(String(20), nullable=True)
    
    # Payment details
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[PaymentCurrency] = mapped_column(SQLEnum(PaymentCurrency), default=PaymentCurrency.KES, nullable=False)
    gateway: Mapped[PaymentGateway] = mapped_column(SQLEnum(PaymentGateway), nullable=False)
    method: Mapped[PaymentMethod] = mapped_column(SQLEnum(PaymentMethod), nullable=False)
    
    # Transaction references
    reference: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    transaction_id: Mapped[str] = mapped_column(String(255), nullable=True)
    gateway_response: Mapped[str] = mapped_column(Text, nullable=True)
    
    # Status
    status: Mapped[PaymentStatus] = mapped_column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False)
    
    # Related to subscription or one-time
    subscription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("subscriptions.id"), nullable=True)
    plan_id: Mapped[str] = mapped_column(String(50), nullable=True)
    
    # Location for auto-detection
    user_country: Mapped[str] = mapped_column(String(2), nullable=True)
    user_ip: Mapped[str] = mapped_column(String(45), nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    paid_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    
    # Description
    description: Mapped[str] = mapped_column(String(500), nullable=True)
    payment_metadata: Mapped[str] = mapped_column(Text, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="payments")
    subscription = relationship("Subscription", back_populates="payments")
    invoices = relationship("Invoice", back_populates="payment")
    logs = relationship("PaymentGatewayLog", back_populates="payment")

class Subscription(Base):
    """Subscription/recurring billing record"""
    __tablename__ = "subscriptions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    
    # User info
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    
    # Subscription details
    plan: Mapped[SubscriptionPlan] = mapped_column(SQLEnum(SubscriptionPlan), nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(SQLEnum(SubscriptionStatus), default=SubscriptionStatus.PENDING, nullable=False)
    
    # Billing
    currency: Mapped[PaymentCurrency] = mapped_column(SQLEnum(PaymentCurrency), default=PaymentCurrency.KES, nullable=False)
    billing_cycle: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    
    # Gateway subscription reference
    gateway: Mapped[PaymentGateway] = mapped_column(SQLEnum(PaymentGateway), nullable=False)
    gateway_subscription_id: Mapped[str] = mapped_column(String(255), nullable=True)
    gateway_customer_id: Mapped[str] = mapped_column(String(255), nullable=True)
    
    # Dates
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    next_billing_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    last_payment_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    
    # Tracking
    payment_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    cancelled_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    
    # Custom data
    subscription_metadata: Mapped[str] = mapped_column(Text, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="subscriptions")
    payments = relationship("Payment", back_populates="subscription")
    invoices = relationship("Invoice", back_populates="subscription")

class Invoice(Base):
    """Invoice record for payments/subscriptions"""
    __tablename__ = "invoices"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    
    # References
    payment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("payments.id"), nullable=False)
    subscription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("subscriptions.id"), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    
    # Invoice details
    invoice_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[PaymentCurrency] = mapped_column(SQLEnum(PaymentCurrency), nullable=False)
    
    # Status
    status: Mapped[str] = mapped_column(String(20), default="issued")
    
    # Dates
    issue_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    due_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    paid_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    
    # Description
    description: Mapped[str] = mapped_column(Text, nullable=True)
    items: Mapped[str] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    payment = relationship("Payment", back_populates="invoices")
    subscription = relationship("Subscription", back_populates="invoices")
    user = relationship("User", back_populates="invoices")

class PaymentGatewayLog(Base):
    """Audit log for all payment gateway interactions"""
    __tablename__ = "payment_gateway_logs"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    
    # References
    payment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("payments.id"), nullable=False)
    
    # Request/Response
    gateway: Mapped[PaymentGateway] = mapped_column(SQLEnum(PaymentGateway), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    request_data: Mapped[str] = mapped_column(Text, nullable=True)
    response_data: Mapped[str] = mapped_column(Text, nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=True)
    
    # Error tracking
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    payment = relationship("Payment", back_populates="logs")
