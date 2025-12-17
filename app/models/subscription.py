# Subscription model is defined in payment.py to avoid duplicate table definitions
# Re-export for backward compatibility
from app.models.payment import Subscription, SubscriptionStatus, SubscriptionPlan

__all__ = ["Subscription", "SubscriptionStatus", "SubscriptionPlan"]