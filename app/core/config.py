"""
Propertechsoftware Application Configuration
Loads settings from .env file using Pydantic v2 with BaseSettings
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Optional, List
from functools import lru_cache
import warnings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # ==================== Project Info ====================
    PROJECT_NAME: str = "Propertechsoftware API"
    PROJECT_DESCRIPTION: str = "Complete Property Management System with Role-Based Portals"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # ==================== Database ====================
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/propertech"
    
    # ==================== Security & Authentication ====================
    SECRET_KEY: str = "your-super-secret-key-change-this-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    
    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v):
        if v == "your-super-secret-key-change-this-in-production":
            warnings.warn(
                "SECRET_KEY is using the default placeholder! Set a secure SECRET_KEY in .env",
                stacklevel=2,
            )
        return v

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v):
        if "password@localhost" in v:
            warnings.warn(
                "DATABASE_URL is using the default placeholder! Set a real DATABASE_URL in .env",
                stacklevel=2,
            )
        return v

    # ==================== CORS & Frontend ====================
    FRONTEND_URL: str = "https://propertechsoftware.com"
    BACKEND_API_URL: str = "https://api.propertechsoftware.com"
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "https://propertechsoftware.com",
        "https://www.propertechsoftware.com",
        "https://api.propertechsoftware.com",
    ]
    
    # ==================== Server Configuration ====================
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = True
    
    # ==================== Paystack Configuration ====================
    PAYSTACK_PUBLIC_KEY: str = ""
    PAYSTACK_SECRET_KEY: str = ""
    PAYSTACK_API_URL: str = "https://api.paystack.co"
    PAYSTACK_ENABLED: bool = True
    
    # ==================== Daraja (M-Pesa) Configuration ====================
    DARAJA_ENABLED: bool = True
    DARAJA_CONSUMER_KEY: str = ""
    DARAJA_CONSUMER_SECRET: str = ""
    DARAJA_BUSINESS_SHORTCODE: str = ""
    DARAJA_PASSKEY: str = ""
    # Public-facing backend URL used for Mpesa callback registration
    BACKEND_URL: str = "http://localhost:8000"

    # ==================== Africa's Talking SMS ====================
    AT_API_KEY: str = ""       # Africa's Talking API key (leave blank for dev logging mode)
    AT_USERNAME: str = "sandbox"  # "sandbox" for testing, your AT username for production
    AT_SENDER_ID: str = ""     # optional short-code sender name
    
    # ==================== Supabase Configuration ====================
    # NOTE: Disabled as per your latest requirements (PostgreSQL only)
    SUPABASE_ENABLED: bool = False
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_JWT_SECRET: str = ""
    
    # ==================== Payment Plans ====================
    PAYMENT_PLANS: dict = {
        "starter": {
            "name": "Starter",
            "description": "Perfect for individuals",
            "monthly_price": 6468,
            "yearly_price": 64680,
            "features": [
                "Up to 5 properties",
                "Basic analytics",
                "Email support",
                "1GB storage"
            ]
        },
        "professional": {
            "name": "Professional",
            "description": "For growing agencies",
            "monthly_price": 13068,
            "yearly_price": 130680,
            "features": [
                "Unlimited properties",
                "Advanced analytics",
                "Priority support",
                "100GB storage",
                "Team members"
            ]
        },
        "enterprise": {
            "name": "Enterprise",
            "description": "For large organizations",
            "monthly_price": 29900,
            "yearly_price": 299000,
            "features": [
                "Unlimited everything",
                "Custom integrations",
                "24/7 support",
                "Unlimited storage",
                "Custom branding"
            ]
        }
    }
    
    # ==================== Email Configuration ====================
    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = "noreply@propertechsoftware.com"
    SEND_EMAILS: bool = True
    
    # ==================== Features ====================
    DEBUG: bool = False
    TESTING: bool = False
    LOG_LEVEL: str = "INFO"
    
    # ==================== Database Connection Pool ====================
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 0
    DATABASE_POOL_RECYCLE: int = 3600
    
    # ==================== Role-Based Access Control ====================
    ENABLE_RBAC: bool = True
    ENABLE_ROLE_PERMISSIONS: bool = True
    
    # ==================== Pagination ====================
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100
    
    # ==================== Configuration Loading ====================
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="allow",  # Allow extra environment variables
        validate_default=True,
    )
    
    # ==================== Properties ====================
    @property
    def database_url_async(self) -> str:
        """Convert sync database URL to async"""
        return self.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    
    @property
    def payment_gateway_enabled(self) -> bool:
        """Check if any payment gateway is enabled"""
        return self.PAYSTACK_ENABLED or self.DARAJA_ENABLED
    
    @property
    def email_configured(self) -> bool:
        """Check if email is properly configured"""
        return bool(self.SMTP_USER and self.SMTP_PASSWORD)


# ==================== Settings Singleton ====================
@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Create default settings instance
settings = get_settings()


# ==================== Helper Functions ====================
def get_cors_origins() -> List[str]:
    """Get CORS allowed origins"""
    return settings.ALLOWED_ORIGINS


def get_database_url() -> str:
    """Get database URL (async version for FastAPI)"""
    return settings.database_url_async


def is_production() -> bool:
    """Check if running in production"""
    return not settings.DEBUG and settings.FRONTEND_URL.startswith("https")


def is_development() -> bool:
    """Check if running in development"""
    return settings.DEBUG or "localhost" in settings.FRONTEND_URL


def is_testing() -> bool:
    """Check if running in testing mode"""
    return settings.TESTING