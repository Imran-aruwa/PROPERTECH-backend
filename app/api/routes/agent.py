"""
Agent Portal Routes - Complete Implementation
Property management, commission tracking, earnings analytics, meter readings
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
from app.models.meter import MeterReading

router = APIRouter(tags=["agent"])


@router.get("/dashboard")
def get_agent_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get agent dashboard with properties and earnings"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Get agent's properties
    properties = db.query(Property).all()

    if not properties:
        return {"success": True, "properties": 0, "metrics": {}}

    property_ids = [p.id for p in properties]

    # Calculate metrics
    total_units = db.query(Unit).filter(Unit.property_id.in_(property_ids)).count()
    occupied_units = db.query(Unit).filter(
        and_(Unit.property_id.in_(property_ids), Unit.is_occupied == True)
    ).count()

    today = datetime.utcnow().date()
    current_month_start = datetime(today.year, today.month, 1).date()
    current_month_end = datetime(today.year, today.month + 1 if today.month < 12 else 1, 1).date() - timedelta(days=1)

    collected_rent = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.RENT,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= current_month_start,
                Payment.payment_date <= current_month_end
            )
        ).scalar() or 0

    # Commission: 5% of collections
    commission = collected_rent * 0.05

    # Count tenants
    total_tenants = db.query(Tenant).filter(Tenant.status == "active").count()

    # Pending amount
    pending_amount = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.RENT,
                Payment.status == PaymentStatus.PENDING
            )
        ).scalar() or 0

    # Recent activities
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

    return {
        "success": True,
        "total_properties": len(properties),
        "total_tenants": total_tenants,
        "rent_collected": float(collected_rent),
        "pending_amount": float(pending_amount),
        "recent_activities": recent_activities
    }


@router.get("/earnings")
def get_agent_earnings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    months: int = 12
):
    """Get agent earnings history"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    properties = db.query(Property).all()
    property_ids = [p.id for p in properties]

    earnings_data = []
    today = datetime.utcnow().date()

    for i in range(months):
        month_date = today - timedelta(days=30*i)
        month_start = datetime(month_date.year, month_date.month, 1).date()
        month_end = datetime(month_date.year, month_date.month + 1 if month_date.month < 12 else 1, 1).date() - timedelta(days=1)

        # Calculate earnings for this month
        rent_collected = db.query(func.sum(Payment.amount))\
            .filter(
                and_(
                    Payment.payment_type == PaymentType.RENT,
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.payment_date >= month_start,
                    Payment.payment_date <= month_end
                )
            ).scalar() or 0

        water_collected = db.query(func.sum(Payment.amount))\
            .filter(
                and_(
                    Payment.payment_type == PaymentType.WATER,
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.payment_date >= month_start,
                    Payment.payment_date <= month_end
                )
            ).scalar() or 0

        electricity_collected = db.query(func.sum(Payment.amount))\
            .filter(
                and_(
                    Payment.payment_type == PaymentType.ELECTRICITY,
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.payment_date >= month_start,
                    Payment.payment_date <= month_end
                )
            ).scalar() or 0

        commission = (rent_collected * 0.05) + (water_collected * 0.02) + (electricity_collected * 0.02)

        earnings_data.append({
            "month": f"{month_date.year}-{month_date.month:02d}",
            "rent_commission": float(rent_collected * 0.05),
            "water_commission": float(water_collected * 0.02),
            "electricity_commission": float(electricity_collected * 0.02),
            "total_commission": float(commission)
        })

    return {
        "success": True,
        "agent_id": str(current_user.id),
        "earnings": earnings_data
    }


@router.get("/properties")
def get_agent_properties(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get properties managed by agent"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    properties = db.query(Property).all()

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
            "total_units": units,
            "occupied_units": occupied,
            "occupancy_rate": round((occupied / units * 100) if units > 0 else 0, 2)
        })

    return {
        "success": True,
        "total_properties": len(properties),
        "properties": property_list
    }


