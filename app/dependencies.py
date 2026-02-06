import uuid
import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.security import decode_access_token
from app.database import get_db
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

security = HTTPBearer()

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user from JWT token"""
    token = credentials.credentials
    logger.info(f"[AUTH] Token received (first 20 chars): {token[:20]}...")

    payload = decode_access_token(token)

    if not payload:
        logger.error("[AUTH] Token decode returned None - invalid/expired token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        logger.error(f"[AUTH] No 'sub' claim in token payload. Keys: {list(payload.keys())}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token: missing user ID")

    try:
        user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    except ValueError:
        logger.error(f"[AUTH] Invalid UUID format for user_id: {user_id}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user ID format")

    try:
        user = db.query(User).filter(User.id == user_uuid).first()
    except Exception as e:
        logger.error(f"[AUTH] Database error querying user {user_uuid}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication database error",
        )

    if user is None:
        logger.error(f"[AUTH] User not found in database: {user_uuid}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    logger.info(f"[AUTH] Authenticated user: {user.email} (role={user.role})")
    return user

def require_role(*roles: UserRole):
    """Dependency factory for role-based access control"""
    def role_checker(user: User = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user
    return role_checker
