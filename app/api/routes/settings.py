"""
Settings Routes - User Profile, Notifications, Password, Billing, Account
All roles can access their own settings
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr
import uuid

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserPreference
from app.models.payment import Subscription, SubscriptionStatus
from app.core.security import verify_password, get_password_hash

router = APIRouter(tags=["settings"])


# ==================== SCHEMAS ====================

class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class NotificationSettings(BaseModel):
    email_notifications: bool = True
    sms_notifications: bool = False
    push_notifications: bool = True
    payment_reminders: bool = True
    maintenance_updates: bool = True
    marketing_emails: bool = False


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


# ==================== PROFILE ====================

@router.get("/profile")
def get_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current user's profile"""
    return {
        "success": True,
        "full_name": current_user.full_name or "",
        "email": current_user.email,
        "phone": current_user.phone or "",
        "avatar_url": current_user.avatar_url
    }


@router.put("/profile")
def update_profile(
    profile_data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update current user's profile"""
    if profile_data.full_name is not None:
        current_user.full_name = profile_data.full_name

    if profile_data.email is not None:
        # Check if email is already taken
        existing = db.query(User).filter(
            User.email == profile_data.email,
            User.id != current_user.id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")
        current_user.email = profile_data.email

    if profile_data.phone is not None:
        current_user.phone = profile_data.phone

    current_user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(current_user)

    return {
        "success": True,
        "message": "Profile updated successfully",
        "full_name": current_user.full_name,
        "email": current_user.email,
        "phone": current_user.phone
    }


# ==================== NOTIFICATIONS ====================

@router.get("/notifications")
def get_notification_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get notification preferences"""
    prefs = db.query(UserPreference).filter(UserPreference.user_id == current_user.id).first()

    if not prefs:
        # Return defaults
        return {
            "success": True,
            "email_notifications": True,
            "sms_notifications": False,
            "push_notifications": True,
            "payment_reminders": True,
            "maintenance_updates": True,
            "marketing_emails": False
        }

    return {
        "success": True,
        "email_notifications": prefs.email_payment_receipt,
        "sms_notifications": prefs.sms_payment_alert,
        "push_notifications": True,
        "payment_reminders": prefs.email_subscription_reminder,
        "maintenance_updates": True,
        "marketing_emails": prefs.email_marketing
    }


@router.put("/notifications")
def update_notification_settings(
    settings: NotificationSettings,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update notification preferences"""
    prefs = db.query(UserPreference).filter(UserPreference.user_id == current_user.id).first()

    if not prefs:
        prefs = UserPreference(
            id=uuid.uuid4(),
            user_id=current_user.id
        )
        db.add(prefs)

    prefs.email_payment_receipt = settings.email_notifications
    prefs.sms_payment_alert = settings.sms_notifications
    prefs.email_subscription_reminder = settings.payment_reminders
    prefs.email_marketing = settings.marketing_emails
    prefs.updated_at = datetime.utcnow()

    db.commit()

    return {
        "success": True,
        "message": "Notification settings updated successfully"
    }


# ==================== PASSWORD ====================

@router.post("/change-password")
def change_password(
    password_data: PasswordChange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Change current user's password"""
    # Verify current password
    if not verify_password(password_data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    # Validate new password
    if len(password_data.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # Update password
    current_user.hashed_password = get_password_hash(password_data.new_password)
    current_user.updated_at = datetime.utcnow()
    db.commit()

    return {
        "success": True,
        "message": "Password changed successfully"
    }


# ==================== BILLING ====================

@router.get("/billing")
def get_billing_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get billing information"""
    # Get active subscription
    subscription = db.query(Subscription).filter(
        Subscription.user_id == current_user.id,
        Subscription.status == SubscriptionStatus.ACTIVE
    ).first()

    if not subscription:
        return {
            "success": True,
            "plan": "free",
            "billing_cycle": None,
            "next_billing_date": None,
            "payment_method": current_user.payment_method
        }

    return {
        "success": True,
        "plan": subscription.plan,
        "billing_cycle": subscription.billing_cycle,
        "next_billing_date": subscription.next_billing_date.isoformat() if subscription.next_billing_date else None,
        "payment_method": current_user.payment_method or "card"
    }


# ==================== ACCOUNT DELETION ====================

@router.delete("/account")
def delete_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete user account (soft delete by marking inactive)"""
    # Soft delete - mark as inactive
    current_user.status = "deleted"
    current_user.email = f"deleted_{current_user.id}@deleted.local"
    current_user.updated_at = datetime.utcnow()

    # Cancel any active subscriptions
    subscriptions = db.query(Subscription).filter(
        Subscription.user_id == current_user.id,
        Subscription.status == SubscriptionStatus.ACTIVE
    ).all()

    for sub in subscriptions:
        sub.status = SubscriptionStatus.CANCELLED
        sub.cancelled_at = datetime.utcnow()

    db.commit()

    return {
        "success": True,
        "message": "Account deleted successfully"
    }
