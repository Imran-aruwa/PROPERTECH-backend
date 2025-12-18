"""
Attendance and Leave Models

Tracks:
- Staff daily attendance (check‑in / check‑out / hours worked)
- Leave requests
- Monthly attendance summaries

Used by: Head Security, Head Gardener, Security Guards, Gardeners, Caretaker
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.db.base import Base, TimestampMixin


class Attendance(Base, TimestampMixin):
    """
    Attendance tracking model for staff members.

    Tracks:
    - Staff member ID
    - Date of attendance
    - Check-in time
    - Check-out time
    - Hours worked
    - Status (present/absent/on-leave)
    """

    __tablename__ = "attendance"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Foreign Keys
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=False, index=True)

    # Date Information
    date = Column(Date, nullable=False, index=True)

    # Time Tracking
    check_in_time = Column(DateTime, nullable=True)
    check_out_time = Column(DateTime, nullable=True)

    # Calculated Fields
    hours_worked = Column(Float, nullable=True, default=0)

    # Status (present, absent, on-leave, sick)
    status = Column(String(50), nullable=False, default="present")

    # Additional Info
    notes = Column(String(500), nullable=True)
    verified_by = Column(String(255), nullable=True)  # ID or name of supervisor
    is_verified = Column(Boolean, default=False)

    # Optional location tracking
    check_in_location = Column(String(255), nullable=True)
    check_out_location = Column(String(255), nullable=True)

    # Relationships
    staff = relationship("Staff", back_populates="attendance")

    def __repr__(self) -> str:
        return (
            f"<Attendance staff_id={self.staff_id} "
            f"date={self.date} hours={self.hours_worked}>"
        )

    def __str__(self) -> str:
        return f"{self.staff_id} - {self.date} ({self.hours_worked}h)"

    # ---------- Computed properties ----------

    @property
    def is_checked_in(self) -> bool:
        """Return True if staff member is currently checked in."""
        return self.check_in_time is not None and self.check_out_time is None

    @property
    def is_checked_out(self) -> bool:
        """Return True if staff member has checked out."""
        return self.check_out_time is not None

    @property
    def display_date(self) -> str:
        """Return formatted date string."""
        return self.date.strftime("%Y-%m-%d") if self.date else "N/A"

    @property
    def display_check_in(self) -> str:
        """Return formatted check-in time."""
        return (
            self.check_in_time.strftime("%H:%M:%S")
            if self.check_in_time
            else "Not checked in"
        )

    @property
    def display_check_out(self) -> str:
        """Return formatted check-out time."""
        return (
            self.check_out_time.strftime("%H:%M:%S")
            if self.check_out_time
            else "Not checked out"
        )

    @property
    def is_late(self) -> bool:
        """Check if check-in was after expected time (08:00)."""
        if not self.check_in_time:
            return False
        expected_time = self.check_in_time.replace(hour=8, minute=0, second=0)
        return self.check_in_time > expected_time

    @property
    def late_minutes(self) -> int:
        """Calculate minutes late."""
        if not self.is_late:
            return 0
        expected_time = self.check_in_time.replace(hour=8, minute=0, second=0)
        delta = self.check_in_time - expected_time
        return int(delta.total_seconds() / 60)

    # ---------- Business logic helpers ----------

    def calculate_hours_worked(self) -> float:
        """Calculate hours worked from check-in and check-out times."""
        if not self.check_in_time or not self.check_out_time:
            return 0.0

        delta = self.check_out_time - self.check_in_time
        hours = delta.total_seconds() / 3600
        return round(hours, 2)

    def is_overtime(self, standard_hours: float = 8.0) -> bool:
        """Return True if staff member worked more than standard_hours."""
        return bool(self.hours_worked and self.hours_worked > standard_hours)

    def get_overtime_hours(self, standard_hours: float = 8.0) -> float:
        """Return overtime hours above standard_hours."""
        if not self.hours_worked or self.hours_worked <= standard_hours:
            return 0.0
        return self.hours_worked - standard_hours

    def get_status_badge(self) -> str:
        """Return a simple status label for UI display."""
        if self.status == "present":
            return "✅ Present"
        if self.status == "absent":
            return "❌ Absent"
        if self.status == "on-leave":
            return "📅 On Leave"
        if self.status == "sick":
            return "🤒 Sick Leave"
        return "❓ Unknown"

    def to_dict(self) -> dict:
        """Serialize attendance record to a dict for JSON responses."""
        return {
            "id": self.id,
            "staff_id": self.staff_id,
            "date": self.display_date,
            "check_in": self.display_check_in,
            "check_out": self.display_check_out,
            "hours_worked": self.hours_worked,
            "status": self.status,
            "is_late": self.is_late,
            "late_minutes": self.late_minutes if self.is_late else 0,
            "is_overtime": self.is_overtime(),
            "overtime_hours": self.get_overtime_hours(),
            "notes": self.notes,
            "is_verified": self.is_verified,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class LeaveRequest(Base, TimestampMixin):
    """
    Leave/Time-off request model (sick leave, annual leave, emergency, etc.).
    """

    __tablename__ = "leave_requests"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Foreign Keys
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=False, index=True)

    # Leave Details
    leave_type = Column(String(50), nullable=False)  # sick, annual, emergency, unpaid
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)

    # Duration
    number_of_days = Column(Integer, nullable=False)

    # Approval
    reason = Column(String(500), nullable=True)
    status = Column(String(50), nullable=False, default="pending")  # pending/approved/rejected
    approved_by = Column(String(255), nullable=True)
    approval_date = Column(DateTime, nullable=True)
    rejection_reason = Column(String(500), nullable=True)

    # Relationships
    staff = relationship("Staff", back_populates="leave_requests")

    def __repr__(self) -> str:
        return f"<LeaveRequest staff_id={self.staff_id} type={self.leave_type} status={self.status}>"


class AttendanceSummary(Base, TimestampMixin):
    """
    Monthly attendance summary for reporting and analytics.
    """

    __tablename__ = "attendance_summary"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Foreign Keys
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=False, index=True)

    # Period
    month = Column(Integer, nullable=False)  # 1–12
    year = Column(Integer, nullable=False)

    # Day counts
    total_days = Column(Integer, nullable=False, default=0)
    days_present = Column(Integer, nullable=False, default=0)
    days_absent = Column(Integer, nullable=False, default=0)
    days_on_leave = Column(Integer, nullable=False, default=0)
    days_sick = Column(Integer, nullable=False, default=0)

    # Hours
    total_hours_worked = Column(Float, nullable=False, default=0.0)
    total_overtime_hours = Column(Float, nullable=False, default=0.0)

    # Punctuality
    late_arrivals = Column(Integer, nullable=False, default=0)
    total_late_minutes = Column(Integer, nullable=False, default=0)

    # Rates (percentages)
    attendance_rate = Column(Float, nullable=True, default=0.0)
    punctuality_rate = Column(Float, nullable=True, default=0.0)

    # Performance
    performance_score = Column(Float, nullable=True, default=0.0)  # 0–100
    performance_notes = Column(String(500), nullable=True)

    # Relationships
    staff = relationship("Staff", back_populates="attendance_summary")

    def __repr__(self) -> str:
        return f"<AttendanceSummary staff_id={self.staff_id} {self.year}-{self.month:02d}>"

