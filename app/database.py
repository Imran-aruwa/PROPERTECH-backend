from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os
import sys

# Load environment variables from .env file
load_dotenv()

# Determine if running on Railway (production)
IS_RAILWAY = os.getenv("RAILWAY_ENVIRONMENT") is not None or os.getenv("RAILWAY_GIT_COMMIT_SHA")

# Get appropriate database URL based on environment
if IS_RAILWAY:
    # Running on Railway - use private/internal URL for zero egress costs
    DATABASE_URL = (
        os.getenv("DATABASE_PRIVATE_URL") or 
        os.getenv("DATABASE_URL")
    )
    print("[RAILWAY] Running on Railway - using private network connection")
else:
    # Running locally - use SQLite for instant dev
    DATABASE_URL = "sqlite:///propertech_local.db"
    print("[LOCAL] Running locally - using SQLite (instant dev)")

if not DATABASE_URL:
    raise ValueError("[ERROR] DATABASE_URL not found!")

# ✅ PRODUCTION READY: SYNC engine ONLY (no async issues)
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False  # SQLite multi-thread
    } if "sqlite" in DATABASE_URL.lower() else {
        "connect_timeout": 10,
        "options": "-c statement_timeout=30000"  # 30s query timeout
    },
    echo=False,
    pool_pre_ping=True,
    pool_size=5 if IS_RAILWAY else 3,
    max_overflow=10,
    pool_recycle=3600,
    pool_timeout=30,
)

# Create SessionLocal class
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()

def get_db():
    """Dependency for getting database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def test_connection():
    """Test database connection - NON-BLOCKING."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
            safe_url = DATABASE_URL.split('@')[1] if '@' in DATABASE_URL and not IS_RAILWAY else DATABASE_URL.split('/')[-1]
            print(f"[OK] Database connected: {safe_url}")
            return True
    except Exception as e:
        print(f"[WARN] Database connection failed (continuing): {str(e)}")
        return False  # Continue anyway

def init_db():
    """Initialize database tables - NON-BLOCKING."""
    try:
        # Import all models so they're registered with Base
        from app.models.user import User, UserPreference
        from app.models.tenant import Tenant
        from app.models.payment import Payment, Subscription, Invoice, PaymentGatewayLog
        # Add other models as they exist:
        # from app.models.property import Property
        # from app.models.unit import Unit
        # from app.models.maintenance import MaintenanceRequest
        
        Base.metadata.create_all(bind=engine)
        print("[OK] Database tables initialized!")
        return True
    except Exception as e:
        print(f"[WARN] Database init warning: {str(e)}")
        return False  # Continue anyway

def close_db_connection():
    """Close database connections."""
    try:
        engine.dispose()
        print("[OK] Database connections closed")
    except Exception as e:
        print(f"[WARN] Error closing DB: {str(e)}")
