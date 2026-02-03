"""
Security and Authentication
Handles password hashing, JWT tokens, and user verification
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from starlette.requests import Request
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import timedelta, datetime
from typing import Optional
import logging

from app.database import get_db
from app.core.config import settings

logger = logging.getLogger(__name__)

# HTTP Bearer scheme for JWT
security = HTTPBearer()

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ============================================================================
# PASSWORD VALIDATION
# ============================================================================

def validate_password_strength(password: str) -> None:
    """Validate password meets minimum strength requirements.
    Raises HTTPException if password is too weak."""
    import re
    if len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters",
        )
    if not re.search(r"[A-Z]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one uppercase letter",
        )
    if not re.search(r"[a-z]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one lowercase letter",
        )
    if not re.search(r"\d", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one number",
        )


# ============================================================================
# PASSWORD HASHING FUNCTIONS
# ============================================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against hashed password"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt"""
    return pwd_context.hash(password)


# ============================================================================
# JWT TOKEN FUNCTIONS
# ============================================================================

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create JWT access token
    
    Args:
        data: Data to encode in token (usually user id, email, role)
        expires_delta: Token expiration time
        
    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decode and verify JWT token
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded token payload or None if invalid
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        return None


# ============================================================================
# USER VERIFICATION DEPENDENCIES
# ============================================================================

def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
):
    """Get current authenticated user from JWT token.
    Thin wrapper that delegates to the canonical implementation in app.dependencies."""
    from app.dependencies import get_current_user as _get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )
    token = auth_header.split(" ", 1)[1]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return _get_current_user(credentials=credentials, db=db)


def verify_admin(user = Depends(get_current_user)):
    """
    Verify user is admin
    
    Args:
        user: Current user
        
    Returns:
        User if admin
        
    Raises:
        HTTPException: If user is not admin
    """
    if user.role != "admin" and user.business_type != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


def verify_email(user = Depends(get_current_user)):
    """
    Verify user email is confirmed
    
    Args:
        user: Current user
        
    Returns:
        User if email verified
        
    Raises:
        HTTPException: If email not verified
    """
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required"
        )
    return user


def verify_phone(user = Depends(get_current_user)):
    """
    Verify user phone is confirmed
    
    Args:
        user: Current user
        
    Returns:
        User if phone verified
        
    Raises:
        HTTPException: If phone not verified
    """
    if not user.phone_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Phone verification required"
        )
    return user