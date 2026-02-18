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
import uuid as uuid_module
import logging
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserRole
from app.models.tenant import Tenant
from app.models.property import Property, Unit
from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.maintenance import MaintenanceRequest, MaintenanceStatus, MaintenancePriority
from app.models.meter import MeterReading
from app.core.security import get_password_hash
from app.schemas.tenant import (
    TenantResponse, TenantCreate, TenantUpdate,
    TenantPaymentResponse, TenantMaintenanceResponse,
    MaintenanceRequestCreate
)

router = APIRouter(tags=["tenants"])
logger = logging.getLogger(__name__)


# ==================== TENANT CRUD ====================

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_tenant(
    tenant_in: TenantCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new tenant (Owner/Agent only).

    Accepts the frontend format:
    {
        "user": { "full_name": "...", "email": "...", "phone": "...", "password": "...", "role": "tenant" },
        "unit_id": "uuid",
        "lease_start": "2026-01-01",
        "lease_end": "2027-01-01",
        "rent_amount": 25000,
        "deposit_amount": 50000,
        "emergency_contact_name": "...",
        "emergency_contact_phone": "...",
        "notes": "..."
    }
    """
    if current_user.role not in [UserRole.OWNER, UserRole.AGENT, UserRole.ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    logger.info(f"[CREATE_TENANT] Received data: user={tenant_in.user}, unit_id={tenant_in.unit_id}")

    # Resolve tenant details from nested user object or flat fields
    full_name = tenant_in.full_name
    email = tenant_in.email
    phone = tenant_in.phone
    id_number = tenant_in.id_number
    password = "TempPass123!"

    if tenant_in.user:
        full_name = tenant_in.user.full_name or full_name
        email = tenant_in.user.email or email
        phone = tenant_in.user.phone or phone
        id_number = tenant_in.user.id_number or id_number
        password = tenant_in.user.password or password

    if not full_name or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="full_name and email are required (either directly or via user object)"
        )

    # Verify unit exists
    unit = None
    if tenant_in.unit_id:
        try:
            unit_uuid = uuid_module.UUID(str(tenant_in.unit_id))
            unit = db.query(Unit).filter(Unit.id == unit_uuid).first()
        except (ValueError, AttributeError):
            unit = db.query(Unit).filter(Unit.id == str(tenant_in.unit_id)).first()
        if not unit:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unit not found")

        # Check if unit already occupied
        existing_tenant = db.query(Tenant).filter(
            and_(
                Tenant.unit_id == unit.id,
                Tenant.status == "active",
                Tenant.move_out_date.is_(None)
            )
        ).first()

        if existing_tenant:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unit already has an active tenant")

    # Create or find user account for the tenant
    user_id = tenant_in.user_id
    if not user_id:
        # Check if user with this email already exists
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            user_id = existing_user.id
            logger.info(f"[CREATE_TENANT] Found existing user: {user_id}")
        else:
            # Create a new user account
            name_parts = full_name.strip().split(" ", 1)
            new_user = User(
                id=uuid_module.uuid4(),
                email=email,
                hashed_password=get_password_hash(password),
                first_name=name_parts[0],
                last_name=name_parts[1] if len(name_parts) > 1 else "",
                full_name=full_name,
                phone=phone or "",
                role=UserRole.TENANT,
                status="active",
            )
            db.add(new_user)
            db.flush()
            user_id = new_user.id
            logger.info(f"[CREATE_TENANT] Created new user: {user_id}")

    # Determine property_id (keep as UUID, not string)
    property_id = None
    if tenant_in.property_id:
        try:
            property_id = uuid_module.UUID(str(tenant_in.property_id))
        except (ValueError, AttributeError):
            property_id = None
    if not property_id and unit:
        property_id = unit.property_id

    # Parse dates
    lease_start = None
    if tenant_in.lease_start:
        try:
            lease_start = datetime.fromisoformat(str(tenant_in.lease_start).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            lease_start = datetime.utcnow()
    else:
        lease_start = datetime.utcnow()

    lease_end = None
    if tenant_in.lease_end:
        try:
            lease_end = datetime.fromisoformat(str(tenant_in.lease_end).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    move_in_date = None
    if tenant_in.move_in_date:
        try:
            move_in_date = datetime.fromisoformat(str(tenant_in.move_in_date).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass
    if not move_in_date:
        move_in_date = lease_start

    # Create tenant record
    tenant = Tenant(
        id=uuid_module.uuid4(),
        user_id=user_id,
        unit_id=unit.id if unit else None,
        property_id=property_id,
        full_name=full_name,
        email=email,
        phone=phone or "",
        id_number=id_number or "",
        rent_amount=tenant_in.rent_amount or (unit.monthly_rent if unit else 0),
        deposit_amount=tenant_in.deposit_amount or 0,
        lease_start=lease_start,
        lease_end=lease_end,
        move_in_date=move_in_date,
        next_of_kin=tenant_in.emergency_contact_name or tenant_in.next_of_kin or "",
        nok_phone=tenant_in.emergency_contact_phone or tenant_in.nok_phone or "",
        status="active",
        balance_due=0.0,
    )

    db.add(tenant)

    # Mark unit as occupied
    if unit:
        unit.status = "occupied"
        logger.info(f"[CREATE_TENANT] Marking unit {unit.id} as occupied")

    db.commit()
    db.refresh(tenant)
    logger.info(f"[CREATE_TENANT] Tenant created: {tenant.id}, unit status: {unit.status if unit else 'N/A'}")

    # Fire tenant_onboarded workflow event
    try:
        from app.services.workflow_engine import WorkflowEngine
        from app.models.workflow import TriggerEvent
        engine = WorkflowEngine(db)
        engine.fire(
            TriggerEvent.TENANT_ONBOARDED,
            {
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.full_name,
                "tenant_email": tenant.email,
                "unit_id": str(tenant.unit_id) if tenant.unit_id else "",
                "unit_number": unit.unit_number if unit else "",
                "property_id": str(tenant.property_id) if tenant.property_id else "",
                "rent_amount": tenant.rent_amount,
                "lease_start": tenant.lease_start.strftime("%Y-%m-%d") if tenant.lease_start else "",
                "owner_id": str(current_user.id),
                "owner_email": current_user.email,
            },
            owner_id=current_user.id,
        )
    except Exception as wf_err:
        logger.warning(f"[WORKFLOW] tenant_onboarded event failed: {wf_err}")

    return {
        "success": True,
        "id": str(tenant.id),
        "full_name": tenant.full_name,
        "email": tenant.email,
        "phone": tenant.phone,
        "user_id": str(tenant.user_id) if tenant.user_id else None,
        "unit_id": str(tenant.unit_id) if tenant.unit_id else None,
        "property_id": str(tenant.property_id) if tenant.property_id else None,
        "rent_amount": tenant.rent_amount,
        "status": tenant.status,
        "balance_due": tenant.balance_due or 0,
        "lease_start": tenant.lease_start.isoformat() if tenant.lease_start else None,
        "lease_end": tenant.lease_end.isoformat() if tenant.lease_end else None,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
    }


@router.get("/")
def list_tenants(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all tenants with enriched data (unit and property info)"""
    if current_user.role == UserRole.OWNER:
        # Owner sees tenants in their properties
        owner_properties = db.query(Property).filter(Property.user_id == current_user.id).all()
        property_ids = [p.id for p in owner_properties]
        if property_ids:
            tenants = db.query(Tenant).filter(
                Tenant.property_id.in_(property_ids)
            ).offset(skip).limit(limit).all()
        else:
            tenants = []
        # Fallback: if no tenants found by property_id, try all tenants (owner might not have property_id set)
        if not tenants:
            tenants = db.query(Tenant).offset(skip).limit(limit).all()
    elif current_user.role in [UserRole.AGENT, UserRole.ADMIN, UserRole.CARETAKER]:
        tenants = db.query(Tenant).offset(skip).limit(limit).all()
    elif current_user.role == UserRole.TENANT:
        tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
        tenants = [tenant] if tenant else []
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Enrich with unit and property data
    tenant_list = []
    for t in tenants:
        if t is None:
            continue
        unit = db.query(Unit).filter(Unit.id == t.unit_id).first() if t.unit_id else None
        prop = db.query(Property).filter(Property.id == t.property_id).first() if t.property_id else None

        tenant_list.append({
            "id": str(t.id),
            "full_name": t.full_name,
            "email": t.email,
            "phone": t.phone,
            "user_id": str(t.user_id) if t.user_id else None,
            "unit_id": str(t.unit_id) if t.unit_id else None,
            "property_id": str(t.property_id) if t.property_id else None,
            "unit_number": unit.unit_number if unit else None,
            "property_name": prop.name if prop else None,
            "rent_amount": t.rent_amount,
            "deposit_amount": t.deposit_amount,
            "status": t.status or "active",
            "balance_due": t.balance_due or 0,
            "lease_start": t.lease_start.isoformat() if t.lease_start else None,
            "lease_end": t.lease_end.isoformat() if t.lease_end else None,
            "move_in_date": t.move_in_date.isoformat() if t.move_in_date else None,
            "move_out_date": t.move_out_date.isoformat() if t.move_out_date else None,
            "id_number": t.id_number,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        })

    return tenant_list


@router.get("/{tenant_id}")
def get_tenant(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get tenant details with unit and property info"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()

    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    # Authorization: Tenant can only see own, Owner/Agent/Caretaker can see all
    if current_user.role == UserRole.TENANT and current_user.id != tenant.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    unit = db.query(Unit).filter(Unit.id == tenant.unit_id).first() if tenant.unit_id else None
    prop = db.query(Property).filter(Property.id == tenant.property_id).first() if tenant.property_id else None

    return {
        "id": str(tenant.id),
        "full_name": tenant.full_name,
        "email": tenant.email,
        "phone": tenant.phone,
        "user_id": str(tenant.user_id) if tenant.user_id else None,
        "unit_id": str(tenant.unit_id) if tenant.unit_id else None,
        "property_id": str(tenant.property_id) if tenant.property_id else None,
        "unit_number": unit.unit_number if unit else None,
        "property_name": prop.name if prop else None,
        "rent_amount": tenant.rent_amount,
        "deposit_amount": tenant.deposit_amount,
        "status": tenant.status or "active",
        "balance_due": tenant.balance_due or 0,
        "lease_start": tenant.lease_start.isoformat() if tenant.lease_start else None,
        "lease_end": tenant.lease_end.isoformat() if tenant.lease_end else None,
        "move_in_date": tenant.move_in_date.isoformat() if tenant.move_in_date else None,
        "move_out_date": tenant.move_out_date.isoformat() if tenant.move_out_date else None,
        "id_number": tenant.id_number,
        "next_of_kin": tenant.next_of_kin,
        "nok_phone": tenant.nok_phone,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
        "updated_at": tenant.updated_at.isoformat() if tenant.updated_at else None,
    }


@router.put("/{tenant_id}")
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

    return {
        "success": True,
        "id": str(tenant.id),
        "full_name": tenant.full_name,
        "email": tenant.email,
        "phone": tenant.phone,
        "status": tenant.status,
        "rent_amount": tenant.rent_amount,
    }


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

    # Capture context before deletion
    _vacated_context = {
        "tenant_id": str(tenant.id),
        "tenant_name": tenant.full_name,
        "unit_id": str(tenant.unit_id) if tenant.unit_id else "",
        "unit_number": unit.unit_number if unit else "",
        "property_id": str(tenant.property_id) if tenant.property_id else "",
        "owner_id": str(current_user.id),
        "owner_email": current_user.email,
    }
    _owner_id = current_user.id

    db.delete(tenant)
    db.commit()

    # Fire unit_vacated workflow event
    try:
        from app.services.workflow_engine import WorkflowEngine
        from app.models.workflow import TriggerEvent
        engine = WorkflowEngine(db)
        engine.fire(TriggerEvent.UNIT_VACATED, _vacated_context, owner_id=_owner_id)
    except Exception as wf_err:
        logger.warning(f"[WORKFLOW] unit_vacated event failed: {wf_err}")


# ==================== TENANT PAYMENTS ====================

@router.get("/{tenant_id}/payments")
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