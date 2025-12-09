from sqlalchemy import Column, String, Integer, Float, ForeignKey, Enum as SQLEnum, Boolean
from sqlalchemy.orm import relationship
from app.db.base import Base, TimestampMixin
from enum import Enum

class UnitType(str, Enum):
    BEDSITTER = "bedsitter"
    ONE_BEDROOM = "one_bedroom"
    TWO_BEDROOM = "two_bedroom"
    THREE_BEDROOM = "three_bedroom"

class Unit(Base, TimestampMixin):
    __tablename__ = "units"
    
    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    unit_number = Column(String(50), nullable=False)
    unit_type = Column(SQLEnum(UnitType), nullable=False)
    monthly_rent = Column(Float, nullable=False)
    is_occupied = Column(Boolean, default=False)
    
    property = relationship("Property", back_populates="units")
    tenants = relationship("Tenant", back_populates="unit")
