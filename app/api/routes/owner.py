"""
Owner Portal Routes - Complete Implementation
Financial analytics, staff management, property oversight, commission tracking
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func
from typing import List, Optional
from datetime import datetime, timedelta

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserRole
from app.models.property import Property, Unit
from app.models.tenant import Tenant
from app.models.payment import Payment, PaymentStatus, PaymentType
from app.models.maintenance import MaintenanceRequest, MaintenanceStatus
from app.models.meter import MeterReading
from app.models.staff import Staff

router = APIRouter(tags=["owner"])


@router.get("/dashboard")
def get_owner_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get owner dashboard with all key metrics"""
    if current_user.role != UserRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    properties = db.query(Property).filter(Property.owner_id == current_user.id).all()

    if not properties:
        return {
            "success": True,
            "properties": 0,
            "units": 0,
            "metrics": {}
        }

    property_ids = [p.id for p in properties]

    # Unit metrics
    total_units = db.query(Unit).filter(Unit.property_id.in_(property_ids)).count()
    occupied_units = db.query(Unit).filter(
        and_(Unit.property_id.in_(property_ids), Unit.is_occupied == True)
    ).count()
    occupancy_rate = (occupied_units / total_units * 100) if total_units > 0 else 0

    # Revenue metrics
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

    water_collected = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.WATER,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= current_month_start,
                Payment.payment_date <= current_month_end
            )
        ).scalar() or 0

    electricity_collected = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.ELECTRICITY,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= current_month_start,
                Payment.payment_date <= current_month_end
            )
        ).scalar() or 0

    total_revenue = float(collected_rent + water_collected + electricity_collected)
    collection_rate = (collected_rent / expected_rent * 100) if expected_rent > 0 else 0

    # Staff metrics
    total_staff = db.query(Staff).count()

    # Maintenance metrics
    total_maintenance = db.query(MaintenanceRequest).count()
    pending_maintenance = db.query(MaintenanceRequest)\
        .filter(MaintenanceRequest.status == MaintenanceStatus.PENDING).count()

    # Count tenants
    total_tenants = db.query(Tenant).filter(Tenant.status == "active").count()

    # Pending payments
    pending_payments = db.query(func.sum(Payment.amount))\
        .filter(Payment.status == PaymentStatus.PENDING)\
        .scalar() or 0

    # Recent activities (last 10 payments or maintenance)
    recent_activities = []

    recent_payments = db.query(Payment)\
        .order_by(desc(Payment.created_at))\
        .limit(5)\
        .all()

    for p in recent_payments:
        recent_activities.append({
            "type": "payment",
            "description": f"Payment of KES {p.amount:,.0f} - {p.status.value}",
            "timestamp": p.created_at.isoformat() if p.created_at else None
        })

    recent_maintenance = db.query(MaintenanceRequest)\
        .order_by(desc(MaintenanceRequest.created_at))\
        .limit(5)\
        .all()

    for m in recent_maintenance:
        recent_activities.append({
            "type": "maintenance",
            "description": f"Maintenance: {m.title} - {m.status.value}",
            "timestamp": m.created_at.isoformat() if m.created_at else None
        })

    # Sort by timestamp
    recent_activities.sort(key=lambda x: x["timestamp"] or "", reverse=True)

    return {
        "success": True,
        "total_properties": len(properties),
        "total_units": total_units,
        "total_tenants": total_tenants,
        "occupancy_rate": round(occupancy_rate, 2),
        "monthly_revenue": total_revenue,
        "pending_payments": float(pending_payments),
        "maintenance_requests": pending_maintenance,
        "recent_activities": recent_activities[:10]
    }


