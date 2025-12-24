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

    return {
        "success": True,
        "properties": len(properties),
        "timestamp": datetime.utcnow().isoformat(),
        "metrics": {
            "units": {
                "total": total_units,
                "occupied": occupied_units,
                "occupancy_rate": round(occupancy_rate, 2)
            },
            "revenue": {
                "expected_rent": float(expected_rent),
                "collected_rent": float(collected_rent),
                "water_bills": float(water_collected),
                "electricity_bills": float(electricity_collected),
                "total_revenue": total_revenue,
                "collection_rate": round(collection_rate, 2)
            },
            "staff": total_staff,
            "maintenance": {
                "total": total_maintenance,
                "pending": pending_maintenance
            }
        }
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
