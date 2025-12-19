from sqlalchemy import Column, String, ForeignKey, Text, Boolean, Uuid
from sqlalchemy.orm import relationship
from app.db.base import Base, TimestampMixin
import uuid

class Equipment(Base, TimestampMixin):
    __tablename__ = "equipment"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=False)
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=True)
    name = Column(String(255), nullable=False)
    type = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="working")
    last_maintenance = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
