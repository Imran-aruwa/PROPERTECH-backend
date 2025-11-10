from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL environment variable not set. "
        "Please add it to your .env file."
    )

print(f"Connecting to database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'unknown'}")

try:
    # Create engine with PostgreSQL-specific options
    engine = create_engine(
        DATABASE_URL,
        connect_args={"options": "-c statement_cache_mode=describe"} if "postgresql" in DATABASE_URL else {},
        echo=False,  # Set to True for SQL debugging
        pool_pre_ping=True,  # Test connections before using them
        pool_size=10,
        max_overflow=20
    )
    
    # Test the connection
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("✓ Database connection successful!")
    
    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine
    )
except Exception as e:
    print(f"✗ Database connection failed: {e}")
    raise

Base = declarative_base()

def get_db():
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()