from sqlalchemy import Column, Integer, Float, ForeignKey, String, DateTime
from sqlalchemy.orm import relationship
from app.db.base import Base, TimestampMixin
from datetime import datetime

class MeterReading(Base, TimestampMixin):
    __tablename__ = "meter_readings"
    
    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(Integer, ForeignKey("units.id"), nullable=False)
    reading_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    water_reading = Column(Float, nullable=True)
    electricity_reading = Column(Float, nullable=True)
    recorded_by = Column(String(255), nullable=False)
    notes = Column(String(500), nullable=True)

