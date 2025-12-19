from sqlalchemy import Column, String, ForeignKey, Text, Enum as SQLEnum, Uuid
from sqlalchemy.orm import relationship
from app.db.base import Base, TimestampMixin
from enum import Enum
import uuid

class MaintenanceStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"

class MaintenancePriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EMERGENCY = "emergency"

class MaintenanceRequest(Base, TimestampMixin):
    __tablename__ = "maintenance_requests"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    tenant_id = Column(Uuid, ForeignKey("tenants.id"), nullable=False)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=True)
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    priority = Column(SQLEnum(MaintenancePriority), default=MaintenancePriority.MEDIUM)
    status = Column(SQLEnum(MaintenanceStatus), default=MaintenanceStatus.PENDING)
    notes = Column(Text, nullable=True)
