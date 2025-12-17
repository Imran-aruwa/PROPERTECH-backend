"""
Database session - Re-exports for backward compatibility
"""

# Re-export from app.database
from app.database import engine, SessionLocal, get_db
# Re-export Base from app.db.base (single source of truth)
from app.db.base import Base

__all__ = ["engine", "SessionLocal", "Base", "get_db"]
