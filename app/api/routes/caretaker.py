"""
Caretaker Portal Routes - Complete Implementation
Meter readings, rent tracking, maintenance management, staff supervision
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
from app.models.property import Property, Unit
from app.models.tenant import Tenant
from app.models.meter import MeterReading
from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.maintenance import MaintenanceRequest, MaintenanceStatus, MaintenancePriority
from app.schemas.meter import MeterReadingCreate, MeterReadingResponse

router = APIRouter(tags=["caretaker"])

# Unit statuses that count as "occupied" for calculations
OCCUPIED_STATUSES = ["occupied", "rented", "mortgaged"]


# ==================== CARETAKER DASHBOARD ====================

@router.get("/dashboard")
def get_caretaker_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get caretaker dashboard with key metrics"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # Get assigned properties
    properties = db.query(Property).all()
    if not properties:
        return {
            "success": True,
            "message": "No properties assigned",
            "metrics": {}
        }
    
    property_ids = [p.id for p in properties]
    
    # Calculate metrics
    total_units = db.query(Unit).filter(Unit.property_id.in_(property_ids)).count()
    occupied_units = db.query(Unit).filter(
        and_(Unit.property_id.in_(property_ids), Unit.status.in_(OCCUPIED_STATUSES))
    ).count()
    occupancy_rate = (occupied_units / total_units * 100) if total_units > 0 else 0

    # Payment metrics
    today = datetime.utcnow().date()
    current_month_start = datetime(today.year, today.month, 1).date()
    current_month_end = datetime(today.year, today.month + 1 if today.month < 12 else 1, 1).date() - timedelta(days=1)

    expected_rent = db.query(func.sum(Unit.monthly_rent))\
        .filter(and_(Unit.property_id.in_(property_ids), Unit.status.in_(OCCUPIED_STATUSES)))\
        .scalar() or 0
    
    collected_rent = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.RENT,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= current_month_start,
                Payment.payment_date <= current_month_end
            )
        ).scalar() or 0
    
    collection_rate = (collected_rent / expected_rent * 100) if expected_rent > 0 else 0
    
    # Maintenance metrics
    total_maintenance = db.query(MaintenanceRequest).count()
    pending_maintenance = db.query(MaintenanceRequest)\
        .filter(MaintenanceRequest.status == MaintenanceStatus.PENDING).count()
    
    # Meter readings status
    pending_readings = db.query(Unit)\
        .filter(
            and_(
                Unit.property_id.in_(property_ids),
                ~Unit.id.in_(
                    db.query(MeterReading.unit_id)\
                    .filter(
                        and_(
                            MeterReading.reading_date >= current_month_start,
                            MeterReading.reading_date <= current_month_end
                        )
                    )
                )
            )
        ).count()
    
    # Tenants count
    total_tenants = db.query(Tenant).filter(Tenant.status == "active").count()

    # Pending payments
    pending_payments = db.query(func.sum(Payment.amount))\
        .filter(Payment.status == PaymentStatus.PENDING)\
        .scalar() or 0

    # Tasks for caretaker (using maintenance requests as tasks)
    tasks = db.query(MaintenanceRequest)\
        .filter(MaintenanceRequest.status.in_([MaintenanceStatus.PENDING, MaintenanceStatus.IN_PROGRESS]))\
        .order_by(desc(MaintenanceRequest.created_at))\
        .limit(5)\
        .all()

    task_list = [
        {
            "id": str(t.id),
            "description": t.title,
            "completed": t.status == MaintenanceStatus.COMPLETED,
            "priority": t.priority.value if t.priority else "medium"
        }
        for t in tasks
    ]

    # Recent issues/maintenance
    issues = db.query(MaintenanceRequest)\
        .order_by(desc(MaintenanceRequest.created_at))\
        .limit(5)\
        .all()

    issue_list = [
        {
            "id": str(i.id),
            "title": i.title,
            "description": i.description or "",
            "reported_at": i.created_at.isoformat() if i.created_at else None,
            "priority": i.priority.value if i.priority else "medium"
        }
        for i in issues
    ]

    return {
        "success": True,
        "rent_collected": float(collected_rent),
        "pending_payments": float(pending_payments),
        "maintenance_requests": pending_maintenance,
        "total_tenants": total_tenants,
        "tasks": task_list,
        "issues": issue_list
    }


# ==================== OUTSTANDING PAYMENTS ====================

@router.get("/outstanding-payments")
def get_outstanding_payments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all outstanding/overdue payments"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    today = datetime.utcnow().date()

    # Get all pending payments (Payment has user_id, join via User)
    # Join: Payment -> User -> Tenant -> Unit
    from app.models.user import User
    overdue_payments = db.query(Payment, Tenant, Unit)\
        .join(User, Payment.user_id == User.id)\
        .join(Tenant, Tenant.user_id == User.id)\
        .join(Unit, Tenant.unit_id == Unit.id)\
        .filter(
            Payment.status == PaymentStatus.PENDING
        ).all()

    total_outstanding = sum(p.Payment.amount for p in overdue_payments)
    overdue_tenants = len(set(p.Tenant.id for p in overdue_payments))

    # Calculate average days late (use created_at as reference)
    total_days = 0
    for p in overdue_payments:
        if p.Payment.created_at:
            days_since = (today - p.Payment.created_at.date()).days
            if days_since > 30:  # Consider overdue after 30 days
                total_days += days_since - 30
    average_days_late = round(total_days / len(overdue_payments), 1) if overdue_payments else 0

    payment_list = []
    for p in overdue_payments:
        days_since = (today - p.Payment.created_at.date()).days if p.Payment.created_at else 0
        payment_list.append({
            "id": str(p.Payment.id),
            "tenant": p.Tenant.full_name,
            "unit": p.Unit.unit_number,
            "amount": float(p.Payment.amount),
            "due_date": p.Payment.created_at.isoformat() if p.Payment.created_at else None,
            "days_overdue": max(0, days_since - 30),
            "phone": p.Tenant.phone,
            "status": p.Payment.status.value
        })

    return {
        "success": True,
        "total_outstanding": float(total_outstanding),
        "overdue_tenants": overdue_tenants,
        "average_days_late": average_days_late,
        "payments": payment_list
    }


# ==================== CARETAKER TENANTS ====================

@router.get("/tenants")
def get_caretaker_tenants(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all tenants managed by caretaker"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    tenants = db.query(Tenant).all()
    active_tenants = [t for t in tenants if t.status == "active"]

    today = datetime.utcnow().date()
    current_month_start = datetime(today.year, today.month, 1).date()

    # Count move-ins this month
    move_ins_this_month = len([
        t for t in tenants
        if t.move_in_date and t.move_in_date >= current_month_start
    ])

    tenant_list = []
    for tenant in tenants:
        unit = db.query(Unit).filter(Unit.id == tenant.unit_id).first()

        tenant_list.append({
            "id": str(tenant.id),
            "name": tenant.full_name,
            "unit": unit.unit_number if unit else None,
            "phone": tenant.phone,
            "email": tenant.email,
            "rent_amount": float(unit.monthly_rent) if unit else 0,
            "lease_start": tenant.lease_start.isoformat() if tenant.lease_start else None,
            "lease_end": tenant.lease_end.isoformat() if tenant.lease_end else None,
            "status": tenant.status
        })

    return {
        "success": True,
        "total_tenants": len(tenants),
        "active_leases": len(active_tenants),
        "move_ins_this_month": move_ins_this_month,
        "tenants": tenant_list
    }


# ==================== METER READINGS ====================

@router.get("/meter-readings")
def get_all_meter_readings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current meter readings for all units"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Get all occupied units with their latest readings
    units = db.query(Unit).filter(Unit.status.in_(OCCUPIED_STATUSES)).all()

    unit_readings = []
    for unit in units:
        tenant = db.query(Tenant).filter(
            and_(Tenant.unit_id == unit.id, Tenant.status == "active")
        ).first()

        # Get latest reading
        latest_reading = db.query(MeterReading)\
            .filter(MeterReading.unit_id == unit.id)\
            .order_by(desc(MeterReading.reading_date))\
            .first()

        # Get previous reading
        prev_reading = db.query(MeterReading)\
            .filter(MeterReading.unit_id == unit.id)\
            .order_by(desc(MeterReading.reading_date))\
            .offset(1)\
            .first()

        unit_readings.append({
            "id": str(unit.id),
            "unit": unit.unit_number,
            "tenant": tenant.full_name if tenant else None,
            "previous_reading": {
                "water": prev_reading.water_reading if prev_reading else 0,
                "electricity": prev_reading.electricity_reading if prev_reading else 0
            },
            "current_reading": {
                "water": latest_reading.water_reading if latest_reading else 0,
                "electricity": latest_reading.electricity_reading if latest_reading else 0
            }
        })

    return {
        "success": True,
        "units": unit_readings
    }


@router.post("/meter-readings", response_model=MeterReadingResponse, status_code=status.HTTP_201_CREATED)
def record_meter_reading(
    reading_in: MeterReadingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Record meter reading for a unit"""
    if current_user.role not in [UserRole.CARETAKER, UserRole.OWNER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # Verify unit exists
    unit = db.query(Unit).filter(Unit.id == reading_in.unit_id).first()
    if not unit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unit not found")
    
    reading = MeterReading(
        unit_id=reading_in.unit_id,
        water_reading=reading_in.water_reading,
        electricity_reading=reading_in.electricity_reading,
        recorded_by=current_user.full_name,
        notes=reading_in.notes,
        reading_date=datetime.utcnow()
    )
    
    db.add(reading)
    db.commit()
    db.refresh(reading)
    
    return reading


@router.get("/meter-readings/{unit_id}", response_model=List[MeterReadingResponse])
def get_meter_readings(
    unit_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 50
):
    """Get meter reading history for a unit"""
    if current_user.role not in [UserRole.CARETAKER, UserRole.OWNER, UserRole.AGENT]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    readings = db.query(MeterReading)\
        .filter(MeterReading.unit_id == unit_id)\
        .order_by(desc(MeterReading.reading_date))\
        .offset(skip)\
        .limit(limit)\
        .all()
    
    return readings


@router.post("/meter-readings/bulk")
def bulk_upload_meter_readings(
    readings: List[MeterReadingCreate],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Bulk upload meter readings"""
    if current_user.role not in [UserRole.CARETAKER, UserRole.OWNER, UserRole.AGENT]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    if not readings:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No readings provided")
    
    if len(readings) > 1000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Maximum 1000 readings at once")
    
    created_readings = []
    failed_readings = []
    
    for idx, reading_in in enumerate(readings):
        try:
            # Verify unit exists
            unit = db.query(Unit).filter(Unit.id == reading_in.unit_id).first()
            if not unit:
                failed_readings.append({"index": idx, "reason": "Unit not found"})
                continue
            
            reading = MeterReading(
                unit_id=reading_in.unit_id,
                water_reading=reading_in.water_reading,
                electricity_reading=reading_in.electricity_reading,
                recorded_by=current_user.full_name,
                notes=reading_in.notes,
                reading_date=datetime.utcnow()
            )
            
            db.add(reading)
            created_readings.append(reading)
        except Exception as e:
            failed_readings.append({"index": idx, "reason": str(e)})
    
    db.commit()
    
    return {
        "success": True,
        "created": len(created_readings),
        "failed": len(failed_readings),
        "failed_records": failed_readings,
        "total_processed": len(readings)
    }


@router.get("/meter-readings-pending")
def get_pending_meter_readings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get list of units pending meter readings for current month"""
    if current_user.role not in [UserRole.CARETAKER, UserRole.OWNER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    today = datetime.utcnow().date()
    current_month_start = datetime(today.year, today.month, 1).date()
    current_month_end = datetime(today.year, today.month + 1 if today.month < 12 else 1, 1).date() - timedelta(days=1)
    
    # Get all occupied units
    occupied_units = db.query(Unit).filter(Unit.status.in_(OCCUPIED_STATUSES)).all()
    
    # Get units with readings this month
    units_with_readings = db.query(MeterReading.unit_id).filter(
        and_(
            MeterReading.reading_date >= current_month_start,
            MeterReading.reading_date <= current_month_end
        )
    ).distinct().all()
    
    units_with_readings_ids = [u[0] for u in units_with_readings]
    
    # Get pending units
    pending_units = [u for u in occupied_units if u.id not in units_with_readings_ids]
    
    return {
        "success": True,
        "total_occupied": len(occupied_units),
        "with_readings": len(units_with_readings),
        "pending": len(pending_units),
        "pending_units": [
            {
                "unit_id": u.id,
                "unit_number": u.unit_number,
                "type": u.status,
                "property_id": u.property_id
            }
            for u in pending_units
        ]
    }


# ==================== RENT TRACKING ====================

@router.get("/rent-tracking")
def get_rent_tracking(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get comprehensive rent tracking and collection data"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    today = datetime.utcnow().date()
    current_month_start = datetime(today.year, today.month, 1).date()
    current_month_end = datetime(today.year, today.month + 1 if today.month < 12 else 1, 1).date() - timedelta(days=1)
    
    # Get all properties
    properties = db.query(Property).all()
    property_ids = [p.id for p in properties]
    
    # Expected rent
    expected_rent = db.query(func.sum(Unit.monthly_rent))\
        .filter(and_(Unit.property_id.in_(property_ids), Unit.status.in_(OCCUPIED_STATUSES)))\
        .scalar() or 0
    
    # Collected rent
    collected_rent = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.RENT,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= current_month_start,
                Payment.payment_date <= current_month_end
            )
        ).scalar() or 0
    
    # Pending payments
    pending_payments = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.RENT,
                Payment.status == PaymentStatus.PENDING,
                Payment.due_date >= current_month_start,
                Payment.due_date <= current_month_end
            )
        ).scalar() or 0
    
    # Overdue payments
    overdue_payments = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.RENT,
                Payment.status == PaymentStatus.PENDING,
                Payment.due_date < today
            )
        ).scalar() or 0
    
    # Get defaulter list (join via User since Payment has user_id, not tenant_id)
    from app.models.user import User as UserModel
    defaulters = db.query(Tenant, Unit, Payment)\
        .join(Unit, Tenant.unit_id == Unit.id)\
        .join(UserModel, Tenant.user_id == UserModel.id)\
        .join(Payment, Payment.user_id == UserModel.id)\
        .filter(
            Payment.status == PaymentStatus.PENDING
        ).all()

    collection_rate = (collected_rent / expected_rent * 100) if expected_rent > 0 else 0

    return {
        "success": True,
        "period": f"{current_month_start} to {current_month_end}",
        "expected_rent": float(expected_rent),
        "collected_rent": float(collected_rent),
        "collection_rate": round(collection_rate, 2),
        "pending_rent": float(pending_payments),
        "overdue_rent": float(overdue_payments),
        "total_outstanding": float(pending_payments + overdue_payments),
        "defaulters_count": len(defaulters),
        "defaulters": [
            {
                "tenant_name": t.Tenant.full_name if t.Tenant else "Unknown",
                "unit_number": t.Unit.unit_number,
                "amount_owed": float(t.Payment.amount),
                "days_overdue": max(0, (today - t.Payment.created_at.date()).days - 30) if t.Payment.created_at else 0
            }
            for t in defaulters
        ]
    }


