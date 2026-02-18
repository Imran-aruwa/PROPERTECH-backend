"""
Area Metrics Model
Stores aggregated neighbourhood/market intelligence data per area.
Computed from properties, units, tenants, and maintenance tables.
"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, DateTime, Text, Uuid
import uuid

from app.db.base import Base


class AreaMetrics(Base):
    """
    Aggregated market metrics per neighbourhood/area.
    One row per unique area_name. Upserted by the MarketService aggregation job.
    data_points = 0 means seeded reference data (no real properties computed yet).
    data_points > 0 means computed from real platform properties.
    """
    __tablename__ = "area_metrics"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    area_name = Column(String(100), nullable=False, unique=True, index=True)
    city = Column(String(100), nullable=True)

    # Rent benchmarks by bedroom count (KES)
    avg_rent_studio = Column(Float, nullable=True)      # 0 bedrooms / bedsitter
    avg_rent_1br = Column(Float, nullable=True)         # 1 bedroom
    avg_rent_2br = Column(Float, nullable=True)         # 2 bedrooms
    avg_rent_3br = Column(Float, nullable=True)         # 3 bedrooms
    avg_rent_4br_plus = Column(Float, nullable=True)    # 4+ bedrooms

    # Vacancy metrics
    total_units = Column(Integer, default=0)
    vacant_units = Column(Integer, default=0)
    vacancy_rate = Column(Float, default=0.0)           # 0.0 to 1.0

    # Tenant stability
    avg_tenancy_months = Column(Float, nullable=True)   # Average lease duration in months

    # Maintenance load (requests per unit over last 90 days)
    maintenance_rate = Column(Float, nullable=True)

    # Overall area health score (0-100, derived from the above)
    area_health_score = Column(Float, nullable=True)

    # How many properties contributed to this computation
    data_points = Column(Integer, default=0)

    # ISO-8601 timestamp of last aggregation run
    last_computed_at = Column(DateTime, nullable=True)

    # 6-month vacancy trend stored as a JSON string
    # Format: '[{"month": "2024-01", "rate": 0.12}, ...]'
    vacancy_trend = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
