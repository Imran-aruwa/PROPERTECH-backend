"""
PROPERTECH Subscription Model
Stores subscription information linked to Stripe
"""

from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.database import Base


class SubscriptionStatus(str, enum.Enum):
    """Subscription status enum"""
    ACTIVE = "active"
    CANCELLED = "cancelled"
    PAST_DUE = "past_due"
    PAUSED = "paused"
    INCOMPLETE = "incomplete"


class BillingCycle(str, enum.Enum):
    """Billing cycle enum"""
    MONTHLY = "monthly"
    ANNUAL = "annual"


class Subscription(Base):
    """
    Subscription model
    Tracks user subscriptions linked to Stripe
    """
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    stripe_subscription_id = Column(String, unique=True, nullable=False, index=True)
    plan = Column(String, nullable=False)  # "starter", "professional", "enterprise"
    billing_cycle = Column(String, default="monthly")  # "monthly" or "annual"
    status = Column(String, default="active")  # active, cancelled, past_due, etc.
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    cancelled_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="subscriptions")
    payments = relationship("Payment", back_populates="subscription")

    def is_active(self) -> bool:
        """Check if subscription is currently active"""
        return self.status == "active"

    def days_until_renewal(self) -> int:
        """Get days until next billing"""
        if self.current_period_end:
            delta = self.current_period_end - datetime.utcnow()
            return delta.days
        return 0

    def __repr__(self):
        return f"<Subscription {self.id} - User {self.user_id} - Plan {self.plan}>"