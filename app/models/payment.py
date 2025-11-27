"""
Payment Models
Database models for payments, subscriptions, invoices, and gateway logs
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from app.database import Base


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
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # User info
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    user_email = Column(String(255), nullable=False)
    user_phone = Column(String(20), nullable=True)
    
    # Payment details
    amount = Column(Float, nullable=False)
    currency = Column(SQLEnum(PaymentCurrency), default=PaymentCurrency.KES, nullable=False)
    gateway = Column(SQLEnum(PaymentGateway), nullable=False)
    method = Column(SQLEnum(PaymentMethod), nullable=False)
    
    # Transaction references
    reference = Column(String(255), unique=True, nullable=False)
    transaction_id = Column(String(255), nullable=True)
    gateway_response = Column(Text, nullable=True)
    
    # Status
    status = Column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False)
    
    # Related to subscription or one-time
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=True)
    plan_id = Column(String(50), nullable=True)
    
    # Location for auto-detection
    user_country = Column(String(2), nullable=True)
    user_ip = Column(String(45), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    paid_at = Column(DateTime, nullable=True)
    
    # Description
    description = Column(String(500), nullable=True)
    payment_metadata = Column(Text, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="payments")
    subscription = relationship("Subscription", back_populates="payments")
    invoices = relationship("Invoice", back_populates="payment")
    logs = relationship("PaymentGatewayLog", back_populates="payment")


class Subscription(Base):
    """Subscription/recurring billing record"""
    __tablename__ = "subscriptions"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # User info
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # Subscription details
    plan = Column(SQLEnum(SubscriptionPlan), nullable=False)
    status = Column(SQLEnum(SubscriptionStatus), default=SubscriptionStatus.PENDING, nullable=False)
    
    # Billing
    currency = Column(SQLEnum(PaymentCurrency), default=PaymentCurrency.KES, nullable=False)
    billing_cycle = Column(String(20), nullable=False)
    amount = Column(Float, nullable=False)
    
    # Gateway subscription reference
    gateway = Column(SQLEnum(PaymentGateway), nullable=False)
    gateway_subscription_id = Column(String(255), nullable=True)
    gateway_customer_id = Column(String(255), nullable=True)
    
    # Dates
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=True)
    next_billing_date = Column(DateTime, nullable=True)
    last_payment_date = Column(DateTime, nullable=True)
    
    # Tracking
    payment_count = Column(Integer, default=0)
    failed_attempts = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    cancelled_at = Column(DateTime, nullable=True)
    
    # Custom data
    subscription_metadata = Column(Text, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="subscriptions")
    payments = relationship("Payment", back_populates="subscription")
    invoices = relationship("Invoice", back_populates="subscription")


class Invoice(Base):
    """Invoice record for payments/subscriptions"""
    __tablename__ = "invoices"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # References
    payment_id = Column(UUID(as_uuid=True), ForeignKey("payments.id"), nullable=False)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # Invoice details
    invoice_number = Column(String(50), unique=True, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(SQLEnum(PaymentCurrency), nullable=False)
    
    # Status
    status = Column(String(20), default="issued")
    
    # Dates
    issue_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    due_date = Column(DateTime, nullable=True)
    paid_date = Column(DateTime, nullable=True)
    
    # Description
    description = Column(Text, nullable=True)
    items = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    payment = relationship("Payment", back_populates="invoices")
    subscription = relationship("Subscription", back_populates="invoices")
    user = relationship("User", back_populates="invoices")


class PaymentGatewayLog(Base):
    """Audit log for all payment gateway interactions"""
    __tablename__ = "payment_gateway_logs"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # References
    payment_id = Column(UUID(as_uuid=True), ForeignKey("payments.id"), nullable=False)
    
    # Request/Response
    gateway = Column(SQLEnum(PaymentGateway), nullable=False)
    action = Column(String(100), nullable=False)
    request_data = Column(Text, nullable=True)
    response_data = Column(Text, nullable=True)
    status_code = Column(Integer, nullable=True)
    
    # Error tracking
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    payment = relationship("Payment", back_populates="logs")