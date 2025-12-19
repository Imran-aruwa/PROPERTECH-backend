"""
Staff Model

Represents staff members assigned to a property, grouped by department
(security, gardening, maintenance) with salary and supervisor data.

Used with:
- Attendance
- LeaveRequest
- AttendanceSummary
"""

from enum import Enum
import uuid

from sqlalchemy import (
    Column,
    Date,
    Float,
    ForeignKey,
    String,
    Enum as SQLEnum,
    Uuid,
)
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class StaffDepartment(str, Enum):
    SECURITY = "security"
    GARDENING = "gardening"
    MAINTENANCE = "maintenance"


class Staff(Base, TimestampMixin):
    __tablename__ = "staff"

    # Primary key
    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)

    # Foreign keys
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=False)
    property_id = Column(Uuid, ForeignKey("properties.id"), nullable=False)
    supervisor_id = Column(Uuid, ForeignKey("staff.id"), nullable=True)

    # Staff details
    department = Column(SQLEnum(StaffDepartment), nullable=False)
    position = Column(String(100), nullable=False)
    salary = Column(Float, nullable=False)
    start_date = Column(Date, nullable=False)

    # Relationships to other models
    attendance = relationship(
        "Attendance",
        back_populates="staff",
        cascade="all, delete-orphan",
    )
    leave_requests = relationship(
        "LeaveRequest",
        back_populates="staff",
        cascade="all, delete-orphan",
    )
    attendance_summary = relationship(
        "AttendanceSummary",
        back_populates="staff",
        cascade="all, delete-orphan",
    )

    # Self-referential relationship (optional): supervisor & subordinates
    supervisor = relationship(
        "Staff",
        remote_side=[id],
        backref="subordinates",
        uselist=False,
    )

    def __repr__(self) -> str:
        return (
            f"<Staff id={self.id} user_id={self.user_id} "
            f"dept={self.department} position={self.position}>"
        )
