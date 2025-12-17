"""
User Model - Synced with Supabase Auth
Extends Supabase auth_users with custom fields
"""
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, String, DateTime, Boolean, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Uuid
import uuid

from app.db.base import Base

# User Roles for PROPERTECH - matches your routes (admin, owner, staff, etc.)
class UserRole(str, Enum):
    ADMIN = "admin"
    OWNER = "owner"
    STAFF = "staff"
    TENANT = "tenant"
    AGENT = "agent"
    CARETAKER = "caretaker"

class User(Base):
    """
    User Profile - Extends Supabase Authentication
    
    The user_id matches auth.users.id from Supabase
    This table stores additional profile and payment data
    """
    __tablename__ = "users"

    # Primary key - matches Supabase auth.users.id
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    
    # Role field - REQUIRED for dependencies.py
    role: Mapped[UserRole] = mapped_column(SQLEnum(UserRole), default=UserRole.TENANT, index=True)
    
    # Authentication (from Supabase)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=True)  # For local auth (optional)
    
    # Profile
    first_name: Mapped[str] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str] = mapped_column(String(100), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str] = mapped_column(String(500), nullable=True)
    
    # Location
    country: Mapped[str] = mapped_column(String(2), nullable=True)  # ISO country code (KE, US, etc.)
    city: Mapped[str] = mapped_column(String(100), nullable=True)
    
    # Business
    company_name: Mapped[str] = mapped_column(String(255), nullable=True)
    business_type: Mapped[str] = mapped_column(String(50), nullable=True)  # realtor, developer, agency, etc.
    website: Mapped[str] = mapped_column(String(255), nullable=True)
    
    # Payment
    preferred_currency: Mapped[str] = mapped_column(String(3), default="KES", nullable=False)
    preferred_gateway: Mapped[str] = mapped_column(String(50), nullable=True)  # paystack or flutterwave
    payment_method: Mapped[str] = mapped_column(String(50), nullable=True)  # mpesa, card, etc.
    
    # Account
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active, inactive, suspended
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Custom data
    user_metadata: Mapped[str] = mapped_column(Text, nullable=True)  # JSON string for custom data
    last_login: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships - Payment related models
    payments = relationship("Payment", back_populates="user")
    subscriptions = relationship("Subscription", back_populates="user")
    invoices = relationship("Invoice", back_populates="user")
    tenants = relationship("Tenant", back_populates="user")

class UserPreference(Base):
    """User preferences for notifications and settings"""
    __tablename__ = "user_preferences"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, index=True)
    
    # Email preferences
    email_payment_receipt: Mapped[bool] = mapped_column(Boolean, default=True)
    email_subscription_reminder: Mapped[bool] = mapped_column(Boolean, default=True)
    email_invoice: Mapped[bool] = mapped_column(Boolean, default=True)
    email_marketing: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Notification preferences
    sms_payment_alert: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_subscription_reminder: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Payment preferences
    auto_renew_subscription: Mapped[bool] = mapped_column(Boolean, default=True)
    save_payment_method: Mapped[bool] = mapped_column(Boolean, default=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
