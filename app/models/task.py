from sqlalchemy import Column, Integer, String, ForeignKey, Text, DateTime, Enum as SQLEnum
from sqlalchemy.orm import relationship
from app.db.base import Base, TimestampMixin
from enum import Enum
from datetime import datetime

class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    assigned_to = Column(Integer, ForeignKey("staff.id"), nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.PENDING)
    due_date = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
