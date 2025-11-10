from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    PROJECT_NAME: str = "PROPERTECH API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str="postgresql+psycopg://postgres.thhwkyzttjegjivrqaps:wpVInkXjHoh48On1@aws-1-ap-southeast-2.pooler.supabase.com:5432/postgres"
    
    # Security
    SECRET_KEY: str="1fb0f9639cda462bd6bd5e78338e2ceec369784e19e9f917b413b3232457c5e5" 
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # CORS
    FRONTEND_URL: str = "https://propertech-indol.vercel.app"

    # Flask run settings (added)
    FLASK_RUN_HOST: str = "127.0.0.1"
    FLASK_RUN_PORT: int = 5050

    # Allow extra values in your .env (prevents validation errors)
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="allow"
    )

settings = Settings()
