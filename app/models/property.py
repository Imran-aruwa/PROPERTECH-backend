from sqlalchemy import Column, String, ForeignKey, DateTime, Integer, Float, Text, Uuid, Boolean, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
from enum import Enum
import uuid
from app.db.base import Base


class UnitStatus(str, Enum):
    """Unit occupancy/ownership status"""
    VACANT = "vacant"           # Available for rent/sale
    OCCUPIED = "occupied"       # Has a tenant (legacy, same as rented)
    RENTED = "rented"           # Currently rented out to a tenant
    BOUGHT = "bought"           # Unit has been sold/purchased
    MORTGAGED = "mortgaged"     # Unit is under mortgage
    MAINTENANCE = "maintenance" # Under maintenance, not available

class Property(Base):
    __tablename__ = "properties"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=False)

    name = Column(String, nullable=False)
    address = Column(String, nullable=False)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)
    country = Column(String, nullable=True, default="Kenya")
    property_type = Column(String)  # residential, commercial, mixed
    description = Column(Text)

    purchase_price = Column(Float)
    purchase_date = Column(DateTime)

    image_url = Column(String, nullable=True)  # Single image URL
    photos = Column(Text)  # Store as JSON string for multiple photos

    total_units = Column(Integer, default=0)  # Total number of units in the property

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    units = relationship("Unit", back_populates="property", cascade="all, delete-orphan")

class Unit(Base):
    __tablename__ = "units"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=False)

    unit_number = Column(String, nullable=False)
    bedrooms = Column(Integer)
    bathrooms = Column(Float)
    toilets = Column(Integer, default=0)  # Separate toilet count
    square_feet = Column(Integer)
    monthly_rent = Column(Float)
    status = Column(String, default="vacant")  # vacant, occupied, maintenance

    # Master bedroom
    has_master_bedroom = Column(Boolean, default=False)

    # Servant Quarters (SQ)
    has_servant_quarters = Column(Boolean, default=False)
    sq_bathrooms = Column(Integer, default=0)  # Bathrooms in servant quarters

    # Description/notes for unit-specific details
    description = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    property = relationship("Property", back_populates="units")