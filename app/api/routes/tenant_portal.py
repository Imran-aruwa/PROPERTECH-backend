"""
Tenant Portal Routes - Tenant Self-Service
Dashboard, maintenance requests, documents, and payments for tenants
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
from typing import Optional
from datetime import datetime, timedelta
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserRole
from app.models.tenant import Tenant
from app.models.property import Property, Unit
from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.maintenance import MaintenanceRequest, MaintenanceStatus, MaintenancePriority
from app.models.meter import MeterReading

router = APIRouter(tags=["tenant-portal"])


# ==================== SCHEMAS ====================

class MaintenanceRequestCreate(BaseModel):
    issue: str
    description: str
    priority: str = "medium"


# ==================== TENANT DASHBOARD ====================

@router.get("/dashboard")
def get_tenant_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get tenant dashboard with all key information"""
    if current_user.role != UserRole.TENANT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Find tenant record
    tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant profile not found")

    # Get unit and property info
    unit = db.query(Unit).filter(Unit.id == tenant.unit_id).first()
    prop = db.query(Property).filter(Property.id == unit.property_id).first() if unit else None

    today = datetime.utcnow().date()
    current_month_end = datetime(today.year, today.month + 1 if today.month < 12 else 1, 1).date() - timedelta(days=1)

    # Get open maintenance requests
    open_requests = db.query(MaintenanceRequest).filter(
        and_(
            MaintenanceRequest.tenant_id == tenant.id,
            MaintenanceRequest.status.in_([MaintenanceStatus.PENDING, MaintenanceStatus.IN_PROGRESS])
        )
    ).count()

    # Format lease end
    lease_end_formatted = None
    if tenant.lease_end:
        lease_end_formatted = tenant.lease_end.strftime("%b %Y")

    # Get recent payments
    recent_payments = db.query(Payment)\
        .filter(Payment.tenant_id == tenant.id)\
        .order_by(desc(Payment.created_at))\
        .limit(5)\
        .all()

    payment_list = []
    for p in recent_payments:
        month_str = p.payment_date.strftime("%b %Y") if p.payment_date else "Pending"
        payment_list.append({
            "id": str(p.id),
            "month": month_str,
            "amount": float(p.amount),
            "status": p.status.value
        })

    # Get maintenance requests
    maintenance_requests = db.query(MaintenanceRequest)\
        .filter(MaintenanceRequest.tenant_id == tenant.id)\
        .order_by(desc(MaintenanceRequest.created_at))\
        .limit(5)\
        .all()

    maintenance_list = [
        {
            "id": str(m.id),
            "title": m.title,
            "status": m.status.value,
            "priority": m.priority.value
        }
        for m in maintenance_requests
    ]

    return {
        "success": True,
        "next_payment_due": current_month_end.strftime("%b %d, %Y"),
        "rent_amount": float(unit.monthly_rent) if unit else 0,
        "open_requests": open_requests,
        "lease_end": lease_end_formatted,
        "unit_number": unit.unit_number if unit else None,
        "property_name": prop.name if prop else None,
        "recent_payments": payment_list,
        "maintenance_requests": maintenance_list
    }


# ==================== MAINTENANCE REQUESTS ====================

@router.get("/maintenance")
def get_tenant_maintenance_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all maintenance requests for the tenant"""
    if current_user.role != UserRole.TENANT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant profile not found")

    requests = db.query(MaintenanceRequest)\
        .filter(MaintenanceRequest.tenant_id == tenant.id)\
        .order_by(desc(MaintenanceRequest.created_at))\
        .all()

    request_list = [
        {
            "id": str(r.id),
            "issue": r.title,
            "description": r.description,
            "priority": r.priority.value,
            "status": r.status.value,
            "date": r.created_at.isoformat() if r.created_at else None
        }
        for r in requests
    ]

    return {
        "success": True,
        "requests": request_list
    }


@router.post("/maintenance")
def create_tenant_maintenance_request(
    request_data: MaintenanceRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new maintenance request"""
    if current_user.role != UserRole.TENANT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant profile not found")

    # Map priority string to enum
    priority_map = {
        "low": MaintenancePriority.LOW,
        "medium": MaintenancePriority.MEDIUM,
        "high": MaintenancePriority.HIGH
    }
    priority = priority_map.get(request_data.priority.lower(), MaintenancePriority.MEDIUM)

    maintenance = MaintenanceRequest(
        tenant_id=tenant.id,
        unit_id=tenant.unit_id,
        title=request_data.issue,
        description=request_data.description,
        priority=priority,
        status=MaintenanceStatus.PENDING
    )

    db.add(maintenance)
    db.commit()
    db.refresh(maintenance)

    return {
        "success": True,
        "message": "Maintenance request submitted successfully",
        "request_id": str(maintenance.id)
    }


# ==================== DOCUMENTS ====================

@router.get("/documents")
def get_tenant_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get tenant documents (lease agreement, ID copies, etc.)"""
    if current_user.role != UserRole.TENANT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant profile not found")

    documents = []

    # Add lease agreement if available
    if tenant.lease_agreement_url:
        documents.append({
            "id": "lease-agreement",
            "name": "Lease Agreement",
            "type": "pdf",
            "url": tenant.lease_agreement_url,
            "uploaded_at": tenant.created_at.isoformat() if tenant.created_at else None
        })

    # Add ID documents if available
    if tenant.id_front_url:
        documents.append({
            "id": "id-front",
            "name": "ID Document (Front)",
            "type": "image",
            "url": tenant.id_front_url,
            "uploaded_at": tenant.created_at.isoformat() if tenant.created_at else None
        })

    if tenant.id_back_url:
        documents.append({
            "id": "id-back",
            "name": "ID Document (Back)",
            "type": "image",
            "url": tenant.id_back_url,
            "uploaded_at": tenant.created_at.isoformat() if tenant.created_at else None
        })

    return {
        "success": True,
        "documents": documents
    }