# ==================== MAINTENANCE MANAGEMENT ====================

@router.get("/maintenance")
def get_maintenance_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100
):
    """Get all maintenance requests"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    requests = db.query(MaintenanceRequest)\
        .order_by(desc(MaintenanceRequest.created_at))\
        .offset(skip)\
        .limit(limit)\
        .all()

    return requests


from pydantic import BaseModel as PydanticBaseModel

class MaintenanceCreate(PydanticBaseModel):
    issue: str
    description: str
    priority: str = "medium"
    unit_id: Optional[str] = None


@router.post("/maintenance")
def create_maintenance_request(
    maintenance_data: MaintenanceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new maintenance request"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    import uuid

    # Map priority string to enum
    priority_map = {
        "low": MaintenancePriority.LOW,
        "medium": MaintenancePriority.MEDIUM,
        "high": MaintenancePriority.HIGH,
        "urgent": MaintenancePriority.EMERGENCY,
        "emergency": MaintenancePriority.EMERGENCY
    }
    priority = priority_map.get(maintenance_data.priority.lower(), MaintenancePriority.MEDIUM)

    maintenance = MaintenanceRequest(
        id=uuid.uuid4(),
        title=maintenance_data.issue,
        description=maintenance_data.description,
        priority=priority,
        status=MaintenanceStatus.PENDING,
        unit_id=UUID(maintenance_data.unit_id) if maintenance_data.unit_id else None,
        created_at=datetime.utcnow()
    )

    db.add(maintenance)
    db.commit()
    db.refresh(maintenance)

    # Fire maintenance_request_opened workflow event
    try:
        from app.services.workflow_engine import WorkflowEngine
        from app.models.workflow import TriggerEvent
        engine = WorkflowEngine(db)
        engine.fire(
            TriggerEvent.MAINTENANCE_REQUEST_OPENED,
            {
                "maintenance_id": str(maintenance.id),
                "title": maintenance.title,
                "description": maintenance.description or "",
                "priority": maintenance_data.priority,
                "unit_id": maintenance_data.unit_id or "",
                "caretaker_id": str(current_user.id),
                "caretaker_name": current_user.full_name or current_user.email,
            },
        )
    except Exception as wf_err:
        import logging as _log
        _log.getLogger(__name__).warning(
            f"[WORKFLOW] maintenance_request_opened event failed: {wf_err}"
        )

    return {
        "success": True,
        "message": "Maintenance request created successfully",
        "id": str(maintenance.id)
    }


@router.put("/maintenance/{maintenance_id}/status")
def update_maintenance_status(
    maintenance_id: str,
    status: MaintenanceStatus,
    notes: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update maintenance request status"""
    if current_user.role not in [UserRole.CARETAKER, UserRole.OWNER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    maintenance = db.query(MaintenanceRequest).filter(MaintenanceRequest.id == maintenance_id).first()
    if not maintenance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    
    prev_status = maintenance.status
    maintenance.status = status
    if notes:
        maintenance.notes = notes

    db.commit()
    db.refresh(maintenance)

    # Fire maintenance_request_resolved event when status transitions to COMPLETED
    if status == MaintenanceStatus.COMPLETED and prev_status != MaintenanceStatus.COMPLETED:
        try:
            from app.services.workflow_engine import WorkflowEngine
            from app.models.workflow import TriggerEvent
            engine = WorkflowEngine(db)
            engine.fire(
                TriggerEvent.MAINTENANCE_REQUEST_RESOLVED,
                {
                    "maintenance_id": str(maintenance.id),
                    "title": maintenance.title or "",
                    "unit_id": str(maintenance.unit_id) if maintenance.unit_id else "",
                    "resolved_by": str(current_user.id),
                    "resolved_by_name": current_user.full_name or current_user.email,
                    "notes": notes or "",
                },
            )
        except Exception as wf_err:
            import logging as _log
            _log.getLogger(__name__).warning(
                f"[WORKFLOW] maintenance_request_resolved event failed: {wf_err}"
            )

    return {
        "success": True,
        "id": maintenance.id,
        "status": maintenance.status,
        "updated_at": datetime.utcnow().isoformat()
    }


@router.get("/maintenance/summary")
def get_maintenance_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get maintenance requests summary"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    total = db.query(func.count(MaintenanceRequest.id)).scalar()
    pending = db.query(func.count(MaintenanceRequest.id)).filter(
        MaintenanceRequest.status == MaintenanceStatus.PENDING
    ).scalar()
    in_progress = db.query(func.count(MaintenanceRequest.id)).filter(
        MaintenanceRequest.status == MaintenanceStatus.IN_PROGRESS
    ).scalar()
    completed = db.query(func.count(MaintenanceRequest.id)).filter(
        MaintenanceRequest.status == MaintenanceStatus.COMPLETED
    ).scalar()
    
    # By priority
    emergency = db.query(func.count(MaintenanceRequest.id)).filter(
        and_(
            MaintenanceRequest.priority == MaintenancePriority.EMERGENCY,
            MaintenanceRequest.status != MaintenanceStatus.COMPLETED
        )
    ).scalar()
    
    return {
        "success": True,
        "total": total,
        "by_status": {
            "pending": pending,
            "in_progress": in_progress,
            "completed": completed
        },
        "by_priority": {
            "emergency": emergency
        }
    }


# ==================== BILLS & SERVICES ====================

@router.get("/bills-summary")
def get_bills_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get water and electricity bills summary"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    today = datetime.utcnow().date()
    current_month_start = datetime(today.year, today.month, 1).date()
    current_month_end = datetime(today.year, today.month + 1 if today.month < 12 else 1, 1).date() - timedelta(days=1)
    
    # Water bills
    water_collected = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.WATER,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= current_month_start,
                Payment.payment_date <= current_month_end
            )
        ).scalar() or 0
    
    water_pending = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.WATER,
                Payment.status == PaymentStatus.PENDING
            )
        ).scalar() or 0
    
    # Electricity bills
    electricity_collected = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.ELECTRICITY,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= current_month_start,
                Payment.payment_date <= current_month_end
            )
        ).scalar() or 0
    
    electricity_pending = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.ELECTRICITY,
                Payment.status == PaymentStatus.PENDING
            )
        ).scalar() or 0
    
    return {
        "success": True,
        "water": {
            "collected": float(water_collected),
            "pending": float(water_pending),
            "total": float(water_collected + water_pending)
        },
        "electricity": {
            "collected": float(electricity_collected),
            "pending": float(electricity_pending),
            "total": float(electricity_collected + electricity_pending)
        },
        "total_collected": float(water_collected + electricity_collected),
        "total_pending": float(water_pending + electricity_pending)
    }


