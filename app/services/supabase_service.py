"""
Supabase Integration Service
Handles syncing between Supabase Auth and PostgreSQL
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from supabase import create_client, Client
import uuid

from app.models.user import User
from app.config import settings

logger = logging.getLogger(__name__)


class SupabaseService:
    """Service for Supabase authentication and user management"""
    
    def __init__(self):
        """Initialize Supabase client"""
        try:
            self.client: Client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_KEY
            )
            self.auth = self.client.auth
            logger.info("Supabase client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            raise
    
    async def get_current_user(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Get current user from Supabase JWT token
        
        Args:
            token: JWT token from Authorization header
            
        Returns:
            User data from Supabase or None
        """
        try:
            # Verify token with Supabase
            user = self.auth.get_user(token)
            return user
        except Exception as e:
            logger.error(f"Token verification failed: {e}")
            return None
    
    def sync_user_to_db(
        self,
        db: Session,
        supabase_user: Dict[str, Any]
    ) -> User:
        """
        Sync Supabase user to PostgreSQL database
        
        Called on:
        1. User signup via Supabase
        2. First API login
        3. User profile update
        
        Args:
            db: Database session
            supabase_user: User data from Supabase
            
        Returns:
            User object from database
        """
        try:
            user_id = uuid.UUID(supabase_user.get("id"))
            email = supabase_user.get("email")
            phone = supabase_user.get("phone")
            
            # Extract user metadata
            user_metadata = supabase_user.get("user_metadata", {})
            
            # Check if user exists in DB
            existing_user = db.query(User).filter(User.id == user_id).first()
            
            if existing_user:
                # Update existing user
                existing_user.email = email
                existing_user.phone = phone
                existing_user.first_name = user_metadata.get("first_name")
                existing_user.last_name = user_metadata.get("last_name")
                existing_user.full_name = user_metadata.get("full_name")
                existing_user.avatar_url = user_metadata.get("avatar_url")
                existing_user.updated_at = datetime.utcnow()
                existing_user.email_verified = supabase_user.get("email_confirmed_at") is not None
                existing_user.phone_verified = supabase_user.get("phone_confirmed_at") is not None
                
                db.commit()
                logger.info(f"Updated user {user_id}")
                return existing_user
            else:
                # Create new user
                new_user = User(
                    id=user_id,
                    email=email,
                    phone=phone,
                    first_name=user_metadata.get("first_name"),
                    last_name=user_metadata.get("last_name"),
                    full_name=user_metadata.get("full_name"),
                    avatar_url=user_metadata.get("avatar_url"),
                    country=user_metadata.get("country"),
                    city=user_metadata.get("city"),
                    company_name=user_metadata.get("company_name"),
                    business_type=user_metadata.get("business_type"),
                    email_verified=supabase_user.get("email_confirmed_at") is not None,
                    phone_verified=supabase_user.get("phone_confirmed_at") is not None,
                    created_at=datetime.fromisoformat(
                        supabase_user.get("created_at", "").replace("Z", "+00:00")
                    ) if supabase_user.get("created_at") else datetime.utcnow()
                )
                
                db.add(new_user)
                db.commit()
                logger.info(f"Created new user {user_id}")
                return new_user
        
        except Exception as e:
            logger.error(f"Error syncing user: {e}")
            db.rollback()
            raise
    
    def get_or_create_user(
        self,
        db: Session,
        supabase_user: Dict[str, Any]
    ) -> User:
        """
        Get user from DB or create if not exists
        
        Args:
            db: Database session
            supabase_user: User data from Supabase
            
        Returns:
            User object
        """
        return self.sync_user_to_db(db, supabase_user)
    
    async def update_user_profile(
        self,
        user_id: str,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Update user profile in Supabase
        
        Args:
            user_id: User ID
            updates: Fields to update (first_name, last_name, etc.)
            
        Returns:
            Updated user data
        """
        try:
            response = self.client.auth.admin.update_user_by_id(
                user_id,
                {"user_metadata": updates}
            )
            return response
        except Exception as e:
            logger.error(f"Error updating user profile: {e}")
            return None
    
    async def create_user(
        self,
        email: str,
        password: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create new user in Supabase
        
        Args:
            email: User email
            password: User password
            metadata: Additional user data
            
        Returns:
            New user data
        """
        try:
            response = self.client.auth.sign_up({
                "email": email,
                "password": password,
                "options": {
                    "data": metadata or {}
                }
            })
            return response
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return None
    
    async def sign_in(
        self,
        email: str,
        password: str
    ) -> Optional[Dict[str, Any]]:
        """
        Sign in user
        
        Args:
            email: User email
            password: User password
            
        Returns:
            User session data with token
        """
        try:
            response = self.client.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            return response
        except Exception as e:
            logger.error(f"Error signing in user: {e}")
            return None
    
    async def sign_out(self, token: str) -> bool:
        """Sign out user"""
        try:
            self.client.auth.sign_out(token)
            return True
        except Exception as e:
            logger.error(f"Error signing out: {e}")
            return False
    
    async def reset_password(self, email: str) -> bool:
        """Send password reset email"""
        try:
            self.client.auth.reset_password_for_email(email)
            return True
        except Exception as e:
            logger.error(f"Error resetting password: {e}")
            return False


# Singleton instance
supabase_service = SupabaseService()