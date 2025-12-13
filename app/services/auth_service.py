"""
Authentication Service
Handles user creation, authentication, and token generation
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import timedelta
from typing import Optional

from app.models.user import User
from app.core.security import get_password_hash, verify_password, create_access_token
from app.core.config import settings


async def create_user(
    db: AsyncSession, 
    email: str, 
    full_name: str, 
    password: str, 
    role: str = "tenant", 
    phone: Optional[str] = None
) -> User:
    """
    Create a new user
    
    Args:
        db: Database session
        email: User email
        full_name: User full name
        password: Plain text password (will be hashed)
        role: User role (default: tenant)
        phone: User phone number (optional)
        
    Returns:
        Created user object
    """
    db_user = User(
        email=email,
        full_name=full_name,
        hashed_password=get_password_hash(password),
        role=role,
        phone=phone
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user


def create_user_sync(
    db: Session, 
    email: str, 
    full_name: str, 
    password: str, 
    role: str = "tenant", 
    phone: Optional[str] = None
) -> User:
    """
    Create a new user (synchronous version)
    
    Args:
        db: Database session
        email: User email
        full_name: User full name
        password: Plain text password (will be hashed)
        role: User role (default: tenant)
        phone: User phone number (optional)
        
    Returns:
        Created user object
    """
    db_user = User(
        email=email,
        full_name=full_name,
        hashed_password=get_password_hash(password),
        role=role,
        phone=phone
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> Optional[User]:
    """
    Authenticate user with email and password
    
    Args:
        db: Database session
        email: User email
        password: Plain text password
        
    Returns:
        User object if authentication successful, None otherwise
    """
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(password, user.hashed_password):
        return None
    
    return user


def authenticate_user_sync(db: Session, email: str, password: str) -> Optional[User]:
    """
    Authenticate user with email and password (synchronous version)
    
    Args:
        db: Database session
        email: User email
        password: Plain text password
        
    Returns:
        User object if authentication successful, None otherwise
    """
    user = db.query(User).filter(User.email == email).first()
    
    if not user or not verify_password(password, user.hashed_password):
        return None
    
    return user


async def generate_tokens(user: User) -> str:
    """
    Generate access token for user
    
    Args:
        user: User object
        
    Returns:
        JWT access token string
    """
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role},
        expires_delta=access_token_expires
    )
    return access_token


def generate_tokens_sync(user: User) -> str:
    """
    Generate access token for user (synchronous version)
    
    Args:
        user: User object
        
    Returns:
        JWT access token string
    """
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role},
        expires_delta=access_token_expires
    )
    return access_token


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    """
    Get user by ID
    
    Args:
        db: Database session
        user_id: User ID
        
    Returns:
        User object or None if not found
    """
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def get_user_by_id_sync(db: Session, user_id: int) -> Optional[User]:
    """
    Get user by ID (synchronous version)
    
    Args:
        db: Database session
        user_id: User ID
        
    Returns:
        User object or None if not found
    """
    return db.query(User).filter(User.id == user_id).first()


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    """
    Get user by email
    
    Args:
        db: Database session
        email: User email
        
    Returns:
        User object or None if not found
    """
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def get_user_by_email_sync(db: Session, email: str) -> Optional[User]:
    """
    Get user by email (synchronous version)
    
    Args:
        db: Database session
        email: User email
        
    Returns:
        User object or None if not found
    """
    return db.query(User).filter(User.email == email).first()