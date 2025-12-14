"""
Database session management - unified sync configuration

Local:
    Uses SQLite (propertech_local.db) for fast development.

Railway:
    Uses PostgreSQL via DATABASE_URL / DATABASE_PRIVATE_URL
    configured in the environment and initialized in app.database.
"""

from app.database import engine, SessionLocal, Base

__all__ = ["engine", "SessionLocal", "Base"]
