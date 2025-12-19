from sqlalchemy import Column, Float, ForeignKey, String, DateTime, Uuid
from sqlalchemy.orm import relationship
from app.db.base import Base, TimestampMixin
from datetime import datetime
import uuid

class MeterReading(Base, TimestampMixin):
    __tablename__ = "meter_readings"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=False)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=True)
    reading_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    water_reading = Column(Float, nullable=True)
    electricity_reading = Column(Float, nullable=True)
    recorded_by = Column(String(255), nullable=False)
    notes = Column(String(500), nullable=True)
