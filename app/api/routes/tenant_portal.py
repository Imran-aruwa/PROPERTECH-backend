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

    # Get recent payments (Payment uses user_id, not tenant_id)
    recent_payments = db.query(Payment)\
        .filter(Payment.user_id == tenant.user_id)\
        .order_by(desc(Payment.created_at))\
        .limit(5)\
        .all()

    payment_list = []
    for p in recent_payments:
        month_str = p.paid_at.strftime("%b %Y") if p.paid_at else "Pending"
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


@router.get("/documents/{document_id}/download")
def download_tenant_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get download URL for a document"""
    if current_user.role != UserRole.TENANT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant profile not found")

    # Map document IDs to URLs
    doc_map = {
        "lease-agreement": tenant.lease_agreement_url,
        "id-front": tenant.id_front_url,
        "id-back": tenant.id_back_url
    }

    url = doc_map.get(document_id)
    if not url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return {
        "success": True,
        "download_url": url
    }


# ==================== PAYMENTS ====================

@router.get("/payments")
def get_tenant_payments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get payment history for tenant"""
    if current_user.role != UserRole.TENANT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant profile not found")

    payments = db.query(Payment)\
        .filter(Payment.user_id == tenant.user_id)\
        .order_by(desc(Payment.created_at))\
        .all()

    # Calculate totals
    total_paid = sum(p.amount for p in payments if p.status == PaymentStatus.COMPLETED)
    total_pending = sum(p.amount for p in payments if p.status == PaymentStatus.PENDING)

    payment_list = []
    for p in payments:
        payment_list.append({
            "id": str(p.id),
            "type": p.plan_id or "rent",
            "amount": float(p.amount),
            "status": p.status.value,
            "payment_date": p.paid_at.isoformat() if p.paid_at else None,
            "due_date": p.created_at.isoformat() if p.created_at else None,
            "reference": p.reference
        })

    return {
        "success": True,
        "total_paid": float(total_paid),
        "total_pending": float(total_pending),
        "payments": payment_list
    }


# ==================== LEASE ====================

@router.get("/lease")
def get_tenant_lease(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get tenant lease information — prefers a real Lease record, falls back to tenant fields."""
    if current_user.role != UserRole.TENANT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    tenant = db.query(Tenant).filter(Tenant.user_id == current_user.id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant profile not found")

    unit = db.query(Unit).filter(Unit.id == tenant.unit_id).first()
    prop = db.query(Property).filter(Property.id == unit.property_id).first() if unit else None

    # Try to find a real Lease record for this tenant
    lease_data = None
    try:
        from app.models.lease import Lease, LeaseStatus
        # Find the most recent non-terminated lease linked to this tenant
        real_lease = (
            db.query(Lease)
            .filter(
                Lease.tenant_id == tenant.id,
                Lease.status.notin_([LeaseStatus.TERMINATED]),
            )
            .order_by(Lease.created_at.desc())
            .first()
        )
        if real_lease:
            lease_data = {
                "id": str(real_lease.id),
                "tenant_name": real_lease.tenant_name or tenant.full_name,
                "unit_number": unit.unit_number if unit else None,
                "property_name": prop.name if prop else None,
                "property_address": prop.address if prop else None,
                "rent_amount": float(real_lease.rent_amount),
                "deposit_amount": float(real_lease.deposit_amount),
                "lease_start": real_lease.start_date.isoformat() if real_lease.start_date else None,
                "lease_end": real_lease.end_date.isoformat() if real_lease.end_date else None,
                "lease_duration_months": tenant.lease_duration_months,
                "status": real_lease.status.value if hasattr(real_lease.status, "value") else str(real_lease.status),
                "move_in_date": tenant.move_in_date.isoformat() if tenant.move_in_date else None,
                "document_url": real_lease.pdf_url or tenant.lease_agreement_url,
                "payment_cycle": real_lease.payment_cycle.value if hasattr(real_lease.payment_cycle, "value") else str(real_lease.payment_cycle),
                "signed_at": real_lease.signed_at.isoformat() if real_lease.signed_at else None,
            }
    except Exception:
        pass  # Fall through to legacy response

    if lease_data is None:
        lease_data = {
            "tenant_name": tenant.full_name,
            "unit_number": unit.unit_number if unit else None,
            "property_name": prop.name if prop else None,
            "property_address": prop.address if prop else None,
            "rent_amount": float(unit.monthly_rent) if unit else 0,
            "deposit_amount": float(tenant.deposit_amount) if tenant.deposit_amount else 0,
            "lease_start": tenant.lease_start.isoformat() if tenant.lease_start else None,
            "lease_end": tenant.lease_end.isoformat() if tenant.lease_end else None,
            "lease_duration_months": tenant.lease_duration_months,
            "status": tenant.status,
            "move_in_date": tenant.move_in_date.isoformat() if tenant.move_in_date else None,
            "document_url": tenant.lease_agreement_url,
        }

    return {"success": True, "lease": lease_data}
