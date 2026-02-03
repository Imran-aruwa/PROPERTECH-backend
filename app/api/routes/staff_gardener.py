"""
Gardener Staff Portal Routes
Dashboard, tasks, equipment, assignments for gardening personnel
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
from app.models.task import Task, TaskStatus
from app.models.attendance import Attendance
from app.models.equipment import Equipment
from app.models.property import Property

router = APIRouter(tags=["staff-gardener"])


# ==================== SCHEMAS ====================

class TaskCreate(BaseModel):
    task: str
    time: str
    priority: str = "medium"


class EquipmentBase(BaseModel):
    name: str
    status: str = "Available"


# ==================== GARDENER DASHBOARD ====================

@router.get("/dashboard")
def get_gardener_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get gardener staff dashboard"""
    if current_user.role not in [UserRole.HEAD_GARDENER, UserRole.GARDENER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    today = datetime.utcnow().date()

    # Get today's tasks
    tasks_today = db.query(Task).filter(
        and_(
            Task.assigned_to == current_user.id,
            func.date(Task.due_date) == today
        )
    ).all()

    completed_tasks = len([t for t in tasks_today if t.status == TaskStatus.COMPLETED])

    # Get hours logged
    attendance = db.query(Attendance).filter(
        and_(
            Attendance.staff_id == current_user.id,
            Attendance.date == today
        )
    ).first()

    hours_logged = 0
    if attendance and attendance.check_in_time:
        if attendance.check_out_time:
            hours_logged = (attendance.check_out_time - attendance.check_in_time).total_seconds() / 3600
        else:
            hours_logged = (datetime.utcnow() - attendance.check_in_time).total_seconds() / 3600

    # Format today's tasks
    todays_tasks = [
        {
            "id": str(t.id),
            "task": t.title,
            "time": t.due_date.strftime("%H:%M") if t.due_date else "TBD",
            "done": t.status == TaskStatus.COMPLETED
        }
        for t in tasks_today
    ]

    # Get staff record to find their property
    staff = db.query(Staff).filter(Staff.user_id == current_user.id).first()

    # Get equipment from database for the staff's property
    equipment_query = db.query(Equipment)
    if staff and staff.property_id:
        equipment_query = equipment_query.filter(Equipment.property_id == staff.property_id)

    equipment_list = equipment_query.all()

    # Format equipment data
    equipment = [
        {
            "id": str(e.id),
            "name": e.name,
            "status": e.status.title() if e.status else "Available",
            "type": e.type,
            "description": e.description
        }
        for e in equipment_list
    ]

    # Count available equipment (status 'working' or 'available')
    equipment_available = len([e for e in equipment_list if e.status and e.status.lower() in ["working", "available"]])

    return {
        "success": True,
        "tasks_today": len(tasks_today),
        "completed": completed_tasks,
        "equipment_available": equipment_available,
        "hours_logged": round(hours_logged, 1),
        "todays_tasks": todays_tasks,
        "equipment": equipment
    }


# ==================== TASKS ====================

@router.get("/tasks")
def get_gardener_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get gardener tasks"""
    if current_user.role not in [UserRole.HEAD_GARDENER, UserRole.GARDENER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if current_user.role == UserRole.HEAD_GARDENER:
        # Head gardener sees all tasks
        tasks = db.query(Task)\
            .order_by(desc(Task.due_date))\
            .all()
    else:
        # Regular gardener sees only their tasks
        tasks = db.query(Task)\
            .filter(Task.assigned_to == current_user.id)\
            .order_by(desc(Task.due_date))\
            .all()

    return {
        "success": True,
        "tasks": [
            {
                "id": str(t.id),
                "task": t.title,
                "description": t.description,
                "time": t.due_date.strftime("%H:%M") if t.due_date else None,
                "date": t.due_date.date().isoformat() if t.due_date else None,
                "status": t.status.value,
                "done": t.status == TaskStatus.COMPLETED,
                "priority": "medium"
            }
            for t in tasks
        ]
    }


@router.post("/tasks")
def create_gardener_task(
    task_data: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new gardening task"""
    if current_user.role != UserRole.HEAD_GARDENER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only head gardener can create tasks")

    # Get staff record
    staff = db.query(Staff).filter(Staff.user_id == current_user.id).first()

    # Parse time and set due date to today at that time
    today = datetime.utcnow().date()
    try:
        hour, minute = map(int, task_data.time.split(":"))
        due_date = datetime.combine(today, datetime.min.time().replace(hour=hour, minute=minute))
    except:
        due_date = datetime.utcnow()

    task = Task(
        id=uuid.uuid4(),
        assigned_to=current_user.id,
        property_id=staff.property_id if staff else None,
        title=task_data.task,
        description=f"Priority: {task_data.priority}",
        status=TaskStatus.PENDING,
        due_date=due_date
    )

    db.add(task)
    db.commit()
    db.refresh(task)

    return {
        "success": True,
        "message": "Task created successfully",
        "task_id": str(task.id)
    }


# ==================== EQUIPMENT ====================

@router.get("/equipment")
def get_gardener_equipment(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get available equipment from database"""
    if current_user.role not in [UserRole.HEAD_GARDENER, UserRole.GARDENER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Get staff record to find their property
    staff = db.query(Staff).filter(Staff.user_id == current_user.id).first()

    # Get equipment from database for the staff's property
    equipment_query = db.query(Equipment)
    if staff and staff.property_id:
        equipment_query = equipment_query.filter(Equipment.property_id == staff.property_id)

    equipment_list = equipment_query.all()

    # Format equipment data
    equipment = [
        {
            "id": str(e.id),
            "name": e.name,
            "status": e.status.title() if e.status else "Available",
            "type": e.type,
            "description": e.description,
            "last_maintenance": e.last_maintenance,
            "notes": e.notes
        }
        for e in equipment_list
    ]

    return {
        "success": True,
        "equipment": equipment,
        "total": len(equipment)
    }


# ==================== ASSIGNMENTS ====================

@router.get("/assignments")
def get_gardener_assignments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get gardener assignments based on staff's property and completed tasks"""
    if current_user.role not in [UserRole.HEAD_GARDENER, UserRole.GARDENER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Get staff record
    staff = db.query(Staff).filter(Staff.user_id == current_user.id).first()

    assignments = []

    if staff and staff.property_id:
        # Get the property details
        property_obj = db.query(Property).filter(Property.id == staff.property_id).first()

        if property_obj:
            # Get completed gardening tasks to determine last completed dates per area
            completed_tasks = db.query(Task).filter(
                and_(
                    Task.property_id == staff.property_id,
                    Task.status == TaskStatus.COMPLETED,
                    Task.assigned_to == current_user.id
                )
            ).order_by(desc(Task.completed_at)).limit(50).all()

            # Create assignment based on property
            assignments.append({
                "id": str(staff.property_id),
                "zone": property_obj.name,
                "area": property_obj.address or "Main Area",
                "frequency": "As scheduled",
                "last_completed": completed_tasks[0].completed_at.date().isoformat() if completed_tasks and completed_tasks[0].completed_at else None,
                "total_tasks_completed": len(completed_tasks)
            })

    return {
        "success": True,
        "assignments": assignments,
        "message": "Assignments are based on your property assignment and task completion history" if assignments else "No property assignment found. Contact your supervisor."
    }


class GardenerTaskUpdate(BaseModel):
    status: Optional[str] = None
    done: Optional[bool] = None


@router.put("/tasks/{task_id}")
def update_gardener_task(
    task_id: str,
    task_data: GardenerTaskUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a gardener task"""
    if current_user.role not in [UserRole.HEAD_GARDENER, UserRole.GARDENER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if task_data.status is not None:
        try:
            task.status = TaskStatus(task_data.status)
        except ValueError:
            pass
    if task_data.done is not None:
        task.status = TaskStatus.COMPLETED if task_data.done else TaskStatus.PENDING
        if task_data.done:
            task.completed_at = datetime.utcnow()

    db.commit()

    return {
        "success": True,
        "message": "Task updated successfully",
        "id": str(task.id),
        "status": task.status.value if task.status else None
    }


class EquipmentUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


@router.put("/equipment/{equipment_id}")
def update_gardener_equipment(
    equipment_id: str,
    equipment_data: EquipmentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update equipment status in database"""
    if current_user.role not in [UserRole.HEAD_GARDENER, UserRole.GARDENER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Find the equipment in database
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()

    if not equipment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipment not found")

    # Update fields if provided
    if equipment_data.status is not None:
        equipment.status = equipment_data.status.lower()
    if equipment_data.notes is not None:
        equipment.notes = equipment_data.notes

    db.commit()
    db.refresh(equipment)

    return {
        "success": True,
        "message": "Equipment status updated successfully",
        "id": str(equipment.id),
        "name": equipment.name,
        "status": equipment.status,
        "notes": equipment.notes
    }