@router.get("/tenants")
def get_agent_tenants(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all tenants managed by agent"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    tenants = db.query(Tenant).filter(Tenant.status == "active").all()

    tenant_list = []
    for tenant in tenants:
        unit = db.query(Unit).filter(Unit.id == tenant.unit_id).first()
        prop = db.query(Property).filter(Property.id == unit.property_id).first() if unit else None

        today = datetime.utcnow().date()
        current_month_start = datetime(today.year, today.month, 1).date()
        current_month_end = datetime(today.year, today.month + 1 if today.month < 12 else 1, 1).date() - timedelta(days=1)

        rent_payment = db.query(Payment).filter(
            and_(
                Payment.tenant_id == tenant.id,
                Payment.payment_type == PaymentType.RENT,
                Payment.due_date >= current_month_start,
                Payment.due_date <= current_month_end
            )
        ).first()

        tenant_list.append({
            "id": str(tenant.id),
            "name": tenant.full_name,
            "unit": unit.unit_number if unit else None,
            "property": prop.name if prop else None,
            "phone": tenant.phone,
            "rent_status": rent_payment.status.value if rent_payment else "pending",
            "rent_amount": float(unit.monthly_rent) if unit else 0
        })

    return {
        "success": True,
        "tenants": tenant_list
    }


@router.get("/rent-tracking")
def get_agent_rent_tracking(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get rent tracking data for agent"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    properties = db.query(Property).all()
    property_ids = [p.id for p in properties]

    today = datetime.utcnow().date()
    current_month_start = datetime(today.year, today.month, 1).date()
    current_month_end = datetime(today.year, today.month + 1 if today.month < 12 else 1, 1).date() - timedelta(days=1)

    # Total expected rent
    total_expected = db.query(func.sum(Unit.monthly_rent))\
        .filter(and_(Unit.property_id.in_(property_ids), Unit.is_occupied == True))\
        .scalar() or 0

    # Total collected
    total_collected = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.payment_type == PaymentType.RENT,
                Payment.status == PaymentStatus.COMPLETED,
                Payment.payment_date >= current_month_start,
                Payment.payment_date <= current_month_end
            )
        ).scalar() or 0

    pending = float(total_expected) - float(total_collected)
    collection_rate = (float(total_collected) / float(total_expected) * 100) if total_expected > 0 else 0

    # Per-property breakdown
    property_breakdown = []
    for prop in properties:
        prop_expected = db.query(func.sum(Unit.monthly_rent))\
            .filter(and_(Unit.property_id == prop.id, Unit.is_occupied == True))\
            .scalar() or 0

        prop_collected = db.query(func.sum(Payment.amount))\
            .filter(
                and_(
                    Payment.payment_type == PaymentType.RENT,
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.payment_date >= current_month_start,
                    Payment.payment_date <= current_month_end
                )
            ).scalar() or 0

        prop_pending = float(prop_expected) - float(prop_collected)
        prop_rate = (float(prop_collected) / float(prop_expected) * 100) if prop_expected > 0 else 0

        property_breakdown.append({
            "id": str(prop.id),
            "name": prop.name,
            "expected": float(prop_expected),
            "collected": float(prop_collected),
            "pending": prop_pending,
            "rate": round(prop_rate, 2)
        })

    return {
        "success": True,
        "total_expected": float(total_expected),
        "total_collected": float(total_collected),
        "pending": pending,
        "collection_rate": round(collection_rate, 2),
        "properties": property_breakdown
    }


@router.get("/rent-collection")
def get_agent_rent_collection(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get detailed rent collection status"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    today = datetime.utcnow().date()
    current_month_start = datetime(today.year, today.month, 1).date()
    current_month_end = datetime(today.year, today.month + 1 if today.month < 12 else 1, 1).date() - timedelta(days=1)

    # Get all rent payments for current month
    payments = db.query(Payment)\
        .filter(
            and_(
                Payment.payment_type == PaymentType.RENT,
                Payment.due_date >= current_month_start,
                Payment.due_date <= current_month_end
            )
        ).all()

    total_collected = sum(p.amount for p in payments if p.status == PaymentStatus.COMPLETED)
    pending_amount = sum(p.amount for p in payments if p.status == PaymentStatus.PENDING)
    tenants_paid = len([p for p in payments if p.status == PaymentStatus.COMPLETED])

    payment_list = []
    for payment in payments:
        tenant = db.query(Tenant).filter(Tenant.id == payment.tenant_id).first()
        unit = db.query(Unit).filter(Unit.id == tenant.unit_id).first() if tenant else None

        days_overdue = 0
        if payment.status == PaymentStatus.PENDING and payment.due_date:
            days_overdue = max(0, (today - payment.due_date).days)

        payment_list.append({
            "id": str(payment.id),
            "tenant": tenant.full_name if tenant else "Unknown",
            "unit": unit.unit_number if unit else "N/A",
            "amount": float(payment.amount),
            "due_date": payment.due_date.isoformat() if payment.due_date else None,
            "status": payment.status.value,
            "days_overdue": days_overdue
        })

    return {
        "success": True,
        "total_collected": float(total_collected),
        "pending_amount": float(pending_amount),
        "tenants_paid": tenants_paid,
        "payments": payment_list
    }


@router.get("/meter-readings/{property_id}")
def get_meter_readings(
    property_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get meter readings for property"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    readings = db.query(MeterReading)\
        .join(Unit, MeterReading.unit_id == Unit.id)\
        .filter(Unit.property_id == property_id)\
        .order_by(desc(MeterReading.reading_date))\
        .all()

    return {
        "success": True,
        "property_id": property_id,
        "readings_count": len(readings),
        "readings": [
            {
                "unit_id": str(r.unit_id),
                "water": r.water_reading,
                "electricity": r.electricity_reading,
                "date": r.reading_date.isoformat() if r.reading_date else None
            }
            for r in readings
        ]
    }
