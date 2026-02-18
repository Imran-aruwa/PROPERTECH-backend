from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.property import Property, Unit
from app.schemas.property import (
    PropertyCreate, PropertyResponse, PropertyUpdate,
    UnitCreate, UnitResponse, UnitUpdate
)

router = APIRouter()


def is_unit_occupied(status: str) -> bool:
    """Check if a unit status counts as 'occupied' for calculations"""
    if not status:
        return False
    return status.lower() in ("occupied", "rented", "mortgaged")


# ==================== STATIC ROUTES FIRST (before /{property_id}) ====================

@router.get("/units", response_model=List[UnitResponse])
@router.get("/units/", response_model=List[UnitResponse])
def list_all_units(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all units for current user's properties"""
    from app.models.user import UserRole

    # For owners, get all units
    if current_user.role in [UserRole.OWNER, UserRole.ADMIN]:
        units = db.query(Unit).all()
        return units

    # For other users, filter by their properties
    properties = db.query(Property)\
        .filter(Property.user_id == current_user.id)\
        .all()

    property_ids = [p.id for p in properties]
    units = db.query(Unit).filter(Unit.property_id.in_(property_ids)).all()
    return units


@router.get("/units/{unit_id}", response_model=UnitResponse)
def get_unit_by_id(
    unit_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific unit by ID"""
    from app.models.user import UserRole

    unit = db.query(Unit).filter(Unit.id == unit_id).first()

    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    # Get property to check access
    property = db.query(Property).filter(Property.id == unit.property_id).first()
    has_access = (
        property and property.user_id == current_user.id or
        current_user.role in [UserRole.OWNER, UserRole.AGENT, UserRole.ADMIN, UserRole.CARETAKER]
    )

    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied")

    return unit


@router.put("/units/{unit_id}", response_model=UnitResponse)
def update_unit_by_id(
    unit_id: UUID,
    unit_update: UnitUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a unit"""
    from app.models.user import UserRole

    unit = db.query(Unit).filter(Unit.id == unit_id).first()

    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    # Get property to check access
    property = db.query(Property).filter(Property.id == unit.property_id).first()
    has_access = (
        property and property.user_id == current_user.id or
        current_user.role in [UserRole.OWNER, UserRole.AGENT, UserRole.ADMIN]
    )

    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied")

    for key, value in unit_update.dict(exclude_unset=True).items():
        setattr(unit, key, value)

    db.commit()
    db.refresh(unit)
    return unit


@router.delete("/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_unit_by_id(
    unit_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a unit"""
    from app.models.user import UserRole

    unit = db.query(Unit).filter(Unit.id == unit_id).first()

    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    # Get property to check access
    property = db.query(Property).filter(Property.id == unit.property_id).first()
    has_access = (
        property and property.user_id == current_user.id or
        current_user.role in [UserRole.OWNER, UserRole.AGENT, UserRole.ADMIN]
    )

    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied")

    db.delete(unit)
    db.commit()
    return None


# ==================== HELPER FUNCTIONS ====================

def property_with_stats(prop: Property) -> dict:
    """Convert property to dict with computed stats"""
    occupied = sum(1 for u in prop.units if is_unit_occupied(u.status)) if prop.units else 0
    return {
        "id": prop.id,
        "user_id": prop.user_id,
        "name": prop.name,
        "address": prop.address,
        "area": prop.area,
        "city": prop.city,
        "state": prop.state,
        "postal_code": prop.postal_code,
        "country": prop.country,
        "property_type": prop.property_type,
        "description": prop.description,
        "purchase_price": prop.purchase_price,
        "purchase_date": prop.purchase_date,
        "image_url": prop.image_url,
        "photos": [],
        "total_units": prop.total_units or len(prop.units) if prop.units else 0,
        "occupied_units": occupied,
        "created_at": prop.created_at,
        "units": prop.units or []
    }

# Property endpoints
@router.post("/", response_model=PropertyResponse, status_code=status.HTTP_201_CREATED)
def create_property(
    property_in: PropertyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new property with optional automatic unit generation"""
    property_data = property_in.dict()

    # Extract unit generation fields (not part of Property model)
    total_units = property_data.pop('total_units', None) or 0
    unit_prefix = property_data.pop('unit_prefix', 'Unit')
    default_bedrooms = property_data.pop('default_bedrooms', 1)
    default_bathrooms = property_data.pop('default_bathrooms', 1.0)
    default_toilets = property_data.pop('default_toilets', 0)
    default_rent = property_data.pop('default_rent', None)
    default_square_feet = property_data.pop('default_square_feet', None)
    # Master bedroom
    default_has_master_bedroom = property_data.pop('default_has_master_bedroom', False)
    # Servant quarters
    default_has_servant_quarters = property_data.pop('default_has_servant_quarters', False)
    default_sq_bathrooms = property_data.pop('default_sq_bathrooms', 0)
    # Unit description
    default_unit_description = property_data.pop('default_unit_description', None)

    # Store total_units in property
    property_data['total_units'] = total_units

    # Create the property
    property = Property(**property_data, user_id=current_user.id)
    db.add(property)
    db.flush()  # Get the property ID without committing

    # Auto-generate units if total_units > 0
    if total_units > 0:
        units_to_create = []
        for i in range(1, total_units + 1):
            unit = Unit(
                property_id=property.id,
                unit_number=f"{unit_prefix} {i}",
                bedrooms=default_bedrooms,
                bathrooms=default_bathrooms,
                toilets=default_toilets,
                monthly_rent=default_rent,
                square_feet=default_square_feet,
                has_master_bedroom=default_has_master_bedroom,
                has_servant_quarters=default_has_servant_quarters,
                sq_bathrooms=default_sq_bathrooms,
                description=default_unit_description,
                status="vacant"
            )
            units_to_create.append(unit)

        # Bulk insert all units
        db.bulk_save_objects(units_to_create)

    db.commit()
    db.refresh(property)
    return property_with_stats(property)

@router.get("/", response_model=List[PropertyResponse])
def list_properties(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all properties for current user"""
    from app.models.user import UserRole
    from sqlalchemy import text
    import logging
    logger = logging.getLogger(__name__)

    # For owners, ensure all properties are linked via raw SQL (avoids UUID type issues)
    if current_user.role == UserRole.OWNER:
        owner_id_str = str(current_user.id)
        try:
            # Check if owner already has properties
            count_result = db.execute(
                text("SELECT COUNT(*) FROM properties WHERE CAST(user_id AS TEXT) = :oid"),
                {"oid": owner_id_str}
            )
            owner_prop_count = count_result.scalar()

            total_result = db.execute(text("SELECT COUNT(*) FROM properties"))
            total_count = total_result.scalar()

            if owner_prop_count == 0 and total_count > 0:
                logger.info(f"[PROPERTIES] Owner has 0/{total_count} properties, fixing via SQL")
                db.execute(
                    text("UPDATE properties SET user_id = CAST(:oid AS UUID)"),
                    {"oid": owner_id_str}
                )
                db.commit()
                db.expire_all()
                logger.info(f"[PROPERTIES] Linked all properties to owner {owner_id_str}")
        except Exception as e:
            logger.error(f"[PROPERTIES] SQL fix failed: {e}")
            db.rollback()

    # Get properties for this user
    properties = db.query(Property)\
        .filter(Property.user_id == current_user.id)\
        .offset(skip)\
        .limit(limit)\
        .all()

    logger.info(f"[PROPERTIES] Returning {len(properties)} properties for user {current_user.id}")
    return [property_with_stats(p) for p in properties]

@router.get("/{property_id}", response_model=PropertyResponse)
def get_property(
    property_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific property"""
    property = db.query(Property)\
        .filter(Property.id == property_id, Property.user_id == current_user.id)\
        .first()

    if not property:
        raise HTTPException(status_code=404, detail="Property not found")
    return property_with_stats(property)

@router.put("/{property_id}", response_model=PropertyResponse)
def update_property(
    property_id: UUID,
    property_update: PropertyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a property"""
    property = db.query(Property)\
        .filter(Property.id == property_id, Property.user_id == current_user.id)\
        .first()

    if not property:
        raise HTTPException(status_code=404, detail="Property not found")

    for key, value in property_update.dict(exclude_unset=True).items():
        setattr(property, key, value)

    db.commit()
    db.refresh(property)
    return property_with_stats(property)

@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_property(
    property_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a property"""
    property = db.query(Property)\
        .filter(Property.id == property_id, Property.user_id == current_user.id)\
        .first()
    
    if not property:
        raise HTTPException(status_code=404, detail="Property not found")
    
    db.delete(property)
    db.commit()
    return None

# Unit endpoints
@router.post("/{property_id}/units", response_model=UnitResponse, status_code=status.HTTP_201_CREATED)
def create_unit(
    property_id: UUID,
    unit_in: UnitCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add a unit to a property"""
    from app.models.user import UserRole

    # Get property - allow access if user owns it OR if user is an owner role
    property = db.query(Property).filter(Property.id == property_id).first()

    if not property:
        raise HTTPException(status_code=404, detail="Property not found")

    # Allow access if: user owns property, OR user is owner/agent role
    has_access = (
        property.user_id == current_user.id or
        current_user.role in [UserRole.OWNER, UserRole.AGENT, UserRole.ADMIN]
    )

    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied")

    # Link property to this owner if not already linked
    if current_user.role == UserRole.OWNER and property.user_id != current_user.id:
        property.user_id = current_user.id
        db.commit()

    unit = Unit(**unit_in.dict(), property_id=property_id)
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return unit

@router.get("/{property_id}/units", response_model=List[UnitResponse])
def list_units(
    property_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all units for a property"""
    from app.models.user import UserRole

    # Get property - allow access if user owns it OR if user is an owner role
    property = db.query(Property).filter(Property.id == property_id).first()

    if not property:
        raise HTTPException(status_code=404, detail="Property not found")

    # Allow access if: user owns property, OR user is owner/agent role
    has_access = (
        property.user_id == current_user.id or
        current_user.role in [UserRole.OWNER, UserRole.AGENT, UserRole.ADMIN, UserRole.CARETAKER]
    )

    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied")

    units = db.query(Unit).filter(Unit.property_id == property_id).all()
    return units


@router.put("/{property_id}/units/{unit_id}", response_model=UnitResponse)
def update_unit_with_property(
    property_id: UUID,
    unit_id: UUID,
    unit_update: UnitUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a unit (alternative path with property_id)"""
    from app.models.user import UserRole

    # Get property - allow access for owners/agents
    property = db.query(Property).filter(Property.id == property_id).first()

    if not property:
        raise HTTPException(status_code=404, detail="Property not found")

    has_access = (
        property.user_id == current_user.id or
        current_user.role in [UserRole.OWNER, UserRole.AGENT, UserRole.ADMIN]
    )

    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied")

    unit = db.query(Unit)\
        .filter(Unit.id == unit_id, Unit.property_id == property_id)\
        .first()

    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    for key, value in unit_update.dict(exclude_unset=True).items():
        setattr(unit, key, value)

    db.commit()
    db.refresh(unit)
    return unit