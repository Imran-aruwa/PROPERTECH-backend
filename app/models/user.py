"""
User Model - Synced with Supabase Auth
Extends Supabase auth_users with custom fields
"""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from app.database import Base


class User(Base):
    """
    User Profile - Extends Supabase Authentication
    
    The user_id matches auth.users.id from Supabase
    This table stores additional profile and payment data
    """
    __tablename__ = "users"

    # Primary key - matches Supabase auth.users.id
    id = Column(UUID(as_uuid=True), primary_key=True)  # UUID from Supabase
    
    # Authentication (from Supabase)
    email = Column(String(255), unique=True, nullable=False, index=True)
    phone = Column(String(20), nullable=True)
    hashed_password = Column(String(255), nullable=True)  # For local auth (optional)
    
    # Profile
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    full_name = Column(String(255), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    
    # Location
    country = Column(String(2), nullable=True)  # ISO country code (KE, US, etc.)
    city = Column(String(100), nullable=True)
    
    # Business
    company_name = Column(String(255), nullable=True)
    business_type = Column(String(50), nullable=True)  # realtor, developer, agency, etc.
    website = Column(String(255), nullable=True)
    
    # Payment
    preferred_currency = Column(String(3), default="KES", nullable=False)
    preferred_gateway = Column(String(50), nullable=True)  # paystack or flutterwave
    payment_method = Column(String(50), nullable=True)  # mpesa, card, etc.
    
    # Account
    status = Column(String(20), default="active", nullable=False)  # active, inactive, suspended
    email_verified = Column(Boolean, default=False)
    phone_verified = Column(Boolean, default=False)
    
    # Custom data
    user_metadata = Column(Text, nullable=True)  # JSON string for custom data
    last_login = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships - Payment related models
    payments = relationship("Payment", back_populates="user")
    subscriptions = relationship("Subscription", back_populates="user")
    invoices = relationship("Invoice", back_populates="user")


class UserPreference(Base):
    """User preferences for notifications and settings"""
    __tablename__ = "user_preferences"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    
    # Email preferences
    email_payment_receipt = Column(Boolean, default=True)
    email_subscription_reminder = Column(Boolean, default=True)
    email_invoice = Column(Boolean, default=True)
    email_marketing = Column(Boolean, default=False)
    
    # Notification preferences
    sms_payment_alert = Column(Boolean, default=False)
    sms_subscription_reminder = Column(Boolean, default=False)
    
    # Payment preferences
    auto_renew_subscription = Column(Boolean, default=True)
    save_payment_method = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)