@router.get("/property/{property_id}")
def get_owner_property_detail(
    property_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get detailed property information with units and revenue trend"""
    if current_user.role != UserRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    # Get units with tenant and payment info
    units = db.query(Unit).filter(Unit.property_id == property_id).all()

    today = datetime.utcnow().date()
    current_month_start = datetime(today.year, today.month, 1).date()
    current_month_end = datetime(today.year, today.month + 1 if today.month < 12 else 1, 1).date() - timedelta(days=1)

    # Calculate revenue metrics
    expected_rent = db.query(func.sum(Unit.monthly_rent))\
        .filter(and_(Unit.property_id == property_id, Unit.is_occupied == True))\
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

    pending_payments = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.RENT,
                Payment.status == PaymentStatus.PENDING
            )
        ).scalar() or 0

    overdue_payments = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.RENT,
                Payment.status == PaymentStatus.PENDING,
                Payment.due_date < today
            )
        ).scalar() or 0

    water_collected = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.WATER,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= current_month_start,
                Payment.payment_date <= current_month_end
            )
        ).scalar() or 0

    electricity_collected = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.ELECTRICITY,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= current_month_start,
                Payment.payment_date <= current_month_end
            )
        ).scalar() or 0

    total_revenue = float(collected_rent + water_collected + electricity_collected)

    # Get previous month revenue
    prev_month_start = datetime(today.year, today.month - 1 if today.month > 1 else 12, 1).date()
    prev_month_end = current_month_start - timedelta(days=1)

    previous_revenue = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= prev_month_start,
                Payment.payment_date <= prev_month_end
            )
        ).scalar() or 0

    # Build unit list with tenant info
    unit_list = []
    for unit in units:
        tenant = db.query(Tenant).filter(
            and_(Tenant.unit_id == unit.id, Tenant.status == "active")
        ).first()

        # Get rent payment status
        rent_payment = db.query(Payment).filter(
            and_(
                Payment.tenant_id == tenant.id if tenant else None,
                Payment.payment_type == PaymentType.RENT,
                Payment.due_date >= current_month_start,
                Payment.due_date <= current_month_end
            )
        ).first() if tenant else None

        water_payment = db.query(Payment).filter(
            and_(
                Payment.tenant_id == tenant.id if tenant else None,
                Payment.payment_type == PaymentType.WATER,
                Payment.due_date >= current_month_start,
                Payment.due_date <= current_month_end
            )
        ).first() if tenant else None

        electricity_payment = db.query(Payment).filter(
            and_(
                Payment.tenant_id == tenant.id if tenant else None,
                Payment.payment_type == PaymentType.ELECTRICITY,
                Payment.due_date >= current_month_start,
                Payment.due_date <= current_month_end
            )
        ).first() if tenant else None

        days_overdue = 0
        if rent_payment and rent_payment.status == PaymentStatus.PENDING and rent_payment.due_date:
            days_overdue = max(0, (today - rent_payment.due_date).days)

        unit_list.append({
            "id": str(unit.id),
            "unit_number": unit.unit_number,
            "tenant_name": tenant.full_name if tenant else None,
            "rent_status": rent_payment.status.value if rent_payment else "no_tenant",
            "water_status": water_payment.status.value if water_payment else "pending",
            "electricity_status": electricity_payment.status.value if electricity_payment else "pending",
            "days_overdue": days_overdue
        })

    # Generate revenue trend (last 12 months)
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    revenue_trend = []

    for i in range(11, -1, -1):
        month_date = today - timedelta(days=30*i)
        month_start = datetime(month_date.year, month_date.month, 1).date()
        if month_date.month == 12:
            month_end = datetime(month_date.year + 1, 1, 1).date() - timedelta(days=1)
        else:
            month_end = datetime(month_date.year, month_date.month + 1, 1).date() - timedelta(days=1)

        month_revenue = db.query(func.sum(Payment.amount))\
            .filter(
                and_(
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.payment_date >= month_start,
                    Payment.payment_date <= month_end
                )
            ).scalar() or 0

        revenue_trend.append({
            "name": month_names[month_date.month - 1],
            "revenue": float(month_revenue)
        })

    # Get caretaker info
    caretaker = db.query(User).filter(
        and_(User.role == UserRole.CARETAKER)
    ).first()

    return {
        "success": True,
        "property": {
            "id": str(prop.id),
            "name": prop.name,
            "location": prop.address or "",
            "caretaker": caretaker.full_name if caretaker else None,
            "expected_rent": float(expected_rent),
            "collected_rent": float(collected_rent),
            "pending": float(pending_payments),
            "overdue": float(overdue_payments),
            "water_collected": float(water_collected),
            "electricity_collected": float(electricity_collected),
            "total_revenue": total_revenue,
            "previous_revenue": float(previous_revenue)
        },
        "units": unit_list,
        "revenue_trend": revenue_trend
    }


@router.get("/analytics")
@router.get("/financial-analytics")
def get_financial_analytics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    months: int = 12
):
    """Get comprehensive financial analytics"""
    if current_user.role != UserRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    properties = db.query(Property).filter(Property.owner_id == current_user.id).all()
    property_ids = [p.id for p in properties]

    # Generate monthly data
    monthly_data = []
    today = datetime.utcnow().date()

    for i in range(months):
        month_date = today - timedelta(days=30*i)
        month_start = datetime(month_date.year, month_date.month, 1).date()
        if month_date.month == 12:
            month_end = datetime(month_date.year + 1, 1, 1).date() - timedelta(days=1)
        else:
            month_end = datetime(month_date.year, month_date.month + 1, 1).date() - timedelta(days=1)

        # Calculate metrics for this month
        expected = db.query(func.sum(Unit.monthly_rent))\
            .filter(and_(Unit.property_id.in_(property_ids), Unit.is_occupied == True))\
            .scalar() or 0

        collected = db.query(func.sum(Payment.amount))\
            .filter(
                and_(
                    Payment.payment_type == PaymentType.RENT,
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.payment_date >= month_start,
                    Payment.payment_date <= month_end
                )
            ).scalar() or 0

        monthly_data.append({
            "month": f"{month_date.year}-{month_date.month:02d}",
            "expected_rent": float(expected),
            "collected_rent": float(collected),
            "collection_rate": round((collected / expected * 100) if expected > 0 else 0, 2)
        })

    return {
        "success": True,
        "owner_id": str(current_user.id),
        "properties": len(properties),
        "monthly_analytics": monthly_data
    }


@router.get("/properties")
def get_owner_properties(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all properties owned by current user"""
    if current_user.role != UserRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    properties = db.query(Property).filter(Property.owner_id == current_user.id).all()

    property_list = []
    for prop in properties:
        units = db.query(Unit).filter(Unit.property_id == prop.id).count()
        occupied = db.query(Unit).filter(
            and_(Unit.property_id == prop.id, Unit.is_occupied == True)
        ).count()

        property_list.append({
            "id": str(prop.id),
            "name": prop.name,
            "address": prop.address,
            "city": prop.city,
            "total_units": units,
            "occupied_units": occupied,
            "occupancy_rate": round((occupied / units * 100) if units > 0 else 0, 2)
        })

    return {
        "success": True,
        "total_properties": len(properties),
        "properties": property_list
    }


@router.get("/staff")
def get_all_staff(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all staff across all properties"""
    if current_user.role != UserRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    staff = db.query(Staff).all()

    staff_list = [
        {
            "id": str(s.id),
            "name": s.user.full_name if s.user else "Unknown",
            "email": s.user.email if s.user else "N/A",
            "position": s.position,
            "department": s.department,
            "salary": float(s.salary) if s.salary else 0,
            "start_date": s.start_date.isoformat() if s.start_date else None
        }
        for s in staff
    ]

    return {
        "success": True,
        "total_staff": len(staff),
        "staff": staff_list
    }


@router.get("/agent-commissions")
def get_agent_commissions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get agent commission tracking and payout history"""
    if current_user.role != UserRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    today = datetime.utcnow().date()
    current_month_start = datetime(today.year, today.month, 1).date()
    current_month_end = datetime(today.year, today.month + 1 if today.month < 12 else 1, 1).date() - timedelta(days=1)

    # Calculate commissions (5% rent, 2% water, 2% electricity)
    rent_commissions = db.query(func.sum(Payment.amount * 0.05))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.RENT,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= current_month_start,
                Payment.payment_date <= current_month_end
            )
        ).scalar() or 0

    water_commissions = db.query(func.sum(Payment.amount * 0.02))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.WATER,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= current_month_start,
                Payment.payment_date <= current_month_end
            )
        ).scalar() or 0

    electricity_commissions = db.query(func.sum(Payment.amount * 0.02))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.ELECTRICITY,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= current_month_start,
                Payment.payment_date <= current_month_end
            )
        ).scalar() or 0

    total_commissions = rent_commissions + water_commissions + electricity_commissions

    return {
        "success": True,
        "period": f"{current_month_start} to {current_month_end}",
        "commissions": {
            "rent_commission": float(rent_commissions),
            "water_commission": float(water_commissions),
            "electricity_commission": float(electricity_commissions),
            "total_commission": float(total_commissions)
        },
        "commission_structure": {
            "rent": "5%",
            "water": "2%",
            "electricity": "2%"
        }
    }


@router.get("/reports/monthly")
def generate_monthly_report(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    month: Optional[int] = None,
    year: Optional[int] = None
):
    """Generate comprehensive monthly report"""
    if current_user.role != UserRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if not month:
        month = datetime.utcnow().month
    if not year:
        year = datetime.utcnow().year

    month_start = datetime(year, month, 1).date()
    month_end = datetime(year, month + 1 if month < 12 else 1, 1).date() - timedelta(days=1)

    properties = db.query(Property).filter(Property.owner_id == current_user.id).all()
    property_ids = [p.id for p in properties]

    report = {
        "success": True,
        "owner": current_user.full_name,
        "period": f"{month_start} to {month_end}",
        "generated_at": datetime.utcnow().isoformat()
    }

    # Add financial summary
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

    report["financial_summary"] = {
        "expected_rent": float(expected_rent),
        "collected_rent": float(collected_rent),
        "collection_rate": round((collected_rent / expected_rent * 100) if expected_rent > 0 else 0, 2)
    }

    return report
