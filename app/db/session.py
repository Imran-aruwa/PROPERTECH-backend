"""
Database session management - SYNC for local, ASYNC for Railway
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

# Detect Railway environment
IS_RAILWAY = os.getenv("RAILWAY_ENVIRONMENT") is not None

if IS_RAILWAY:
    # Railway: Use PostgreSQL async
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost")
    engine = create_async_engine(DATABASE_URL)
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    print("🚀 Railway PostgreSQL (async)")
else:
    # Local: Use SQLite sync (NO async issues)
    DATABASE_URL = "sqlite:///propertech_local.db"
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    print("💻 Local SQLite (sync)")

Base = declarative_base()

def get_db():
    """Database dependency - works for both sync/async."""
    if IS_RAILWAY:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    else:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
