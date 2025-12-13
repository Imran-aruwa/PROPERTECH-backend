"""
Database Base Class and Timestamp Mixin - Production Ready
"""
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import DateTime
from datetime import datetime, timezone
import typing

class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass

class TimestampMixin:
    """Mixin for automatic created_at/updated_at timestamps."""
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
