"""
Security and Authentication
Integrates Supabase JWT verification with FastAPI
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from starlette.requests import Request
from sqlalchemy.orm import Session
import logging
from typing import Optional

from app.database import get_db
from app.models.user import User
from app.services.supabase_service import supabase_service

logger = logging.getLogger(__name__)

# HTTP Bearer scheme for JWT
security = HTTPBearer()


def extract_token(credentials) -> str:
    """Extract token from credentials"""
    if hasattr(credentials, 'credentials'):
        return credentials.credentials
    return str(credentials)


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """
    Get current user from JWT token

    Verifies token with Supabase and syncs user to database

    Args:
        request: HTTP request
        db: Database session

    Returns:
        User object from database

    Raises:
        HTTPException: If token is invalid or user not found
    """
    try:
        # Get token from Authorization header
        auth_header = request.headers.get("Authorization")
        
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header"
            )
        
        token = auth_header.split(" ")[1]

        # Verify token with Supabase
        supabase_user = await supabase_service.get_current_user(token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Sync user to database
        user = supabase_service.sync_user_to_db(db, supabase_user)

        return user

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed"
        )


async def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    Get current user if authenticated, otherwise return None

    Useful for endpoints that work with or without auth

    Args:
        request: HTTP request
        db: Database session

    Returns:
        User object or None
    """
    try:
        return await get_current_user(request, db)
    except HTTPException:
        return None


def verify_admin(user: User = Depends(get_current_user)) -> User:
    """
    Verify user is admin

    Args:
        user: Current user

    Returns:
        User if admin

    Raises:
        HTTPException: If user is not admin
    """
    if user.business_type != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


def verify_email(user: User = Depends(get_current_user)) -> User:
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


def verify_phone(user: User = Depends(get_current_user)) -> User:
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


# Password hashing functions (for auth.py)
from passlib.context import CryptContext
from datetime import timedelta, datetime
from app.config import settings
from jose import JWTError, jwt

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against hashed password"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    
    return encoded_jwt