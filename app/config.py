"""
Application Configuration
Loads settings from .env file
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # ==================== Project Info ====================
    PROJECT_NAME: str = "PROPERTECH API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # ==================== Database ====================
    DATABASE_URL: str = "postgresql+psycopg://postgres.thhwkyzttjegjivrqaps:wpVInkXjHoh48On1@aws-1-ap-southeast-2.pooler.supabase.com:5432/postgres"
    
    # ==================== Security & Authentication ====================
    SECRET_KEY: str = "1fb0f9639cda462bd6bd5e78338e2ceec369784e19e9f917b413b3232457c5e5"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # ==================== Supabase ====================
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_JWT_SECRET: str = ""
    
    # ==================== CORS ====================
    FRONTEND_URL: str = "https://propertech-indol.vercel.app"
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "https://propertech-indol.vercel.app"
    ]
    
    # ==================== Server ====================
    FLASK_RUN_HOST: str = "0.0.0.0"
    FLASK_RUN_PORT: int = 8000
    
    # ==================== Paystack Configuration ====================
    PAYSTACK_PUBLIC_KEY: str = ""
    PAYSTACK_SECRET_KEY: str = ""
    PAYSTACK_API_URL: str = "https://api.paystack.co"
    
    # ==================== Flutterwave Configuration ====================
    FLUTTERWAVE_PUBLIC_KEY: str = ""
    FLUTTERWAVE_SECRET_KEY: str = ""
    FLUTTERWAVE_WEBHOOK_HASH: str = ""
    FLUTTERWAVE_API_URL: str = "https://api.flutterwave.com/v3"
    
    # ==================== Payment Plans ====================
    PAYMENT_PLANS: dict = {
        "starter": {
            "name": "Starter",
            "description": "Perfect for individuals",
            "monthly_price": 2900,
            "yearly_price": 29000,
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
            "monthly_price": 9900,
            "yearly_price": 99000,
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
    
    # ==================== Features ====================
    DEBUG: bool = False
    TESTING: bool = False
    
    # ==================== Logging ====================
    LOG_LEVEL: str = "INFO"
    
    # Configuration loading
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="allow"  # Allow extra environment variables
    )


# Create settings singleton
settings = Settings()