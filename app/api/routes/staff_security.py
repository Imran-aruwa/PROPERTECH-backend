"""
Security Staff Portal Routes
Dashboard, incidents, attendance for security personnel
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func
from typing import Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
import uuid

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserRole
from app.models.staff import Staff
from app.models.incident import Incident, IncidentSeverity
from app.models.attendance import Attendance

router = APIRouter(tags=["staff-security"])


# ==================== SCHEMAS ====================

class IncidentCreate(BaseModel):
    title: str
    description: str
    priority: str = "medium"


class AttendanceCreate(BaseModel):
    post: str
    shift: str = "day"


# ==================== SECURITY DASHBOARD ====================

@router.get("/dashboard")
def get_security_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get security staff dashboard"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.SECURITY_GUARD]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    today = datetime.utcnow().date()

    # Get incidents today
    incidents_today = db.query(Incident).filter(
        func.date(Incident.reported_at) == today
    ).count()

    # Get staff on duty
    on_duty_staff = db.query(Attendance).filter(
        and_(
            Attendance.date == today,
            Attendance.check_in_time.isnot(None),
            Attendance.check_out_time.is_(None)
        )
    ).count()

    # Get hours logged for current user
    user_attendance = db.query(Attendance).filter(
        and_(
            Attendance.staff_id == current_user.id,
            Attendance.date == today
        )
    ).first()

    hours_logged = 0
    if user_attendance and user_attendance.check_in_time:
        if user_attendance.check_out_time:
            hours_logged = (user_attendance.check_out_time - user_attendance.check_in_time).total_seconds() / 3600
        else:
            hours_logged = (datetime.utcnow() - user_attendance.check_in_time).total_seconds() / 3600

    # Recent incidents
    recent_incidents = db.query(Incident)\
        .order_by(desc(Incident.reported_at))\
        .limit(5)\
        .all()

    incident_list = [
        {
            "id": str(i.id),
            "title": i.title,
            "priority": i.severity.value if i.severity else "medium",
            "reported_at": i.reported_at.isoformat() if i.reported_at else None
        }
        for i in recent_incidents
    ]

    # Staff on duty list
    on_duty = db.query(Attendance, User)\
        .join(User, Attendance.staff_id == User.id)\
        .filter(
            and_(
                Attendance.date == today,
                Attendance.check_in_time.isnot(None),
                Attendance.check_out_time.is_(None)
            )
        ).all()

    staff_on_duty = [
        {
            "id": str(a.User.id),
            "name": a.User.full_name or "Unknown",
            "post": "Main Gate",  # Could be stored in attendance record
            "status": "On Duty"
        }
        for a in on_duty
    ]

    return {
        "success": True,
        "incidents_today": incidents_today,
        "on_duty_staff": on_duty_staff,
        "hours_logged": round(hours_logged, 1),
        "response_time": "3 min",  # Could be calculated from incident data
        "recent_incidents": incident_list,
        "staff_on_duty": staff_on_duty
    }


# ==================== INCIDENTS ====================

@router.get("/incidents")
def get_security_incidents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get security incidents"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.SECURITY_GUARD]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    incidents = db.query(Incident)\
        .order_by(desc(Incident.reported_at))\
        .all()

    return {
        "success": True,
        "incidents": [
            {
                "id": str(i.id),
                "title": i.title,
                "description": i.description,
                "priority": i.severity.value if i.severity else "medium",
                "status": "resolved" if i.resolved_at else "open",
                "reported_at": i.reported_at.isoformat() if i.reported_at else None,
                "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None
            }
            for i in incidents
        ]
    }


@router.post("/incidents")
def create_security_incident(
    incident_data: IncidentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Report a security incident"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.SECURITY_GUARD]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Map priority to severity
    severity_map = {
        "low": IncidentSeverity.LOW,
        "medium": IncidentSeverity.MEDIUM,
        "high": IncidentSeverity.HIGH,
        "critical": IncidentSeverity.CRITICAL
    }
    severity = severity_map.get(incident_data.priority.lower(), IncidentSeverity.MEDIUM)

    # Get staff record
    staff = db.query(Staff).filter(Staff.user_id == current_user.id).first()

    incident = Incident(
        id=uuid.uuid4(),
        staff_id=staff.id if staff else None,
        property_id=staff.property_id if staff else None,
        title=incident_data.title,
        description=incident_data.description,
        severity=severity,
        reported_at=datetime.utcnow()
    )

    db.add(incident)
    db.commit()
    db.refresh(incident)

    return {
        "success": True,
        "message": "Incident reported successfully",
        "incident_id": str(incident.id)
    }


# ==================== ATTENDANCE ====================

@router.get("/attendance")
def get_security_attendance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get attendance records for security staff"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.SECURITY_GUARD]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Get last 30 days of attendance
    start_date = datetime.utcnow().date() - timedelta(days=30)

    if current_user.role == UserRole.HEAD_SECURITY:
        # Head security sees all security staff attendance
        records = db.query(Attendance, User)\
            .join(User, Attendance.staff_id == User.id)\
            .filter(Attendance.date >= start_date)\
            .order_by(desc(Attendance.date))\
            .all()
    else:
        # Regular staff sees only their own
        records = db.query(Attendance)\
            .filter(
                and_(
                    Attendance.staff_id == current_user.id,
                    Attendance.date >= start_date
                )
            )\
            .order_by(desc(Attendance.date))\
            .all()

    if current_user.role == UserRole.HEAD_SECURITY:
        attendance_list = [
            {
                "id": str(r.Attendance.id),
                "staff_name": r.User.full_name or "Unknown",
                "date": r.Attendance.date.isoformat(),
                "check_in": r.Attendance.check_in_time.isoformat() if r.Attendance.check_in_time else None,
                "check_out": r.Attendance.check_out_time.isoformat() if r.Attendance.check_out_time else None,
                "hours_worked": r.Attendance.hours_worked or 0,
                "status": r.Attendance.status or "present"
            }
            for r in records
        ]
    else:
        attendance_list = [
            {
                "id": str(r.id),
                "date": r.date.isoformat(),
                "check_in": r.check_in_time.isoformat() if r.check_in_time else None,
                "check_out": r.check_out_time.isoformat() if r.check_out_time else None,
                "hours_worked": r.hours_worked or 0,
                "status": r.status or "present"
            }
            for r in records
        ]

    return {
        "success": True,
        "attendance": attendance_list
    }


@router.post("/attendance")
def record_security_attendance(
    attendance_data: AttendanceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Record attendance (check-in)"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.SECURITY_GUARD]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    today = datetime.utcnow().date()

    # Check if already checked in
    existing = db.query(Attendance).filter(
        and_(
            Attendance.staff_id == current_user.id,
            Attendance.date == today
        )
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Already checked in today")

    attendance = Attendance(
        id=uuid.uuid4(),
        staff_id=current_user.id,
        date=today,
        check_in_time=datetime.utcnow(),
        status="present",
        notes=f"Post: {attendance_data.post}, Shift: {attendance_data.shift}"
    )

    db.add(attendance)
    db.commit()

    return {
        "success": True,
        "message": "Checked in successfully",
        "time": datetime.utcnow().isoformat()
    }


# ==================== PERFORMANCE ====================

@router.get("/performance")
def get_security_performance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    days: int = 30
):
    """Get security staff performance metrics"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.SECURITY_GUARD]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    start_date = datetime.utcnow().date() - timedelta(days=days)

    # Get attendance data
    if current_user.role == UserRole.HEAD_SECURITY:
        attendance_records = db.query(Attendance).filter(Attendance.date >= start_date).all()
    else:
        attendance_records = db.query(Attendance).filter(
            and_(
                Attendance.staff_id == current_user.id,
                Attendance.date >= start_date
            )
        ).all()

    # Get incidents data
    if current_user.role == UserRole.HEAD_SECURITY:
        incidents = db.query(Incident).filter(Incident.reported_at >= datetime.combine(start_date, datetime.min.time())).all()
    else:
        staff = db.query(Staff).filter(Staff.user_id == current_user.id).first()
        incidents = db.query(Incident).filter(
            and_(
                Incident.staff_id == staff.id if staff else None,
                Incident.reported_at >= datetime.combine(start_date, datetime.min.time())
            )
        ).all() if staff else []

    total_hours = sum(r.hours_worked or 0 for r in attendance_records)
    days_present = len([r for r in attendance_records if r.check_in_time])
    incidents_reported = len(incidents)
    incidents_resolved = len([i for i in incidents if i.resolved_at])

    return {
        "success": True,
        "period_days": days,
        "metrics": {
            "total_hours_worked": round(total_hours, 1),
            "days_present": days_present,
            "attendance_rate": round((days_present / days * 100) if days > 0 else 0, 1),
            "incidents_reported": incidents_reported,
            "incidents_resolved": incidents_resolved,
            "resolution_rate": round((incidents_resolved / incidents_reported * 100) if incidents_reported > 0 else 100, 1),
            "average_response_time": "3 min"  # Could be calculated from incident data
        }
    }


# ==================== ON DUTY STAFF ====================

@router.get("/on-duty")
def get_on_duty_staff(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get list of security staff currently on duty"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.SECURITY_GUARD]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    today = datetime.utcnow().date()

    # Get all staff currently on duty (checked in but not checked out)
    on_duty = db.query(Attendance, User)\
        .join(User, Attendance.staff_id == User.id)\
        .filter(
            and_(
                Attendance.date == today,
                Attendance.check_in_time.isnot(None),
                Attendance.check_out_time.is_(None)
            )
        ).all()

    on_duty_list = []
    for record in on_duty:
        hours_on_duty = 0
        if record.Attendance.check_in_time:
            hours_on_duty = (datetime.utcnow() - record.Attendance.check_in_time).total_seconds() / 3600

        on_duty_list.append({
            "id": str(record.User.id),
            "name": record.User.full_name or "Unknown",
            "check_in_time": record.Attendance.check_in_time.isoformat() if record.Attendance.check_in_time else None,
            "hours_on_duty": round(hours_on_duty, 1),
            "post": "Main Gate",  # Could be stored in notes
            "status": "on_duty"
        })

    return {
        "success": True,
        "total_on_duty": len(on_duty_list),
        "staff": on_duty_list
    }
