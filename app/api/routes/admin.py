"""
Admin Portal Routes - System Administration
User management, property management, system reports
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserRole
from app.models.property import Property, Unit
from app.models.tenant import Tenant
from app.models.payment import Payment, PaymentStatus
from app.models.maintenance import MaintenanceRequest

router = APIRouter(tags=["admin"])


def verify_admin(user: User):
    """Verify user has admin access"""
    if user.role not in [UserRole.ADMIN, UserRole.OWNER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


# ==================== USER MANAGEMENT ====================

@router.get("/users")
def get_all_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    search: Optional[str] = None,
    role: Optional[str] = None,
    skip: int = 0,
    limit: int = 100
):
    """Get all users with optional search and filter"""
    verify_admin(current_user)

    query = db.query(User)

    # Apply search filter
    if search:
        query = query.filter(
            (User.full_name.ilike(f"%{search}%")) |
            (User.email.ilike(f"%{search}%"))
        )

    # Apply role filter
    if role:
        try:
            role_enum = UserRole(role.lower())
            query = query.filter(User.role == role_enum)
        except ValueError:
            pass  # Invalid role, ignore filter

    total = query.count()
    users = query.order_by(desc(User.created_at)).offset(skip).limit(limit).all()

    user_list = []
    for user in users:
        user_list.append({
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name or "",
            "phone": user.phone or "",
            "role": user.role.value if user.role else "owner",
            "is_active": user.is_active if hasattr(user, 'is_active') else True,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login": user.last_login.isoformat() if hasattr(user, 'last_login') and user.last_login else None
        })

    return {
        "success": True,
        "total": total,
        "users": user_list
    }


class UserCreate(BaseModel):
    email: str
    full_name: str
    password: str
    role: str = "owner"
    phone: Optional[str] = None


@router.post("/users")
def create_user(
    user_data: UserCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new user (admin only)"""
    verify_admin(current_user)

    # Check if user exists
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    from app.core.security import get_password_hash
    import uuid

    try:
        role_enum = UserRole(user_data.role.lower())
    except ValueError:
        role_enum = UserRole.OWNER

    new_user = User(
        id=uuid.uuid4(),
        email=user_data.email,
        full_name=user_data.full_name,
        hashed_password=get_password_hash(user_data.password),
        role=role_enum,
        phone=user_data.phone
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "success": True,
        "message": "User created successfully",
        "user": {
            "id": str(new_user.id),
            "email": new_user.email,
            "full_name": new_user.full_name,
            "role": new_user.role.value
        }
    }


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


