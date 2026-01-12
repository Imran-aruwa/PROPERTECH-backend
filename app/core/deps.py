from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session
import logging

from app.core.config import settings
from app.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

# Fix: Use correct token URL that matches actual auth endpoint
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    Get current authenticated user from JWT token.
    Returns 401 if token is invalid or user not found.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        # Decode JWT token
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

        # Get user_id from token (stored in "sub" field)
        user_id: str = payload.get("sub")
        if user_id is None:
            logger.warning("Token missing 'sub' field")
            raise credentials_exception

    except JWTError as e:
        logger.warning(f"JWT decode error: {e}")
        raise credentials_exception

    # Query user by ID
    try:
        user = db.query(User).filter(User.id == user_id).first()
    except Exception as e:
        logger.error(f"Database error looking up user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error"
        )

    if user is None:
        logger.warning(f"User not found in database: {user_id}")
        raise credentials_exception

    return user