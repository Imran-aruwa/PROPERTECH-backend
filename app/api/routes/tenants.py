"""
Tenant Portal Routes - Complete Implementation
Tenant management, payment tracking, maintenance requests, and billing
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
from typing import List, Optional
from datetime import datetime, timedelta
from uuid import UUID
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserRole
from app.models.tenant import Tenant
from app.models.property import Unit
from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.maintenance import MaintenanceRequest, MaintenanceStatus, MaintenancePriority
from app.models.meter import MeterReading
from app.schemas.tenant import (
    TenantResponse, TenantCreate, TenantUpdate,
    TenantPaymentResponse, TenantMaintenanceResponse,
    MaintenanceRequestCreate
)

router = APIRouter(tags=["tenants"])


# ==================== TENANT CRUD ====================

@router.post("/", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def create_tenant(
    tenant_in: TenantCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new tenant (Owner/Agent only)"""
    if current_user.role not in [UserRole.OWNER, UserRole.AGENT]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # Verify unit exists
    unit = db.query(Unit).filter(Unit.id == tenant_in.unit_id).first()
    if not unit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unit not found")
    
    # Check if unit already occupied
    existing_tenant = db.query(Tenant).filter(
        and_(
            Tenant.unit_id == tenant_in.unit_id,
            Tenant.move_out_date.is_(None)
        )
    ).first()
    
    if existing_tenant:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unit already occupied")
    
    tenant = Tenant(
        user_id=tenant_in.user_id,
        unit_id=tenant_in.unit_id,
        move_in_date=tenant_in.move_in_date,
        move_out_date=tenant_in.move_out_date
    )
    
    # Mark unit as occupied
    unit.status = "occupied"
    
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@router.get("/", response_model=List[TenantResponse])
def list_tenants(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all tenants (Owner/Agent) or own tenant profile"""
    if current_user.role == UserRole.OWNER:
        # Owner sees all tenants
        tenants = db.query(Tenant).offset(skip).limit(limit).all()
    elif current_user.role == UserRole.AGENT:
        # Agent sees tenants in their properties
        tenants = db.query(Tenant).offset(skip).limit(limit).all()
    elif current_user.role == UserRole.TENANT:
        # Tenant sees only their own profile
        tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
        tenants = [tenant] if tenant else []
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    return tenants


@router.get("/{tenant_id}", response_model=TenantResponse)
def get_tenant(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get tenant details"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    
    # Authorization: Tenant can only see own, Owner/Agent/Caretaker can see all
    if current_user.role == UserRole.TENANT and current_user.id != tenant.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    return tenant


@router.put("/{tenant_id}", response_model=TenantResponse)
def update_tenant(
    tenant_id: str,
    tenant_update: TenantUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update tenant information"""
    if current_user.role not in [UserRole.OWNER, UserRole.AGENT, UserRole.CARETAKER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    
    for key, value in tenant_update.dict(exclude_unset=True).items():
        setattr(tenant, key, value)
    
    db.commit()
    db.refresh(tenant)
    return tenant


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete tenant (Owner only)"""
    if current_user.role != UserRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    
    # Mark unit as vacant
    unit = db.query(Unit).filter(Unit.id == tenant.unit_id).first()
    if unit:
        unit.status = "vacant"
    
    db.delete(tenant)
    db.commit()


# ==================== TENANT PAYMENTS ====================

@router.get("/{tenant_id}/payments", response_model=List[TenantPaymentResponse])
def get_tenant_payments(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 50
):
    """Get tenant's payment history and current bills"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    
    # Authorization
    if current_user.role == UserRole.TENANT and current_user.id != tenant.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    payments = db.query(Payment)\
        .filter(Payment.tenant_id == tenant_id)\
        .order_by(desc(Payment.created_at))\
        .offset(skip)\
        .limit(limit)\
        .all()
    
    return payments


@router.get("/{tenant_id}/payment-summary")
def get_payment_summary(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get tenant's payment summary (current & overdue bills)"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    
    if current_user.role == UserRole.TENANT and current_user.id != tenant.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # Get unit details
    unit = db.query(Unit).filter(Unit.id == tenant.unit_id).first()
    
    today = datetime.utcnow().date()
    current_month_start = datetime(today.year, today.month, 1).date()
    current_month_end = datetime(today.year, today.month + 1 if today.month < 12 else 1, 1).date() - timedelta(days=1)
    
    # Get current month rent payment
    rent_payment = db.query(Payment).filter(
        and_(
            Payment.tenant_id == tenant_id,
            Payment.payment_type == PaymentType.RENT,
            Payment.due_date >= current_month_start,
            Payment.due_date <= current_month_end
        )
    ).first()
    
    # Get water bill
    water_payment = db.query(Payment).filter(
        and_(
            Payment.tenant_id == tenant_id,
            Payment.payment_type == PaymentType.WATER,
            Payment.due_date >= current_month_start,
            Payment.due_date <= current_month_end
        )
    ).first()
    
    # Get electricity bill
    electricity_payment = db.query(Payment).filter(
        and_(
            Payment.tenant_id == tenant_id,
            Payment.payment_type == PaymentType.ELECTRICITY,
            Payment.due_date >= current_month_start,
            Payment.due_date <= current_month_end
        )
    ).first()
    
    # Calculate overdue
    overdue_payments = db.query(Payment).filter(
        and_(
            Payment.tenant_id == tenant_id,
            Payment.status == PaymentStatus.PENDING,
            Payment.due_date < today
        )
    ).all()
    
    return {
        "success": True,
        "unit_number": unit.unit_number if unit else None,
        "monthly_rent": unit.monthly_rent if unit else 0,
        "rent_payment": {
            "amount": rent_payment.amount if rent_payment else unit.monthly_rent,
            "status": rent_payment.status if rent_payment else PaymentStatus.PENDING,
            "due_date": rent_payment.due_date if rent_payment else current_month_end,
            "paid_date": rent_payment.payment_date if rent_payment else None
        },
        "water_bill": {
            "amount": water_payment.amount if water_payment else 0,
            "status": water_payment.status if water_payment else PaymentStatus.PENDING,
            "due_date": water_payment.due_date if water_payment else current_month_end,
            "paid_date": water_payment.payment_date if water_payment else None
        },
        "electricity_bill": {
            "amount": electricity_payment.amount if electricity_payment else 0,
            "status": electricity_payment.status if electricity_payment else PaymentStatus.PENDING,
            "due_date": electricity_payment.due_date if electricity_payment else current_month_end,
            "paid_date": electricity_payment.payment_date if electricity_payment else None
        },
        "overdue_count": len(overdue_payments),
        "overdue_amount": sum(p.amount for p in overdue_payments),
        "total_due": sum(p.amount for p in [rent_payment, water_payment, electricity_payment] if p and p.status == PaymentStatus.PENDING)
    }


# ==================== MAINTENANCE REQUESTS ====================

@router.post("/{tenant_id}/maintenance", response_model=TenantMaintenanceResponse, status_code=status.HTTP_201_CREATED)
def submit_maintenance_request(
    tenant_id: str,
    request_in: MaintenanceRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Submit a maintenance request"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    
    # Only tenant can submit their own request
    if current_user.role == UserRole.TENANT and current_user.id != tenant.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    maintenance = MaintenanceRequest(
        tenant_id=tenant_id,
        title=request_in.title,
        description=request_in.description,
        priority=request_in.priority,
        status=MaintenanceStatus.PENDING
    )
    
    db.add(maintenance)
    db.commit()
    db.refresh(maintenance)
    return maintenance


@router.get("/{tenant_id}/maintenance", response_model=List[TenantMaintenanceResponse])
def get_maintenance_requests(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 50
):
    """Get tenant's maintenance requests"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    
    if current_user.role == UserRole.TENANT and current_user.id != tenant.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    requests = db.query(MaintenanceRequest)\
        .filter(MaintenanceRequest.tenant_id == tenant_id)\
        .order_by(desc(MaintenanceRequest.created_at))\
        .offset(skip)\
        .limit(limit)\
        .all()
    
    return requests


@router.get("/{tenant_id}/maintenance/{maintenance_id}", response_model=TenantMaintenanceResponse)
def get_maintenance_request(
    tenant_id: str,
    maintenance_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get specific maintenance request details"""
    maintenance = db.query(MaintenanceRequest)\
        .filter(
            and_(
                MaintenanceRequest.id == maintenance_id,
                MaintenanceRequest.tenant_id == tenant_id
            )
        ).first()
    
    if not maintenance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    
    if current_user.role == UserRole.TENANT and current_user.id != db.query(Tenant).filter(Tenant.id == tenant_id).first().user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    return maintenance


# ==================== METER READINGS ====================

@router.get("/{tenant_id}/meter-readings")
def get_meter_readings(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 12
):
    """Get tenant's meter reading history (water & electricity)"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    
    if current_user.role == UserRole.TENANT and current_user.id != tenant.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    readings = db.query(MeterReading)\
        .filter(MeterReading.unit_id == tenant.unit_id)\
        .order_by(desc(MeterReading.reading_date))\
        .offset(skip)\
        .limit(limit)\
        .all()
    
    return {
        "success": True,
        "unit_id": tenant.unit_id,
        "readings": [
            {
                "id": r.id,
                "date": r.reading_date.isoformat(),
                "water": r.water_reading,
                "electricity": r.electricity_reading,
                "notes": r.notes,
                "recorded_by": r.recorded_by
            }
            for r in readings
        ]
    }


@router.get("/{tenant_id}/current-bills")
def get_current_bills(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current month's bills based on meter readings"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    
    if current_user.role == UserRole.TENANT and current_user.id != tenant.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # Get latest meter readings
    latest_water = db.query(MeterReading)\
        .filter(MeterReading.unit_id == tenant.unit_id)\
        .order_by(desc(MeterReading.reading_date))\
        .first()
    
    # Get previous month's reading
    prev_water = db.query(MeterReading)\
        .filter(MeterReading.unit_id == tenant.unit_id)\
        .order_by(desc(MeterReading.reading_date))\
        .offset(1)\
        .first()
    
    # Calculate consumption
    water_consumed = 0
    electricity_consumed = 0
    
    if latest_water and prev_water:
        water_consumed = (latest_water.water_reading or 0) - (prev_water.water_reading or 0)
        electricity_consumed = (latest_water.electricity_reading or 0) - (prev_water.electricity_reading or 0)
    
    # Get rates (these should be in settings)
    water_rate = 15  # KES per unit
    electricity_rate = 30  # KES per kWh
    
    return {
        "success": True,
        "water": {
            "consumed": water_consumed,
            "rate": water_rate,
            "total": water_consumed * water_rate,
            "unit": "m³"
        },
        "electricity": {
            "consumed": electricity_consumed,
            "rate": electricity_rate,
            "total": electricity_consumed * electricity_rate,
            "unit": "kWh"
        },
        "total_bills": (water_consumed * water_rate) + (electricity_consumed * electricity_rate)
    }


# ==================== TENANT STATISTICS ====================

@router.get("/{tenant_id}/statistics")
def get_tenant_statistics(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get tenant statistics (payment history, maintenance, etc)"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    
    if current_user.role == UserRole.TENANT and current_user.id != tenant.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # Payment stats
    total_payments = db.query(Payment).filter(Payment.tenant_id == tenant_id).count()
    completed_payments = db.query(Payment).filter(
        and_(Payment.tenant_id == tenant_id, Payment.status == PaymentStatus.COMPLETED)
    ).count()
    
    # Maintenance stats
    total_maintenance = db.query(MaintenanceRequest).filter(MaintenanceRequest.tenant_id == tenant_id).count()
    completed_maintenance = db.query(MaintenanceRequest).filter(
        and_(MaintenanceRequest.tenant_id == tenant_id, MaintenanceRequest.status == MaintenanceStatus.COMPLETED)
    ).count()
    
    # Occupancy duration
    days_occupied = (datetime.utcnow().date() - tenant.move_in_date).days if tenant.move_in_date else 0
    
    return {
        "success": True,
        "move_in_date": tenant.move_in_date.isoformat() if tenant.move_in_date else None,
        "days_occupied": days_occupied,
        "payment_reliability": {
            "total_payments": total_payments,
            "completed_payments": completed_payments,
            "completion_rate": (completed_payments / total_payments * 100) if total_payments > 0 else 0
        },
        "maintenance": {
            "total_requests": total_maintenance,
            "completed": completed_maintenance,
            "pending": total_maintenance - completed_maintenance
        }
    }