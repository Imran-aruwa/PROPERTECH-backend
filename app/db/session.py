"""
Database session - Re-exports from app.database for backward compatibility
"""

# Re-export everything from app.database for backward compatibility
from app.database import engine, SessionLocal, Base, get_db

__all__ = ["engine", "SessionLocal", "Base", "get_db"]
