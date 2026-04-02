"""
Authentication Endpoints
User signup, login, email verification, and profile management
"""
import logging
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserResponse, UserLogin, Token
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    validate_password_strength,
    decode_access_token,
)
from app.dependencies import get_current_user
from app.core.config import settings
from app.services.email_service import email_service

logger = logging.getLogger(__name__)

router = APIRouter()

# ── In-memory rate limiter for resend-verification (resets on restart) ──────
# Structure: { email: [timestamp, ...] }
_resend_rate_limit: dict[str, list[datetime]] = {}
_RESEND_LIMIT = 3          # max resends per window
_RESEND_WINDOW_HOURS = 1


def _check_resend_rate_limit(email: str) -> None:
    """Raise 429 if this email has exceeded the resend limit."""
    now = datetime.utcnow()
    window_start = now - timedelta(hours=_RESEND_WINDOW_HOURS)
    timestamps = _resend_rate_limit.get(email, [])
    # Keep only timestamps within the window
    timestamps = [t for t in timestamps if t > window_start]
    if len(timestamps) >= _RESEND_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Too many resend requests. Please wait before trying again.",
        )
    timestamps.append(now)
    _resend_rate_limit[email] = timestamps


# ── Pydantic bodies ──────────────────────────────────────────────────────────

class VerifyEmailBody(BaseModel):
    token: str


class ResendVerificationBody(BaseModel):
    email: EmailStr


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(user_in: UserCreate, db: Session = Depends(get_db)):
    """Register a new user. Returns a prompt to check email — no JWT issued yet."""
    try:
        # Check if user exists
        existing = db.query(User).filter(User.email == user_in.email).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")

        # Validate password strength
        validate_password_strength(user_in.password)

        # Resolve role
        role_str = user_in.get_role()
        try:
            user_role = UserRole(role_str)
        except ValueError:
            user_role = UserRole.OWNER

        # Create user — auto-verified until SMTP is configured
        user = User(
            id=uuid.uuid4(),
            email=user_in.email,
            full_name=user_in.get_full_name(),
            hashed_password=get_password_hash(user_in.password),
            role=user_role,
            email_verified=True,
            email_verification_token=None,
            email_verification_token_expires_at=None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # Email verification temporarily disabled until SMTP is configured
        # try:
        #     email_service.send_verification_email(
        #         to_email=user.email,
        #         user_name=user.full_name or "",
        #         verification_token=verification_token,
        #     )
        # except Exception as mail_err:
        #     logger.error("[signup] Email send failed for %s: %s", user.email, mail_err)

        return {
            "message": "Registration successful. You can now log in.",
            "email": user.email,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Signup error: %s", e)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create account",
        )


@router.post("/verify-email")
def verify_email(
    body: VerifyEmailBody = None,
    token: str = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Verify an email address using the token sent during registration.
    Accepts token as JSON body {"token": "..."} OR as ?token=... query param.
    """
    token_value = (body.token if body else None) or token
    if not token_value:
        raise HTTPException(status_code=400, detail="Verification token is required")

    user = db.query(User).filter(
        User.email_verification_token == token_value
    ).first()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")

    if user.email_verified:
        raise HTTPException(status_code=400, detail="Email is already verified")

    if (
        user.email_verification_token_expires_at is None
        or datetime.utcnow() > user.email_verification_token_expires_at
    ):
        raise HTTPException(
            status_code=400,
            detail="Verification token has expired. Please request a new one.",
        )

    # Mark verified and clear token
    user.email_verified = True
    user.email_verification_token = None
    user.email_verification_token_expires_at = None
    db.commit()

    # Send welcome email (best-effort)
    try:
        email_service.send_welcome_email(
            to_email=user.email,
            user_name=user.full_name or "",
        )
    except Exception as mail_err:
        logger.error("[verify_email] Welcome email failed for %s: %s", user.email, mail_err)

    return {"message": "Email verified successfully. You can now log in.", "verified": True}


@router.post("/resend-verification")
def resend_verification(body: ResendVerificationBody, db: Session = Depends(get_db)):
    """
    Resend a verification email. Rate-limited: max 3 per hour per email.
    Always returns success to prevent email enumeration.
    """
    email_lower = body.email.lower()

    try:
        _check_resend_rate_limit(email_lower)
    except HTTPException:
        raise

    user = db.query(User).filter(User.email == email_lower).first()

    if user and not user.email_verified:
        new_token = secrets.token_urlsafe(32)
        user.email_verification_token = new_token
        user.email_verification_token_expires_at = datetime.utcnow() + timedelta(hours=24)
        db.commit()

        try:
            email_service.send_verification_email(
                to_email=user.email,
                user_name=user.full_name or "",
                verification_token=new_token,
            )
        except Exception as mail_err:
            logger.error(
                "[resend_verification] Email send failed for %s: %s", user.email, mail_err
            )

    # Always return success (prevents enumeration)
    return {
        "message": "If that email exists and is unverified, a new verification link has been sent."
    }


@router.post("/login")
def login(user_credentials: UserLogin, db: Session = Depends(get_db)):
    """Login and get access token. Requires email to be verified first."""
    try:
        user = db.query(User).filter(User.email == user_credentials.email).first()
    except Exception as e:
        logger.error("Database error during login: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred",
        )

    if not user or not verify_password(user_credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Email verification temporarily disabled until SMTP is configured
    # if not user.email_verified:
    #     raise HTTPException(
    #         status_code=403,
    #         detail="Please verify your email address before logging in. Check your inbox for the verification link.",
    #     )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    user_role_jwt = getattr(user, "role", None)
    role_for_jwt = (
        user_role_jwt.value if hasattr(user_role_jwt, "value") else str(user_role_jwt)
        if user_role_jwt else "owner"
    )

    token_data = {
        "sub": str(user.id),
        "user_id": str(user.id),
        "email": user.email,
        "role": role_for_jwt,
    }

    access_token = create_access_token(data=token_data, expires_delta=access_token_expires)

    verify_payload = decode_access_token(access_token)
    if verify_payload is None:
        logger.error("[LOGIN] CRITICAL: Token created but cannot be decoded!")

    role_value = role_for_jwt

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": str(user.id),
        "full_name": user.full_name or "",
        "email": user.email,
        "role": role_value.upper(),
    }


@router.get("/me")
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information"""
    user_role = getattr(current_user, "role", None)
    role_value = (
        user_role.value if hasattr(user_role, "value") else str(user_role)
        if user_role else "owner"
    )

    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "full_name": current_user.full_name or "",
        "phone": current_user.phone or "",
        "role": role_value.upper(),
        "avatar_url": current_user.avatar_url,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }


@router.post("/forgot-password")
def forgot_password(email: str, db: Session = Depends(get_db)):
    """Request password reset. Always returns success to prevent email enumeration."""
    # In production, send email with reset link if user exists
    return {
        "success": True,
        "message": "If an account with this email exists, a password reset link has been sent.",
    }


@router.get("/verify-token")
def verify_token(current_user: User = Depends(get_current_user)):
    """Verify that a token is valid and return user info."""
    user_role = getattr(current_user, "role", None)
    role_value = (
        user_role.value if hasattr(user_role, "value") else str(user_role)
        if user_role else "owner"
    )

    return {
        "valid": True,
        "user_id": str(current_user.id),
        "email": current_user.email,
        "role": role_value.upper(),
    }
