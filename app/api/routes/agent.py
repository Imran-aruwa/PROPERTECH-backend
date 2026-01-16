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
from app.models.lead import Lead, LeadStatus
from app.models.viewing import Viewing, ViewingStatus
from pydantic import BaseModel
import uuid as uuid_module

router = APIRouter(tags=["agent"])


# Pydantic schema for property creation by agent
class AgentPropertyCreate(BaseModel):
    name: str
    address: str
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = "Kenya"
    property_type: Optional[str] = "residential"
    description: Optional[str] = None
    image_url: Optional[str] = None
    owner_id: Optional[str] = None  # Owner user ID - links property to owner's dashboard
    # Unit generation fields
    total_units: Optional[int] = 0
    unit_prefix: Optional[str] = "Unit"
    default_bedrooms: Optional[int] = 1
    default_bathrooms: Optional[float] = 1.0
    default_toilets: Optional[int] = 0
    default_rent: Optional[float] = None
    default_square_feet: Optional[int] = None
    default_has_master_bedroom: Optional[bool] = False
    default_has_servant_quarters: Optional[bool] = False
    default_sq_bathrooms: Optional[int] = 0
    default_unit_description: Optional[str] = None


# Pydantic schema for lead creation
class LeadCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: str
    property_interest: Optional[str] = None
    budget: Optional[float] = None
    source: Optional[str] = None
    notes: Optional[str] = None


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
        and_(Unit.property_id.in_(property_ids), Unit.status == "occupied")
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


@router.get("/activities")
def get_agent_activities(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 20
):
    """Get recent agent activities"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    activities = []

    # Recent payments
    recent_payments = db.query(Payment)\
        .order_by(desc(Payment.created_at))\
        .limit(limit)\
        .all()

    for p in recent_payments:
        tenant = db.query(Tenant).filter(Tenant.id == p.tenant_id).first()
        activities.append({
            "id": str(p.id),
            "type": "payment",
            "description": f"Payment of KES {p.amount:,.0f} received" if p.status == PaymentStatus.COMPLETED else f"Payment of KES {p.amount:,.0f} pending",
            "tenant": tenant.full_name if tenant else "Unknown",
            "amount": float(p.amount),
            "status": p.status.value,
            "timestamp": p.created_at.isoformat() if p.created_at else None
        })

    # Sort by timestamp
    activities.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

    return {
        "success": True,
        "total": len(activities),
        "activities": activities[:limit]
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
    """Get all properties in the system for agent to manage"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    properties = db.query(Property).all()

    property_list = []
    for prop in properties:
        units = db.query(Unit).filter(Unit.property_id == prop.id).count()
        occupied = db.query(Unit).filter(
            and_(Unit.property_id == prop.id, Unit.status == "occupied")
        ).count()
        vacant = units - occupied

        property_list.append({
            "id": str(prop.id),
            "name": prop.name,
            "address": prop.address,
            "city": prop.city,
            "description": prop.description,
            "image_url": prop.image_url,
            "total_units": units,
            "occupied_units": occupied,
            "vacant_units": vacant,
            "occupancy_rate": round((occupied / units * 100) if units > 0 else 0, 2)
        })

    return {
        "success": True,
        "total_properties": len(properties),
        "properties": property_list
    }


