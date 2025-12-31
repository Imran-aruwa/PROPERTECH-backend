"""
Staff Portal Routes - Complete Implementation
Attendance tracking, incident reporting, task management, performance metrics
Used by: Head Security, Head Gardener, Security Guards, Gardeners
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func
from typing import List, Optional
from datetime import datetime, timedelta
from uuid import UUID

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserRole
from app.models.staff import Staff, StaffDepartment
from app.models.incident import Incident, IncidentSeverity
from app.models.task import Task, TaskStatus
from app.models.maintenance import MaintenanceRequest

router = APIRouter(tags=["staff"])


# ==================== ROOT ENDPOINT ====================

@router.get("")
@router.get("/")
def get_all_staff(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all staff members (accessible by owners, caretakers, and staff supervisors)"""
    allowed_roles = [UserRole.OWNER, UserRole.CARETAKER, UserRole.HEAD_SECURITY, UserRole.HEAD_GARDENER, UserRole.ADMIN]
    if current_user.role not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    staff_members = db.query(Staff).all()

    staff_list = []
    for s in staff_members:
        staff_list.append({
            "id": str(s.id),
            "user_id": str(s.user_id) if s.user_id else None,
            "name": s.user.full_name if s.user else "Unknown",
            "email": s.user.email if s.user else "N/A",
            "position": s.position,
            "department": s.department,
            "salary": float(s.salary) if s.salary else 0,
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "property_id": str(s.property_id) if s.property_id else None
        })

    return {
        "success": True,
        "total_staff": len(staff_list),
        "staff": staff_list
    }


# ==================== STAFF CRUD OPERATIONS ====================

from pydantic import BaseModel
import uuid

class StaffCreate(BaseModel):
    user_id: Optional[str] = None
    position: str
    department: str
    salary: Optional[float] = None
    property_id: Optional[str] = None

class StaffUpdate(BaseModel):
    position: Optional[str] = None
    department: Optional[str] = None
    salary: Optional[float] = None
    property_id: Optional[str] = None


