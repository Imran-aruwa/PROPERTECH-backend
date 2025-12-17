"""
Authentication Endpoints
User signup, login, and profile management
"""
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse, UserLogin, Token
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    get_current_user
)
from app.core.config import settings

router = APIRouter()


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(user_in: UserCreate, db: Session = Depends(get_db)):
    """Register a new user"""
    import uuid
    import logging
    from app.models.user import UserRole

    try:
        # Check if user exists
        user = db.query(User).filter(User.email == user_in.email).first()
        if user:
            raise HTTPException(
                status_code=400,
                detail="Email already registered"
            )

        # Get role - convert to lowercase enum value
        role_str = user_in.get_role()
        try:
            user_role = UserRole(role_str)
        except ValueError:
            user_role = UserRole.OWNER

        # Create new user with UUID
        user = User(
            id=uuid.uuid4(),
            email=user_in.email,
            full_name=user_in.get_full_name(),
            hashed_password=get_password_hash(user_in.password),
            role=user_role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # Return serializable response
        user_role_value = user.role.value if hasattr(user.role, 'value') else str(user.role)
        return {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name or "",
            "role": user_role_value.upper(),
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "message": "Account created successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Signup error: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create account: {str(e)}"
        )


@router.post("/login")
def login(user_credentials: UserLogin, db: Session = Depends(get_db)):
    """Login and get access token with user info"""
    try:
        user = db.query(User).filter(User.email == user_credentials.email).first()
    except Exception as e:
        # Log database errors for debugging
        import logging
        logging.error(f"Database error during login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred"
        )

    if not user or not verify_password(user_credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    # Safely extract role value (handle enum or string)
    user_role = getattr(user, 'role', None)
    if user_role is not None:
        role_value = user_role.value if hasattr(user_role, 'value') else str(user_role)
    else:
        role_value = "owner"

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": str(user.id),  # Convert UUID to string for JSON
        "full_name": user.full_name or "",
        "email": user.email,
        "role": role_value.upper(),  # Return uppercase for frontend compatibility
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information"""
    return current_user