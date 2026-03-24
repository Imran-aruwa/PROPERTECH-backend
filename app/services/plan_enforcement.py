"""
Plan Enforcement — checks subscription limits before allowing property/unit creation.

Plan limits:
  starter      : 1 property,  10 units
  professional : unlimited
  enterprise   : unlimited
"""
import logging
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.payment import Subscription, SubscriptionStatus, SubscriptionPlan
from app.models.property import Property, Unit

logger = logging.getLogger(__name__)

# Hard-coded limits per plan
PLAN_LIMITS: dict[str, dict] = {
    SubscriptionPlan.STARTER: {"max_properties": 1, "max_units": 10},
    SubscriptionPlan.PROFESSIONAL: {"max_properties": -1, "max_units": -1},
    SubscriptionPlan.ENTERPRISE: {"max_properties": -1, "max_units": -1},
}

_DEFAULT_LIMITS = {"max_properties": 1, "max_units": 10}   # free / no subscription


def _get_active_plan(user_id, db: Session) -> str:
    """Return the active plan slug for a user, or 'starter' if none."""
    sub = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
        .order_by(Subscription.created_at.desc())
        .first()
    )
    if sub:
        plan_val = sub.plan.value if hasattr(sub.plan, "value") else str(sub.plan)
        return plan_val
    return SubscriptionPlan.STARTER.value


def check_property_limit(user, db: Session) -> None:
    """
    Raise HTTP 403 if the user has reached their plan's property limit.
    Call this before creating a new Property.
    """
    plan_slug = _get_active_plan(user.id, db)
    limits = PLAN_LIMITS.get(plan_slug, _DEFAULT_LIMITS)
    max_props = limits["max_properties"]

    if max_props == -1:
        return  # unlimited

    current = db.query(Property).filter(Property.user_id == user.id).count()
    if current >= max_props:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Your {plan_slug.capitalize()} plan allows {max_props} "
                f"{'property' if max_props == 1 else 'properties'}. "
                f"Please upgrade to add more."
            ),
        )


def check_unit_limit(user, db: Session) -> None:
    """
    Raise HTTP 403 if the user has reached their plan's unit limit.
    Call this before creating a new Unit.
    """
    plan_slug = _get_active_plan(user.id, db)
    limits = PLAN_LIMITS.get(plan_slug, _DEFAULT_LIMITS)
    max_units = limits["max_units"]

    if max_units == -1:
        return  # unlimited

    current = (
        db.query(Unit)
        .join(Property, Unit.property_id == Property.id)
        .filter(Property.user_id == user.id)
        .count()
    )
    if current >= max_units:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Your {plan_slug.capitalize()} plan allows {max_units} units. "
                f"Please upgrade to add more."
            ),
        )