@router.post("/")
def create_staff(
    staff_data: StaffCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new staff member"""
    if current_user.role not in [UserRole.OWNER, UserRole.ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    staff = Staff(
        id=uuid.uuid4(),
        user_id=UUID(staff_data.user_id) if staff_data.user_id else None,
        position=staff_data.position,
        department=staff_data.department,
        salary=staff_data.salary,
        property_id=UUID(staff_data.property_id) if staff_data.property_id else None,
        start_date=datetime.utcnow().date()
    )

    db.add(staff)
    db.commit()
    db.refresh(staff)

    return {
        "success": True,
        "message": "Staff member created successfully",
        "staff": {
            "id": str(staff.id),
            "position": staff.position,
            "department": staff.department
        }
    }


@router.get("/{staff_id}")
def get_staff_by_id(
    staff_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific staff member by ID"""
    allowed_roles = [UserRole.OWNER, UserRole.CARETAKER, UserRole.HEAD_SECURITY, UserRole.HEAD_GARDENER, UserRole.ADMIN]
    if current_user.role not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not staff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff member not found")

    return {
        "success": True,
        "staff": {
            "id": str(staff.id),
            "user_id": str(staff.user_id) if staff.user_id else None,
            "name": staff.user.full_name if staff.user else "Unknown",
            "email": staff.user.email if staff.user else "N/A",
            "position": staff.position,
            "department": staff.department,
            "salary": float(staff.salary) if staff.salary else 0,
            "start_date": staff.start_date.isoformat() if staff.start_date else None,
            "property_id": str(staff.property_id) if staff.property_id else None
        }
    }


@router.put("/{staff_id}")
def update_staff(
    staff_id: str,
    staff_data: StaffUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a staff member"""
    if current_user.role not in [UserRole.OWNER, UserRole.ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not staff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff member not found")

    if staff_data.position is not None:
        staff.position = staff_data.position
    if staff_data.department is not None:
        staff.department = staff_data.department
    if staff_data.salary is not None:
        staff.salary = staff_data.salary
    if staff_data.property_id is not None:
        staff.property_id = UUID(staff_data.property_id)

    db.commit()
    db.refresh(staff)

    return {
        "success": True,
        "message": "Staff member updated successfully",
        "staff": {
            "id": str(staff.id),
            "position": staff.position,
            "department": staff.department
        }
    }


@router.delete("/{staff_id}")
def delete_staff(
    staff_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a staff member"""
    if current_user.role not in [UserRole.OWNER, UserRole.ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not staff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff member not found")

    db.delete(staff)
    db.commit()

    return {
        "success": True,
        "message": "Staff member deleted successfully"
    }


# ==================== ATTENDANCE ====================

@router.post("/attendance/check-in")
@router.post("/check-in")
def check_in(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Staff member checks in"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.HEAD_GARDENER, UserRole.SECURITY_GUARD, UserRole.GARDENER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # Create or update attendance record
    from app.models.attendance import Attendance
    
    today = datetime.utcnow().date()
    attendance = db.query(Attendance).filter(
        and_(
            Attendance.staff_id == current_user.id,
            Attendance.date == today
        )
    ).first()
    
    if not attendance:
        attendance = Attendance(
            staff_id=current_user.id,
            date=today,
            check_in_time=datetime.utcnow()
        )
        db.add(attendance)
    
    attendance.check_in_time = datetime.utcnow()
    db.commit()
    
    return {
        "success": True,
        "message": "Checked in successfully",
        "time": datetime.utcnow().isoformat()
    }


@router.post("/attendance/check-out")
@router.post("/check-out")
def check_out(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Staff member checks out"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.HEAD_GARDENER, UserRole.SECURITY_GUARD, UserRole.GARDENER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    from app.models.attendance import Attendance
    
    today = datetime.utcnow().date()
    attendance = db.query(Attendance).filter(
        and_(
            Attendance.staff_id == current_user.id,
            Attendance.date == today
        )
    ).first()
    
    if not attendance:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No check-in found for today")
    
    attendance.check_out_time = datetime.utcnow()
    
    # Calculate hours worked
    if attendance.check_in_time:
        hours_worked = (attendance.check_out_time - attendance.check_in_time).total_seconds() / 3600
        attendance.hours_worked = hours_worked
    
    db.commit()
    
    return {
        "success": True,
        "message": "Checked out successfully",
        "time": datetime.utcnow().isoformat(),
        "hours_worked": attendance.hours_worked
    }


@router.get("/attendance")
def get_attendance_record(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 30
):
    """Get attendance records for current staff or managed staff"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.HEAD_GARDENER, UserRole.SECURITY_GUARD, UserRole.GARDENER, UserRole.CARETAKER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    from app.models.attendance import Attendance
    
    # Get appropriate records based on role
    if current_user.role in [UserRole.SECURITY_GUARD, UserRole.GARDENER]:
        # Staff member sees only their own
        records = db.query(Attendance)\
            .filter(Attendance.staff_id == current_user.id)\
            .order_by(desc(Attendance.date))\
            .offset(skip)\
            .limit(limit)\
            .all()
    else:
        # Supervisors see their team
        records = db.query(Attendance)\
            .order_by(desc(Attendance.date))\
            .offset(skip)\
            .limit(limit)\
            .all()
    
    return {
        "success": True,
        "records_count": len(records),
        "records": [
            {
                "id": r.id,
                "staff_id": r.staff_id,
                "date": r.date.isoformat(),
                "check_in": r.check_in_time.isoformat() if r.check_in_time else None,
                "check_out": r.check_out_time.isoformat() if r.check_out_time else None,
                "hours_worked": r.hours_worked
            }
            for r in records
        ]
    }


@router.get("/attendance-summary")
def get_attendance_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    days: int = 30
):
    """Get attendance summary for period"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.HEAD_GARDENER, UserRole.CARETAKER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    from app.models.attendance import Attendance
    
    start_date = (datetime.utcnow().date()) - timedelta(days=days)
    
    records = db.query(Attendance)\
        .filter(Attendance.date >= start_date)\
        .all()
    
    total_records = len(records)
    present = len([r for r in records if r.check_in_time])
    absent = total_records - present
    
    avg_hours = 0
    if present > 0:
        total_hours = sum([r.hours_worked or 0 for r in records if r.hours_worked])
        avg_hours = total_hours / present
    
    return {
        "success": True,
        "period_days": days,
        "total_days_worked": present,
        "total_days_absent": absent,
        "attendance_rate": round((present / total_records * 100) if total_records > 0 else 0, 2),
        "average_hours_per_day": round(avg_hours, 2)
    }


# ==================== INCIDENTS (SECURITY) ====================

@router.post("/incidents")
def report_incident(
    title: str,
    description: str,
    severity: IncidentSeverity = IncidentSeverity.MEDIUM,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Report a security incident"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.SECURITY_GUARD]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # Get staff record
    staff = db.query(Staff).filter(Staff.user_id == current_user.id).first()
    if not staff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff record not found")
    
    incident = Incident(
        staff_id=staff.id,
        property_id=staff.property_id,
        title=title,
        description=description,
        severity=severity,
        reported_at=datetime.utcnow()
    )
    
    db.add(incident)
    db.commit()
    db.refresh(incident)
    
    return {
        "success": True,
        "incident_id": incident.id,
        "status": "reported",
        "created_at": incident.reported_at.isoformat()
    }


@router.get("/incidents")
def get_incidents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 50
):
    """Get incidents reported by or visible to current user"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.SECURITY_GUARD, UserRole.CARETAKER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    incidents = db.query(Incident)\
        .order_by(desc(Incident.reported_at))\
        .offset(skip)\
        .limit(limit)\
        .all()
    
    return {
        "success": True,
        "incidents_count": len(incidents),
        "incidents": [
            {
                "id": i.id,
                "title": i.title,
                "description": i.description,
                "severity": i.severity,
                "reported_at": i.reported_at.isoformat(),
                "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
                "status": "resolved" if i.resolved_at else "open"
            }
            for i in incidents
        ]
    }


@router.put("/incidents/{incident_id}/resolve")
def resolve_incident(
    incident_id: int,
    notes: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Resolve an incident"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.CARETAKER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    
    incident.resolved_at = datetime.utcnow()
    if notes:
        incident.description = f"{incident.description}\n\nResolution: {notes}"
    
    db.commit()
    
    return {
        "success": True,
        "incident_id": incident_id,
        "resolved_at": incident.resolved_at.isoformat()
    }


# ==================== TASKS (GARDENING/SECURITY) ====================

@router.post("/tasks")
def create_task(
    assigned_to: int,
    title: str,
    description: str,
    due_date: datetime,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a task (for supervisors)"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.HEAD_GARDENER, UserRole.CARETAKER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # Get staff record for current user
    staff = db.query(Staff).filter(Staff.user_id == current_user.id).first()
    if not staff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff record not found")
    
    task = Task(
        assigned_to=assigned_to,
        property_id=staff.property_id,
        title=title,
        description=description,
        status=TaskStatus.PENDING,
        due_date=due_date
    )
    
    db.add(task)
    db.commit()
    db.refresh(task)
    
    return {
        "success": True,
        "task_id": task.id,
        "status": "created",
        "created_at": datetime.utcnow().isoformat()
    }


@router.get("/tasks")
def get_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 50
):
    """Get tasks assigned to current user or managed by current user"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.HEAD_GARDENER, UserRole.SECURITY_GUARD, UserRole.GARDENER, UserRole.CARETAKER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    if current_user.role in [UserRole.SECURITY_GUARD, UserRole.GARDENER]:
        # Staff sees tasks assigned to them
        tasks = db.query(Task)\
            .filter(Task.assigned_to == current_user.id)\
            .order_by(desc(Task.due_date))\
            .offset(skip)\
            .limit(limit)\
            .all()
    else:
        # Supervisors see all tasks
        tasks = db.query(Task)\
            .order_by(desc(Task.due_date))\
            .offset(skip)\
            .limit(limit)\
            .all()
    
    return {
        "success": True,
        "tasks_count": len(tasks),
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "status": t.status,
                "due_date": t.due_date.isoformat(),
                "completed_at": t.completed_at.isoformat() if t.completed_at else None
            }
            for t in tasks
        ]
    }


class TaskUpdate(BaseModel):
    status: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None


@router.put("/tasks/{task_id}/status")
def update_task_status(
    task_id: int,
    task_status: TaskStatus,
    notes: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update task status"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    # Verify authorization
    if current_user.role in [UserRole.SECURITY_GUARD, UserRole.GARDENER]:
        if task.assigned_to != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    elif current_user.role not in [UserRole.HEAD_SECURITY, UserRole.HEAD_GARDENER, UserRole.CARETAKER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    task.status = task_status
    if task_status == TaskStatus.COMPLETED:
        task.completed_at = datetime.utcnow()

    db.commit()

    return {
        "success": True,
        "task_id": task_id,
        "status": task_status,
        "updated_at": datetime.utcnow().isoformat()
    }


@router.put("/tasks/{task_id}")
def update_task(
    task_id: int,
    task_data: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a task (simple PUT endpoint)"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    # Verify authorization
    if current_user.role in [UserRole.SECURITY_GUARD, UserRole.GARDENER]:
        if task.assigned_to != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    elif current_user.role not in [UserRole.HEAD_SECURITY, UserRole.HEAD_GARDENER, UserRole.CARETAKER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if task_data.status is not None:
        try:
            task.status = TaskStatus(task_data.status)
            if task.status == TaskStatus.COMPLETED:
                task.completed_at = datetime.utcnow()
        except ValueError:
            pass
    if task_data.title is not None:
        task.title = task_data.title
    if task_data.description is not None:
        task.description = task_data.description

    db.commit()

    return {
        "success": True,
        "task_id": task_id,
        "status": task.status.value if task.status else None,
        "updated_at": datetime.utcnow().isoformat()
    }


# ==================== PERFORMANCE ====================

@router.get("/dashboard")
def get_staff_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get staff member's dashboard"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.HEAD_GARDENER, UserRole.SECURITY_GUARD, UserRole.GARDENER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    from app.models.attendance import Attendance
    
    today = datetime.utcnow().date()
    
    # Get today's attendance
    attendance = db.query(Attendance).filter(
        and_(
            Attendance.staff_id == current_user.id,
            Attendance.date == today
        )
    ).first()
    
    # Get assigned tasks
    tasks = db.query(Task)\
        .filter(Task.assigned_to == current_user.id)\
        .all()
    
    pending_tasks = len([t for t in tasks if t.status == TaskStatus.PENDING])
    completed_tasks = len([t for t in tasks if t.status == TaskStatus.COMPLETED])
    
    return {
        "success": True,
        "user": current_user.full_name,
        "role": current_user.role,
        "timestamp": datetime.utcnow().isoformat(),
        "today": {
            "check_in": attendance.check_in_time.isoformat() if attendance and attendance.check_in_time else None,
            "check_out": attendance.check_out_time.isoformat() if attendance and attendance.check_out_time else None,
            "hours_worked": attendance.hours_worked if attendance else 0
        },
        "tasks": {
            "total": len(tasks),
            "pending": pending_tasks,
            "completed": completed_tasks
        }
    }


@router.get("/performance")
def get_performance_metrics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    days: int = 30
):
    """Get performance metrics for staff member or team"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.HEAD_GARDENER, UserRole.SECURITY_GUARD, UserRole.GARDENER, UserRole.CARETAKER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    from app.models.attendance import Attendance
    
    start_date = (datetime.utcnow().date()) - timedelta(days=days)
    
    # Get attendance data
    records = db.query(Attendance)\
        .filter(Attendance.date >= start_date)\
        .all()
    
    # Get task completion
    tasks = db.query(Task)\
        .filter(Task.completed_at >= datetime.combine(start_date, datetime.min.time()))\
        .all()
    
    completed_tasks = len([t for t in tasks if t.status == TaskStatus.COMPLETED])
    
    return {
        "success": True,
        "period_days": days,
        "metrics": {
            "attendance_rate": round((len([r for r in records if r.check_in_time]) / len(records) * 100) if records else 0, 2),
            "tasks_completed": completed_tasks,
            "average_hours_per_day": round(sum([r.hours_worked or 0 for r in records]) / len(records) if records else 0, 2)
        }
    }


# ==================== MAINTENANCE (FOR STAFF) ====================

@router.get("/maintenance")
def get_staff_maintenance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get maintenance requests assigned to or visible by staff"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.HEAD_GARDENER, UserRole.SECURITY_GUARD, UserRole.GARDENER, UserRole.CARETAKER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    from app.models.maintenance import MaintenanceRequest, MaintenanceStatus

    # Get maintenance requests
    requests = db.query(MaintenanceRequest).order_by(desc(MaintenanceRequest.created_at)).all()

    # Calculate stats
    total = len(requests)
    pending = len([r for r in requests if r.status == MaintenanceStatus.PENDING])
    in_progress = len([r for r in requests if r.status == MaintenanceStatus.IN_PROGRESS])
    completed = len([r for r in requests if r.status == MaintenanceStatus.COMPLETED])

    request_list = []
    for req in requests:
        request_list.append({
            "id": str(req.id),
            "title": req.title,
            "description": req.description,
            "status": req.status.value if req.status else "pending",
            "priority": req.priority.value if req.priority else "medium",
            "unit_id": str(req.unit_id) if req.unit_id else None,
            "created_at": req.created_at.isoformat() if req.created_at else None,
            "updated_at": req.updated_at.isoformat() if req.updated_at else None
        })

    return {
        "success": True,
        "total": total,
        "pending": pending,
        "in_progress": in_progress,
        "completed": completed,
        "requests": request_list
    }


class MaintenanceUpdate(BaseModel):
    status: Optional[str] = None


@router.put("/maintenance/{request_id}")
def update_maintenance_request(
    request_id: str,
    maintenance_data: MaintenanceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a maintenance request status"""
    if current_user.role not in [UserRole.HEAD_SECURITY, UserRole.HEAD_GARDENER, UserRole.SECURITY_GUARD, UserRole.GARDENER, UserRole.CARETAKER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    from app.models.maintenance import MaintenanceRequest, MaintenanceStatus

    maintenance = db.query(MaintenanceRequest).filter(MaintenanceRequest.id == request_id).first()
    if not maintenance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance request not found")

    if maintenance_data.status is not None:
        try:
            maintenance.status = MaintenanceStatus(maintenance_data.status)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")

    maintenance.updated_at = datetime.utcnow()
    db.commit()

    return {
        "success": True,
        "message": "Maintenance request updated successfully",
        "id": str(maintenance.id),
        "status": maintenance.status.value if maintenance.status else None
    }