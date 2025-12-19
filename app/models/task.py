from sqlalchemy import Column, String, ForeignKey, Text, DateTime, Enum as SQLEnum, Uuid
from sqlalchemy.orm import relationship
from app.db.base import Base, TimestampMixin
from enum import Enum
from datetime import datetime
import uuid

class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    assigned_to = Column(Uuid, ForeignKey("staff.id"), nullable=False)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=False)
    unit_id = Column(Uuid, ForeignKey("units.id"), nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.PENDING)
    due_date = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