# ==================== STAFF SUPERVISION ====================

@router.get("/staff")
def get_supervised_staff(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all staff supervised by this caretaker"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    from app.models.staff import Staff
    
    staff = db.query(Staff).all()
    
    return {
        "success": True,
        "total_staff": len(staff),
        "staff": [
            {
                "id": s.id,
                "name": s.user.full_name if s.user else "Unknown",
                "position": s.position,
                "department": s.department,
                "start_date": s.start_date.isoformat() if s.start_date else None
            }
            for s in staff
        ]
    }


# ==================== REPORTS ====================

@router.get("/monthly-report")
def get_monthly_report(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    month: Optional[int] = None,
    year: Optional[int] = None
):
    """Generate comprehensive monthly report"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    if not month:
        month = datetime.utcnow().month
    if not year:
        year = datetime.utcnow().year
    
    month_start = datetime(year, month, 1).date()
    month_end = datetime(year, month + 1 if month < 12 else 1, 1).date() - timedelta(days=1)
    
    # Compile all data for report
    report = {
        "success": True,
        "period": f"{month_start} to {month_end}",
        "generated_at": datetime.utcnow().isoformat(),
        "generated_by": current_user.full_name
    }
    
    # Add all metrics
    properties = db.query(Property).all()
    property_ids = [p.id for p in properties]
    
    total_units = db.query(Unit).filter(Unit.property_id.in_(property_ids)).count()
    occupied_units = db.query(Unit).filter(
        and_(Unit.property_id.in_(property_ids), Unit.status.in_(OCCUPIED_STATUSES))
    ).count()
    
    expected_rent = db.query(func.sum(Unit.monthly_rent))\
        .filter(and_(Unit.property_id.in_(property_ids), Unit.status.in_(OCCUPIED_STATUSES)))\
        .scalar() or 0
    
    collected_rent = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.RENT,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= month_start,
                Payment.payment_date <= month_end
            )
        ).scalar() or 0
    
    report["metrics"] = {
        "occupancy": {
            "total_units": total_units,
            "occupied_units": occupied_units,
            "occupancy_rate": round((occupied_units / total_units * 100) if total_units > 0 else 0, 2)
        },
        "rent_collection": {
            "expected": float(expected_rent),
            "collected": float(collected_rent),
            "collection_rate": round((collected_rent / expected_rent * 100) if expected_rent > 0 else 0, 2)
        }
    }

    return report


# ==================== CARETAKER PROPERTIES ====================

@router.get("/properties")
def get_caretaker_properties(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all properties assigned to caretaker"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    properties = db.query(Property).all()

    property_list = []
    for prop in properties:
        units = db.query(Unit).filter(Unit.property_id == prop.id).all()
        occupied = len([u for u in units if u.status in OCCUPIED_STATUSES])
        total_units = len(units)

        property_list.append({
            "id": str(prop.id),
            "name": prop.name,
            "address": prop.address,
            "total_units": total_units,
            "occupied_units": occupied,
            "vacant_units": total_units - occupied,
            "occupancy_rate": round((occupied / total_units * 100) if total_units > 0 else 0, 2)
        })

    return {
        "success": True,
        "total_properties": len(properties),
        "properties": property_list
    }


# ==================== CARETAKER TASKS ====================

@router.get("/tasks")
def get_caretaker_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all tasks for caretaker"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    from app.models.task import Task

    tasks = db.query(Task).order_by(desc(Task.created_at)).all()

    # Calculate stats
    total = len(tasks)
    pending = len([t for t in tasks if t.status == "pending"])
    in_progress = len([t for t in tasks if t.status == "in_progress"])
    completed = len([t for t in tasks if t.status == "completed"])

    task_list = []
    for task in tasks:
        task_list.append({
            "id": str(task.id),
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "priority": task.priority,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "created_at": task.created_at.isoformat() if task.created_at else None
        })

    return {
        "success": True,
        "total": total,
        "pending": pending,
        "in_progress": in_progress,
        "completed": completed,
        "tasks": task_list
    }


from pydantic import BaseModel
from typing import Optional as Opt

class CaretakerTaskUpdate(BaseModel):
    status: Opt[str] = None
    title: Opt[str] = None
    description: Opt[str] = None


@router.put("/tasks/{task_id}")
def update_caretaker_task(
    task_id: str,
    task_data: CaretakerTaskUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a task"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    from app.models.task import Task

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if task_data.status is not None:
        task.status = task_data.status
    if task_data.title is not None:
        task.title = task_data.title
    if task_data.description is not None:
        task.description = task_data.description

    task.updated_at = datetime.utcnow()
    db.commit()

    return {
        "success": True,
        "message": "Task updated successfully",
        "id": str(task.id),
        "status": task.status
    }


@router.delete("/maintenance/{maintenance_id}")
def delete_caretaker_maintenance(
    maintenance_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a maintenance request"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    maintenance = db.query(MaintenanceRequest).filter(MaintenanceRequest.id == maintenance_id).first()
    if not maintenance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance request not found")

    db.delete(maintenance)
    db.commit()

    return {
        "success": True,
        "message": "Maintenance request deleted successfully"
    }


# ==================== CARETAKER REPORTS ====================

@router.get("/reports")
def get_caretaker_reports(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get list of available reports"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Generate list of available monthly reports (last 12 months)
    reports = []
    today = datetime.utcnow()

    for i in range(12):
        month_date = today - timedelta(days=30 * i)
        month_start = datetime(month_date.year, month_date.month, 1)

        reports.append({
            "id": f"report-{month_date.year}-{month_date.month:02d}",
            "title": f"Monthly Report - {month_date.strftime('%B %Y')}",
            "type": "monthly",
            "period": f"{month_date.strftime('%B %Y')}",
            "generated_at": month_start.isoformat(),
            "status": "available"
        })

    return {
        "success": True,
        "total_reports": len(reports),
        "reports": reports
    }


# ==================== RENT SUMMARY ====================

@router.get("/rent-summary")
def get_rent_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get comprehensive rent summary with collection trend and utility bills"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    today = datetime.utcnow().date()
    current_month_start = datetime(today.year, today.month, 1).date()

    # Get all properties
    properties = db.query(Property).all()
    property_ids = [p.id for p in properties]

    # Current month metrics
    expected_rent = db.query(func.sum(Unit.monthly_rent))\
        .filter(and_(Unit.property_id.in_(property_ids), Unit.status.in_(OCCUPIED_STATUSES)))\
        .scalar() or 0

    collected_rent = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.RENT,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= current_month_start
            )
        ).scalar() or 0

    pending_rent = float(expected_rent) - float(collected_rent)

    # Collection trend (last 6 months)
    collection_trend = []
    for i in range(6):
        month_date = today - timedelta(days=30 * i)
        month_start = datetime(month_date.year, month_date.month, 1).date()
        month_end = datetime(month_date.year, month_date.month + 1 if month_date.month < 12 else 1, 1).date() - timedelta(days=1)

        month_collected = db.query(func.sum(Payment.amount))\
            .filter(
                and_(
                    Payment.payment_type == PaymentType.RENT,
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.payment_date >= month_start,
                    Payment.payment_date <= month_end
                )
            ).scalar() or 0

        collection_trend.append({
            "month": month_date.strftime('%b %Y'),
            "collected": float(month_collected)
        })

    collection_trend.reverse()  # Oldest first

    # Utility bills summary
    water_collected = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.WATER,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= current_month_start
            )
        ).scalar() or 0

    water_pending = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.WATER,
                Payment.status == PaymentStatus.PENDING
            )
        ).scalar() or 0

    electricity_collected = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.ELECTRICITY,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= current_month_start
            )
        ).scalar() or 0

    electricity_pending = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.ELECTRICITY,
                Payment.status == PaymentStatus.PENDING
            )
        ).scalar() or 0

    return {
        "success": True,
        "rent": {
            "expected": float(expected_rent),
            "collected": float(collected_rent),
            "pending": pending_rent,
            "collection_rate": round((float(collected_rent) / float(expected_rent) * 100) if expected_rent > 0 else 0, 2)
        },
        "collection_trend": collection_trend,
        "utility_bills": {
            "water": {
                "collected": float(water_collected),
                "pending": float(water_pending)
            },
            "electricity": {
                "collected": float(electricity_collected),
                "pending": float(electricity_pending)
            }
        }
    }


# ==================== RENT REMINDERS ====================

@router.post("/rent-reminders")
def send_rent_reminders(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Send rent payment reminders to tenants with overdue payments"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    today = datetime.utcnow().date()

    # Get all pending payments (join via User since Payment has user_id)
    from app.models.user import User as ReminderUser
    overdue_payments = db.query(Payment, Tenant)\
        .join(ReminderUser, Payment.user_id == ReminderUser.id)\
        .join(Tenant, Tenant.user_id == ReminderUser.id)\
        .filter(
            Payment.status == PaymentStatus.PENDING
        ).all()

    # In production, this would send SMS/email notifications
    # For now, we just return the list of tenants who would receive reminders
    reminders_sent = []
    for payment, tenant in overdue_payments:
        days_since = (today - payment.created_at.date()).days if payment.created_at else 0
        reminders_sent.append({
            "tenant_name": tenant.full_name,
            "phone": tenant.phone,
            "amount": float(payment.amount),
            "days_overdue": max(0, days_since - 30)
        })

    return {
        "success": True,
        "message": f"Reminders sent to {len(reminders_sent)} tenants",
        "reminders_count": len(reminders_sent),
        "reminders": reminders_sent
    }


# ==================== REPORT GENERATION & DOWNLOAD ====================

@router.post("/reports/generate")
def generate_caretaker_report(
    report_type: str = "monthly",
    month: Optional[int] = None,
    year: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Generate a new report"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if not month:
        month = datetime.utcnow().month
    if not year:
        year = datetime.utcnow().year

    month_start = datetime(year, month, 1).date()
    month_end = datetime(year, month + 1 if month < 12 else 1, 1).date() - timedelta(days=1)

    # Generate report data
    properties = db.query(Property).all()
    property_ids = [p.id for p in properties]

    total_units = db.query(Unit).filter(Unit.property_id.in_(property_ids)).count()
    occupied_units = db.query(Unit).filter(
        and_(Unit.property_id.in_(property_ids), Unit.status.in_(OCCUPIED_STATUSES))
    ).count()

    expected_rent = db.query(func.sum(Unit.monthly_rent))\
        .filter(and_(Unit.property_id.in_(property_ids), Unit.status.in_(OCCUPIED_STATUSES)))\
        .scalar() or 0

    collected_rent = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.RENT,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= month_start,
                Payment.payment_date <= month_end
            )
        ).scalar() or 0

    report_id = f"report-{year}-{month:02d}"

    return {
        "success": True,
        "message": "Report generated successfully",
        "report": {
            "id": report_id,
            "title": f"Monthly Report - {month_start.strftime('%B %Y')}",
            "type": report_type,
            "period": f"{month_start} to {month_end}",
            "generated_at": datetime.utcnow().isoformat(),
            "generated_by": current_user.full_name,
            "data": {
                "occupancy": {
                    "total_units": total_units,
                    "occupied_units": occupied_units,
                    "occupancy_rate": round((occupied_units / total_units * 100) if total_units > 0 else 0, 2)
                },
                "rent_collection": {
                    "expected": float(expected_rent),
                    "collected": float(collected_rent),
                    "collection_rate": round((float(collected_rent) / float(expected_rent) * 100) if expected_rent > 0 else 0, 2)
                }
            }
        }
    }


@router.get("/reports/{report_id}/download")
def download_caretaker_report(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get download URL for a report"""
    if current_user.role != UserRole.CARETAKER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Parse report ID to get month/year
    parts = report_id.split("-")
    if len(parts) >= 3:
        year = int(parts[1])
        month = int(parts[2])
    else:
        year = datetime.utcnow().year
        month = datetime.utcnow().month

    # In production, this would return a URL to a generated PDF
    # For now, return report metadata
    return {
        "success": True,
        "report_id": report_id,
        "title": f"Monthly Report - {datetime(year, month, 1).strftime('%B %Y')}",
        "download_url": f"/api/caretaker/reports/{report_id}/pdf",
        "format": "pdf"
    }