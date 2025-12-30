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
        and_(Unit.property_id.in_(property_ids), Unit.is_occupied == True)
    ).count()
    occupancy_rate = (occupied_units / total_units * 100) if total_units > 0 else 0
    
    # Payment metrics
    today = datetime.utcnow().date()
    current_month_start = datetime(today.year, today.month, 1).date()
    current_month_end = datetime(today.year, today.month + 1 if today.month < 12 else 1, 1).date() - timedelta(days=1)
    
    expected_rent = db.query(func.sum(Unit.monthly_rent))\
        .filter(and_(Unit.property_id.in_(property_ids), Unit.is_occupied == True))\
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

    # Get all pending/overdue payments
    overdue_payments = db.query(Payment, Tenant, Unit)\
        .join(Tenant, Payment.tenant_id == Tenant.id)\
        .join(Unit, Tenant.unit_id == Unit.id)\
        .filter(
            and_(
                Payment.status == PaymentStatus.PENDING,
                Payment.due_date < today
            )
        ).all()

    total_outstanding = sum(p.Payment.amount for p in overdue_payments)
    overdue_tenants = len(set(p.Tenant.id for p in overdue_payments))

    # Calculate average days late
    total_days = 0
    for p in overdue_payments:
        if p.Payment.due_date:
            total_days += (today - p.Payment.due_date).days
    average_days_late = round(total_days / len(overdue_payments), 1) if overdue_payments else 0

    payment_list = []
    for p in overdue_payments:
        days_overdue = (today - p.Payment.due_date).days if p.Payment.due_date else 0
        payment_list.append({
            "id": str(p.Payment.id),
            "tenant": p.Tenant.full_name,
            "unit": p.Unit.unit_number,
            "amount": float(p.Payment.amount),
            "due_date": p.Payment.due_date.isoformat() if p.Payment.due_date else None,
            "days_overdue": days_overdue,
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
    units = db.query(Unit).filter(Unit.is_occupied == True).all()

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
    unit_id: int,
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
    occupied_units = db.query(Unit).filter(Unit.is_occupied == True).all()
    
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
                "type": u.unit_type,
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
        .filter(and_(Unit.property_id.in_(property_ids), Unit.is_occupied == True))\
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
    
    # Get defaulter list
    defaulters = db.query(Tenant, Unit, Payment)\
        .join(Unit, Tenant.unit_id == Unit.id)\
        .join(Payment, Tenant.id == Payment.tenant_id)\
        .filter(
            and_(
                Payment.payment_type == PaymentType.RENT,
                Payment.status == PaymentStatus.PENDING,
                Payment.due_date < today
            )
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
                "amount_owed": t.Payment.amount,
                "days_overdue": (today - t.Payment.due_date).days
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


@router.put("/maintenance/{maintenance_id}/status")
def update_maintenance_status(
    maintenance_id: int,
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
    
    maintenance.status = status
    if notes:
        maintenance.notes = notes
    
    db.commit()
    db.refresh(maintenance)
    
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
        and_(Unit.property_id.in_(property_ids), Unit.is_occupied == True)
    ).count()
    
    expected_rent = db.query(func.sum(Unit.monthly_rent))\
        .filter(and_(Unit.property_id.in_(property_ids), Unit.is_occupied == True))\
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