"""
Price Optimization Engine Models
Tables: rent_reviews, market_comparables, price_optimization_settings, vacancy_history
"""
from sqlalchemy import (
    Column, String, ForeignKey, DateTime, Integer, Boolean, Text, Uuid,
    Numeric, Date,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.db.base import Base


# Use JSONB on postgres, fall back to JSON for sqlite
def _json_col(**kwargs):
    """Return JSONB for postgresql, JSON for SQLite."""
    return Column(JSONB().with_variant(JSON(), "sqlite"), **kwargs)


class RentReview(Base):
    __tablename__ = "rent_reviews"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=False, index=True)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=False, index=True)

    trigger = Column(String(50), nullable=False)  # unit_vacant/manual/scheduled/unit_vacant_7d
    current_rent = Column(Numeric(12, 2), nullable=False)
    recommended_rent = Column(Numeric(12, 2), nullable=False)
    min_rent = Column(Numeric(12, 2), nullable=False)
    max_rent = Column(Numeric(12, 2), nullable=False)
    confidence_score = Column(Integer, default=50)  # 0–100

    reasoning = _json_col(nullable=True)            # array of strings
    market_data_snapshot = _json_col(nullable=True) # snapshot dict

    status = Column(String(20), default="pending", nullable=False, index=True)
    # pending / accepted / rejected / applied

    accepted_rent = Column(Numeric(12, 2), nullable=True)
    reviewed_by = Column(Uuid, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    applied_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)


class MarketComparable(Base):
    __tablename__ = "market_comparables"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=True)

    unit_type = Column(String(50), nullable=False)   # Studio/1BR/2BR/3BR/4BR+
    bedrooms = Column(Integer, nullable=True)
    location_area = Column(String(200), nullable=False, index=True)

    asking_rent = Column(Numeric(12, 2), nullable=False)
    actual_rent = Column(Numeric(12, 2), nullable=True)
    vacancy_days = Column(Integer, nullable=True)

    source = Column(String(30), nullable=False, default="manual")  # manual/import/api
    data_date = Column(Date, nullable=False)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class PriceOptimizationSettings(Base):
    __tablename__ = "price_optimization_settings"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False, unique=True, index=True)

    is_enabled = Column(Boolean, default=True, nullable=False)
    auto_apply = Column(Boolean, default=False, nullable=False)

    max_increase_pct = Column(Numeric(5, 2), default=10.0, nullable=False)
    max_decrease_pct = Column(Numeric(5, 2), default=15.0, nullable=False)
    target_vacancy_days = Column(Integer, default=14, nullable=False)
    min_rent_floor = Column(Numeric(12, 2), nullable=True)
    comparable_radius_km = Column(Numeric(5, 2), default=2.0, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)


class VacancyHistory(Base):
    __tablename__ = "vacancy_history"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=False, index=True)
    owner_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)

    vacant_from = Column(DateTime(timezone=True), nullable=False)
    vacant_until = Column(DateTime(timezone=True), nullable=True)
    days_vacant = Column(Integer, nullable=True)  # computed on fill

    rent_at_vacancy = Column(Numeric(12, 2), nullable=False)
    rent_when_filled = Column(Numeric(12, 2), nullable=True)
    price_changes_count = Column(Integer, default=0, nullable=False)
    filled_by_tenant_id = Column(Uuid, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