@router.put("/users/{user_id}")
def update_user(
    user_id: str,
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a user (admin only)"""
    verify_admin(current_user)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user_data.full_name:
        user.full_name = user_data.full_name
    if user_data.phone:
        user.phone = user_data.phone
    if user_data.role:
        try:
            user.role = UserRole(user_data.role.lower())
        except ValueError:
            pass
    if user_data.is_active is not None and hasattr(user, 'is_active'):
        user.is_active = user_data.is_active

    db.commit()
    db.refresh(user)

    return {
        "success": True,
        "message": "User updated successfully",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value
        }
    }


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a user (admin only)"""
    verify_admin(current_user)

    if str(current_user.id) == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete yourself")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    db.delete(user)
    db.commit()

    return {
        "success": True,
        "message": "User deleted successfully"
    }


# ==================== PROPERTY MANAGEMENT ====================

@router.get("/properties")
def get_all_properties(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100
):
    """Get all properties in the system"""
    verify_admin(current_user)

    query = db.query(Property)

    if search:
        query = query.filter(
            (Property.name.ilike(f"%{search}%")) |
            (Property.address.ilike(f"%{search}%"))
        )

    total = query.count()
    properties = query.order_by(desc(Property.created_at)).offset(skip).limit(limit).all()

    property_list = []
    for prop in properties:
        units = db.query(Unit).filter(Unit.property_id == prop.id).all()
        occupied = len([u for u in units if u.is_occupied])
        total_units = len(units)

        # Get owner info
        owner = db.query(User).filter(User.id == prop.owner_id).first() if prop.owner_id else None

        property_list.append({
            "id": str(prop.id),
            "name": prop.name,
            "address": prop.address,
            "owner": owner.full_name if owner else "Unknown",
            "owner_id": str(prop.owner_id) if prop.owner_id else None,
            "total_units": total_units,
            "occupied_units": occupied,
            "vacant_units": total_units - occupied,
            "occupancy_rate": round((occupied / total_units * 100) if total_units > 0 else 0, 2),
            "created_at": prop.created_at.isoformat() if prop.created_at else None
        })

    return {
        "success": True,
        "total": total,
        "properties": property_list
    }


# ==================== SYSTEM REPORTS ====================

@router.get("/reports")
def get_system_reports(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get list of available system reports"""
    verify_admin(current_user)

    reports = [
        {
            "id": "revenue-summary",
            "title": "Revenue Summary Report",
            "description": "Total revenue from rent and utilities",
            "type": "financial"
        },
        {
            "id": "occupancy-report",
            "title": "Occupancy Report",
            "description": "Property and unit occupancy statistics",
            "type": "operational"
        },
        {
            "id": "user-activity",
            "title": "User Activity Report",
            "description": "User registrations and activity",
            "type": "system"
        },
        {
            "id": "maintenance-summary",
            "title": "Maintenance Summary",
            "description": "Maintenance requests and resolutions",
            "type": "operational"
        },
        {
            "id": "payment-collection",
            "title": "Payment Collection Report",
            "description": "Payment collection rates and defaulters",
            "type": "financial"
        }
    ]

    return {
        "success": True,
        "total_reports": len(reports),
        "reports": reports
    }


@router.get("/reports/{report_id}")
def get_report_data(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get specific report data"""
    verify_admin(current_user)

    today = datetime.utcnow().date()
    current_month_start = datetime(today.year, today.month, 1).date()

    if report_id == "revenue-summary":
        # Revenue data - use paid_at instead of payment_date
        total_collected = db.query(func.sum(Payment.amount))\
            .filter(
                and_(
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.paid_at >= datetime.combine(current_month_start, datetime.min.time())
                )
            ).scalar() or 0

        return {
            "success": True,
            "report_id": report_id,
            "title": "Revenue Summary Report",
            "period": f"{current_month_start} to {today}",
            "data": {
                "total_collected": float(total_collected),
                "total_revenue": float(total_collected)
            }
        }

    elif report_id == "occupancy-report":
        total_units = db.query(Unit).count()
        occupied_units = db.query(Unit).filter(Unit.is_occupied == True).count()
        vacant_units = total_units - occupied_units

        return {
            "success": True,
            "report_id": report_id,
            "title": "Occupancy Report",
            "data": {
                "total_units": total_units,
                "occupied_units": occupied_units,
                "vacant_units": vacant_units,
                "occupancy_rate": round((occupied_units / total_units * 100) if total_units > 0 else 0, 2)
            }
        }

    elif report_id == "user-activity":
        total_users = db.query(User).count()
        new_users_month = db.query(User).filter(User.created_at >= current_month_start).count()

        # Count by role
        role_counts = {}
        for role in UserRole:
            count = db.query(User).filter(User.role == role).count()
            if count > 0:
                role_counts[role.value] = count

        return {
            "success": True,
            "report_id": report_id,
            "title": "User Activity Report",
            "data": {
                "total_users": total_users,
                "new_users_this_month": new_users_month,
                "users_by_role": role_counts
            }
        }

    elif report_id == "maintenance-summary":
        from app.models.maintenance import MaintenanceStatus

        total = db.query(MaintenanceRequest).count()
        pending = db.query(MaintenanceRequest).filter(MaintenanceRequest.status == MaintenanceStatus.PENDING).count()
        in_progress = db.query(MaintenanceRequest).filter(MaintenanceRequest.status == MaintenanceStatus.IN_PROGRESS).count()
        completed = db.query(MaintenanceRequest).filter(MaintenanceRequest.status == MaintenanceStatus.COMPLETED).count()

        return {
            "success": True,
            "report_id": report_id,
            "title": "Maintenance Summary",
            "data": {
                "total_requests": total,
                "pending": pending,
                "in_progress": in_progress,
                "completed": completed,
                "completion_rate": round((completed / total * 100) if total > 0 else 0, 2)
            }
        }

    elif report_id == "payment-collection":
        expected_rent = db.query(func.sum(Unit.monthly_rent))\
            .filter(Unit.is_occupied == True)\
            .scalar() or 0

        collected_payments = db.query(func.sum(Payment.amount))\
            .filter(
                and_(
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.paid_at >= datetime.combine(current_month_start, datetime.min.time())
                )
            ).scalar() or 0

        pending_payments = db.query(func.sum(Payment.amount))\
            .filter(Payment.status == PaymentStatus.PENDING)\
            .scalar() or 0

        return {
            "success": True,
            "report_id": report_id,
            "title": "Payment Collection Report",
            "data": {
                "expected_rent": float(expected_rent),
                "collected_payments": float(collected_payments),
                "pending_payments": float(pending_payments),
                "collection_rate": round((float(collected_payments) / float(expected_rent) * 100) if expected_rent > 0 else 0, 2)
            }
        }

    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")


# ==================== SYSTEM STATS ====================

@router.get("/stats")
def get_system_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get overall system statistics"""
    verify_admin(current_user)

    total_users = db.query(User).count()
    total_properties = db.query(Property).count()
    total_units = db.query(Unit).count()
    total_tenants = db.query(Tenant).filter(Tenant.status == "active").count()

    today = datetime.utcnow().date()
    current_month_start = datetime(today.year, today.month, 1).date()

    total_revenue = db.query(func.sum(Payment.amount))\
        .filter(
            and_(
                Payment.status == PaymentStatus.COMPLETED,
                Payment.paid_at >= datetime.combine(current_month_start, datetime.min.time())
            )
        ).scalar() or 0

    return {
        "success": True,
        "stats": {
            "total_users": total_users,
            "total_properties": total_properties,
            "total_units": total_units,
            "total_tenants": total_tenants,
            "monthly_revenue": float(total_revenue)
        }
    }


# ==================== REPORT GENERATION ====================

@router.post("/reports/generate")
def generate_admin_report(
    report_type: str = "revenue-summary",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Generate a new admin report"""
    verify_admin(current_user)

    today = datetime.utcnow().date()
    current_month_start = datetime(today.year, today.month, 1).date()

    # Generate comprehensive report based on type
    report_data = {}

    if report_type == "revenue-summary":
        total_collected = db.query(func.sum(Payment.amount))\
            .filter(
                and_(
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.paid_at >= datetime.combine(current_month_start, datetime.min.time())
                )
            ).scalar() or 0

        report_data = {
            "total_collected": float(total_collected),
            "total_revenue": float(total_collected)
        }

    elif report_type == "full-system":
        # Comprehensive system report
        total_users = db.query(User).count()
        total_properties = db.query(Property).count()
        total_units = db.query(Unit).count()
        occupied_units = db.query(Unit).filter(Unit.is_occupied == True).count()
        total_tenants = db.query(Tenant).filter(Tenant.status == "active").count()

        total_revenue = db.query(func.sum(Payment.amount))\
            .filter(
                and_(
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.paid_at >= datetime.combine(current_month_start, datetime.min.time())
                )
            ).scalar() or 0

        report_data = {
            "users": total_users,
            "properties": total_properties,
            "units": {"total": total_units, "occupied": occupied_units},
            "tenants": total_tenants,
            "monthly_revenue": float(total_revenue)
        }

    return {
        "success": True,
        "message": "Report generated successfully",
        "report": {
            "id": f"admin-report-{today.isoformat()}",
            "type": report_type,
            "generated_at": datetime.utcnow().isoformat(),
            "generated_by": current_user.full_name,
            "data": report_data
        }
    }
