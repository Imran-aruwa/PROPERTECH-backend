"""
Seed / verify subscription plan configuration.

The system uses SubscriptionPlan enum values (not a separate plans table).
This script documents the plan configuration and verifies the Paystack plan
codes are set. Run as a one-off check or import from main startup.

Usage:
    python -m app.seeds.seed_plans
"""
import os
import logging

logger = logging.getLogger(__name__)

PLANS = [
    {
        "slug": "starter",
        "name": "Starter",
        "description": "Perfect for individual landlords",
        "price_monthly_kes": 6468,
        "price_yearly_kes": 64680,
        "max_properties": 1,
        "max_units": 10,
        "features": [
            "Up to 1 property",
            "Up to 10 units",
            "Basic dashboard",
            "Tenant management",
            "Maintenance tracking",
            "Email support",
        ],
        "paystack_plan_code_env": None,   # Free tier — no Paystack plan code required
    },
    {
        "slug": "professional",
        "name": "Professional",
        "description": "For growing property portfolios",
        "price_monthly_kes": 13068,
        "price_yearly_kes": 130680,
        "max_properties": -1,   # unlimited
        "max_units": -1,        # unlimited
        "features": [
            "Unlimited properties",
            "Unlimited units",
            "Advanced analytics",
            "M-Pesa integration",
            "Document management",
            "Priority support",
        ],
        "paystack_plan_code_env": "PAYSTACK_PLAN_CODE_PROFESSIONAL",
    },
    {
        "slug": "enterprise",
        "name": "Enterprise",
        "description": "For large real-estate organisations",
        "price_monthly_kes": 29900,
        "price_yearly_kes": 299000,
        "max_properties": -1,
        "max_units": -1,
        "features": [
            "Everything in Professional",
            "AI-powered features (ARIA, Tenant Intelligence)",
            "White-label support",
            "24/7 priority support",
            "Custom integrations",
        ],
        "paystack_plan_code_env": "PAYSTACK_PLAN_CODE_ENTERPRISE",
    },
]


def verify_plan_codes() -> list[str]:
    """
    Check that Paystack plan codes are set for paid plans.
    Returns a list of warning messages for any missing codes.
    """
    warnings: list[str] = []
    for plan in PLANS:
        env_key = plan.get("paystack_plan_code_env")
        if env_key:
            value = os.getenv(env_key, "")
            if not value:
                warnings.append(
                    f"[seed_plans] WARNING: {env_key} is not set. "
                    f"Paystack recurring billing for '{plan['name']}' will not work."
                )
    return warnings


def print_plan_summary() -> None:
    """Print a summary of all plans to the log."""
    logger.info("=== PROPERTECH Subscription Plans ===")
    for plan in PLANS:
        limits = (
            f"{plan['max_properties']} props / {plan['max_units']} units"
            if plan["max_properties"] != -1
            else "unlimited props & units"
        )
        logger.info(
            "  [%s] %s — KES %s/mo | %s",
            plan["slug"].upper(),
            plan["name"],
            f"{plan['price_monthly_kes']:,}",
            limits,
        )

    for warning in verify_plan_codes():
        logger.warning(warning)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print_plan_summary()
