
from sqlalchemy import Column, Integer, String, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from app.db.base import Base, TimestampMixin

class Equipment(Base, TimestampMixin):
    __tablename__ = "equipment"
    
    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    name = Column(String(255), nullable=False)
    type = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="working")
    last_maintenance = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)