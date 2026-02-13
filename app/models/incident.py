from sqlalchemy import Column, String, ForeignKey, Text, DateTime, Enum as SQLEnum, Uuid
from sqlalchemy.orm import relationship
from app.db.base import Base, TimestampMixin
from enum import Enum
from datetime import datetime
import uuid

class IncidentSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class Incident(Base, TimestampMixin):
    __tablename__ = "incidents"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    staff_id = Column(Uuid, ForeignKey("staff.id"), nullable=False)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=False)
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    severity = Column(SQLEnum(IncidentSeverity), default=IncidentSeverity.MEDIUM)
    reported_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    # Relationships
    staff = relationship("Staff", backref="incidents")
    property = relationship("Property", backref="incidents")