@router.post("/properties")
def create_agent_property(
    property_data: AgentPropertyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new property as an agent"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Determine property owner: use provided owner_id or fall back to agent
    property_owner_id = current_user.id
    if property_data.owner_id:
        # Validate owner exists and has OWNER role
        owner = db.query(User).filter(User.id == property_data.owner_id).first()
        if not owner:
            raise HTTPException(status_code=404, detail="Owner not found")
        if owner.role != UserRole.OWNER:
            raise HTTPException(
                status_code=400,
                detail=f"User has role '{owner.role.value}', expected 'owner'"
            )
        property_owner_id = owner.id

    # Create the property
    new_property = Property(
        id=uuid_module.uuid4(),
        user_id=property_owner_id,
        name=property_data.name,
        address=property_data.address,
        city=property_data.city,
        state=property_data.state,
        postal_code=property_data.postal_code,
        country=property_data.country,
        property_type=property_data.property_type,
        description=property_data.description,
        image_url=property_data.image_url,
        total_units=property_data.total_units or 0
    )

    db.add(new_property)
    db.flush()  # Get the property ID

    # Auto-generate units if total_units > 0
    units_created = 0
    if property_data.total_units and property_data.total_units > 0:
        for i in range(1, property_data.total_units + 1):
            unit = Unit(
                id=uuid_module.uuid4(),
                property_id=new_property.id,
                unit_number=f"{property_data.unit_prefix} {i}",
                bedrooms=property_data.default_bedrooms,
                bathrooms=property_data.default_bathrooms,
                toilets=property_data.default_toilets,
                monthly_rent=property_data.default_rent,
                square_feet=property_data.default_square_feet,
                has_master_bedroom=property_data.default_has_master_bedroom,
                has_servant_quarters=property_data.default_has_servant_quarters,
                sq_bathrooms=property_data.default_sq_bathrooms,
                description=property_data.default_unit_description,
                status="vacant"
            )
            db.add(unit)
            units_created += 1

    db.commit()
    db.refresh(new_property)

    return {
        "success": True,
        "message": "Property created successfully",
        "property": {
            "id": str(new_property.id),
            "name": new_property.name,
            "address": new_property.address,
            "city": new_property.city,
            "total_units": units_created,
            "created_at": new_property.created_at.isoformat() if new_property.created_at else None
        }
    }


@router.get("/marketplace")
def get_marketplace_properties(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all available properties with vacant units for sales/rentals"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Get all properties with at least one vacant unit
    properties = db.query(Property).all()

    marketplace_list = []
    for prop in properties:
        # Get vacant units for this property
        vacant_units = db.query(Unit).filter(
            and_(Unit.property_id == prop.id, Unit.status == "vacant")
        ).all()

        if len(vacant_units) > 0:
            # Calculate rent range
            rents = [u.monthly_rent for u in vacant_units if u.monthly_rent]
            min_rent = min(rents) if rents else 0
            max_rent = max(rents) if rents else 0

            # Get unit types summary
            bedroom_counts = {}
            for u in vacant_units:
                beds = u.bedrooms or 0
                bedroom_counts[beds] = bedroom_counts.get(beds, 0) + 1

            unit_types = [f"{beds}BR ({count})" for beds, count in sorted(bedroom_counts.items())]

            marketplace_list.append({
                "id": str(prop.id),
                "name": prop.name,
                "address": prop.address,
                "city": prop.city,
                "description": prop.description,
                "image_url": prop.image_url,
                "vacant_units": len(vacant_units),
                "min_rent": float(min_rent) if min_rent else None,
                "max_rent": float(max_rent) if max_rent else None,
                "unit_types": unit_types,
                "units": [
                    {
                        "id": str(u.id),
                        "unit_number": u.unit_number,
                        "bedrooms": u.bedrooms,
                        "bathrooms": u.bathrooms,
                        "toilets": u.toilets,
                        "square_feet": u.square_feet,
                        "monthly_rent": float(u.monthly_rent) if u.monthly_rent else None,
                        "has_master_bedroom": u.has_master_bedroom,
                        "has_servant_quarters": u.has_servant_quarters,
                        "description": u.description
                    }
                    for u in vacant_units
                ]
            })

    # Sort by number of vacant units (most first)
    marketplace_list.sort(key=lambda x: x["vacant_units"], reverse=True)

    return {
        "success": True,
        "total_properties": len(marketplace_list),
        "total_vacant_units": sum(p["vacant_units"] for p in marketplace_list),
        "properties": marketplace_list
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
        .filter(and_(Unit.property_id.in_(property_ids), Unit.status == "occupied"))\
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
            .filter(and_(Unit.property_id == prop.id, Unit.status == "occupied"))\
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


@router.get("/leads")
def get_agent_leads(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all leads for agent"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Get leads for this agent
    leads = db.query(Lead).filter(Lead.agent_id == current_user.id).order_by(desc(Lead.created_at)).all()

    # Calculate stats
    total_leads = len(leads)
    new_leads = len([l for l in leads if l.status == LeadStatus.NEW])
    contacted = len([l for l in leads if l.status == LeadStatus.CONTACTED])
    converted = len([l for l in leads if l.status == LeadStatus.CONVERTED])

    lead_list = []
    for lead in leads:
        lead_list.append({
            "id": str(lead.id),
            "name": lead.name,
            "email": lead.email,
            "phone": lead.phone,
            "property_interest": lead.property_interest,
            "budget": float(lead.budget) if lead.budget else None,
            "status": lead.status.value,
            "source": lead.source,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
            "notes": lead.notes
        })

    return {
        "success": True,
        "total_leads": total_leads,
        "new_leads": new_leads,
        "contacted": contacted,
        "converted": converted,
        "leads": lead_list
    }


@router.post("/leads")
def create_agent_lead(
    lead_data: LeadCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new lead"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    import uuid

    new_lead = Lead(
        id=uuid.uuid4(),
        agent_id=current_user.id,
        name=lead_data.name,
        email=lead_data.email,
        phone=lead_data.phone,
        property_interest=lead_data.property_interest,
        budget=lead_data.budget,
        source=lead_data.source,
        notes=lead_data.notes,
        status=LeadStatus.NEW
    )

    db.add(new_lead)
    db.commit()
    db.refresh(new_lead)

    return {
        "success": True,
        "message": "Lead created successfully",
        "lead": {
            "id": str(new_lead.id),
            "name": new_lead.name,
            "email": new_lead.email,
            "phone": new_lead.phone,
            "property_interest": new_lead.property_interest,
            "budget": float(new_lead.budget) if new_lead.budget else None,
            "status": new_lead.status.value,
            "source": new_lead.source,
            "created_at": new_lead.created_at.isoformat() if new_lead.created_at else None,
            "notes": new_lead.notes
        }
    }


@router.put("/leads/{lead_id}")
def update_agent_lead(
    lead_id: str,
    lead_data: LeadCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a lead"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    lead = db.query(Lead).filter(
        and_(Lead.id == lead_id, Lead.agent_id == current_user.id)
    ).first()

    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    lead.name = lead_data.name
    lead.email = lead_data.email
    lead.phone = lead_data.phone
    lead.property_interest = lead_data.property_interest
    lead.budget = lead_data.budget
    lead.source = lead_data.source
    lead.notes = lead_data.notes

    db.commit()
    db.refresh(lead)

    return {
        "success": True,
        "message": "Lead updated successfully",
        "lead": {
            "id": str(lead.id),
            "name": lead.name,
            "email": lead.email,
            "phone": lead.phone,
            "property_interest": lead.property_interest,
            "budget": float(lead.budget) if lead.budget else None,
            "status": lead.status.value,
            "source": lead.source,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
            "notes": lead.notes
        }
    }


class LeadStatusUpdate(BaseModel):
    status: str


@router.patch("/leads/{lead_id}/status")
def update_lead_status(
    lead_id: str,
    status_update: LeadStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update lead status"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    lead = db.query(Lead).filter(
        and_(Lead.id == lead_id, Lead.agent_id == current_user.id)
    ).first()

    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    try:
        new_status = LeadStatus(status_update.status.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {[s.value for s in LeadStatus]}"
        )

    lead.status = new_status
    if new_status == LeadStatus.CONTACTED:
        lead.last_contacted_at = datetime.utcnow()

    db.commit()

    return {
        "success": True,
        "message": f"Lead status updated to {new_status.value}",
        "lead_id": str(lead.id),
        "status": new_status.value
    }


# ============================================================================
# VIEWINGS ENDPOINTS
# ============================================================================

class ViewingCreate(BaseModel):
    property_id: str
    unit_id: Optional[str] = None
    client_name: str
    client_phone: str
    client_email: Optional[str] = None
    viewing_date: datetime
    notes: Optional[str] = None


@router.get("/viewings")
def get_agent_viewings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all viewings for agent"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    viewings = db.query(Viewing).filter(
        Viewing.agent_id == current_user.id
    ).order_by(desc(Viewing.viewing_date)).all()

    # Calculate stats
    total = len(viewings)
    scheduled = len([v for v in viewings if v.status == ViewingStatus.SCHEDULED])
    completed = len([v for v in viewings if v.status == ViewingStatus.COMPLETED])
    cancelled = len([v for v in viewings if v.status == ViewingStatus.CANCELLED])

    viewing_list = []
    for v in viewings:
        prop = db.query(Property).filter(Property.id == v.property_id).first()
        unit = db.query(Unit).filter(Unit.id == v.unit_id).first() if v.unit_id else None

        viewing_list.append({
            "id": str(v.id),
            "property_id": str(v.property_id),
            "property_name": prop.name if prop else "Unknown",
            "unit_id": str(v.unit_id) if v.unit_id else None,
            "unit_number": unit.unit_number if unit else None,
            "client_name": v.client_name,
            "client_phone": v.client_phone,
            "client_email": v.client_email,
            "viewing_date": v.viewing_date.isoformat() if v.viewing_date else None,
            "status": v.status.value,
            "notes": v.notes,
            "feedback": v.feedback,
            "created_at": v.created_at.isoformat() if v.created_at else None
        })

    return {
        "success": True,
        "total": total,
        "scheduled": scheduled,
        "completed": completed,
        "cancelled": cancelled,
        "viewings": viewing_list
    }


@router.post("/viewings")
def create_viewing(
    viewing_data: ViewingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Schedule a new property viewing"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    import uuid

    new_viewing = Viewing(
        id=uuid.uuid4(),
        agent_id=current_user.id,
        property_id=viewing_data.property_id,
        unit_id=viewing_data.unit_id,
        client_name=viewing_data.client_name,
        client_phone=viewing_data.client_phone,
        client_email=viewing_data.client_email,
        viewing_date=viewing_data.viewing_date,
        notes=viewing_data.notes,
        status=ViewingStatus.SCHEDULED
    )

    db.add(new_viewing)
    db.commit()
    db.refresh(new_viewing)

    return {
        "success": True,
        "message": "Viewing scheduled successfully",
        "viewing": {
            "id": str(new_viewing.id),
            "property_id": str(new_viewing.property_id),
            "client_name": new_viewing.client_name,
            "viewing_date": new_viewing.viewing_date.isoformat(),
            "status": new_viewing.status.value
        }
    }


class ViewingStatusUpdate(BaseModel):
    status: str
    feedback: Optional[str] = None


@router.patch("/viewings/{viewing_id}")
def update_viewing_status(
    viewing_id: str,
    update_data: ViewingStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update viewing status"""
    if current_user.role != UserRole.AGENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    viewing = db.query(Viewing).filter(
        and_(Viewing.id == viewing_id, Viewing.agent_id == current_user.id)
    ).first()

    if not viewing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Viewing not found")

    try:
        new_status = ViewingStatus(update_data.status.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {[s.value for s in ViewingStatus]}"
        )

    viewing.status = new_status
    if update_data.feedback:
        viewing.feedback = update_data.feedback

    db.commit()

    return {
        "success": True,
        "message": f"Viewing status updated to {new_status.value}",
        "viewing_id": str(viewing.id),
        "status": new_status.value
    }
