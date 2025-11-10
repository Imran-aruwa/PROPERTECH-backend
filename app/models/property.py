from sqlalchemy import Column, String, ForeignKey, DateTime, Integer, Float, Text
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.database import Base

class Property(Base):
    __tablename__ = "properties"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    name = Column(String, nullable=False)
    address = Column(String, nullable=False)
    property_type = Column(String)  # residential, commercial, mixed
    description = Column(Text)
    
    purchase_price = Column(Float)
    purchase_date = Column(DateTime)
    
    photos = Column(ARRAY(String))
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    units = relationship("Unit", back_populates="property", cascade="all, delete-orphan")

class Unit(Base):
    __tablename__ = "units"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id"), nullable=False)
    
    unit_number = Column(String, nullable=False)
    bedrooms = Column(Integer)
    bathrooms = Column(Float)
    square_feet = Column(Integer)
    monthly_rent = Column(Float)
    status = Column(String, default="vacant")  # vacant, occupied, maintenance
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    property = relationship("Property", back_populates="units")