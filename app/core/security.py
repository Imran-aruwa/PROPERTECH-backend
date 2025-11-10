from datetime import datetime, timedelta
from typing import Optional
from jose import jwt
from passlib.context import CryptContext
from app.config import settings

# Use Argon2 for password hashing (more secure, no 72-byte limit)
pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    deprecated="auto",
    argon2__memory_cost=65536,  # 64 MB
    argon2__time_cost=3,        # 3 iterations
    argon2__parallelism=4       # 4 parallel threads
)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password.
    Supports both argon2 and bcrypt for backwards compatibility.
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        # Log error for debugging
        print(f"Password verification error: {e}")
        return False

def get_password_hash(password: str) -> str:
    """
    Hash a password using Argon2.
    Argon2 is the winner of the Password Hashing Competition and
    is recommended by OWASP for password storage.
    """
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """
    Create a JWT access token.
    
    Args:
        data: Dictionary containing claims to encode in the token
        expires_delta: Optional timedelta for token expiration
        
    Returns:
        Encoded JWT token as a string
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt