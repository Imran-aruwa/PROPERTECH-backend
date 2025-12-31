from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from app.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.property import Property, Unit
from app.schemas.property import (
    PropertyCreate, PropertyResponse, PropertyUpdate,
    UnitCreate, UnitResponse, UnitUpdate
)

router = APIRouter()

# Property endpoints
@router.post("/", response_model=PropertyResponse, status_code=status.HTTP_201_CREATED)
def create_property(
    property_in: PropertyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new property"""
    property = Property(**property_in.dict(), user_id=current_user.id)
    db.add(property)
    db.commit()
    db.refresh(property)
    return property

@router.get("/", response_model=List[PropertyResponse])
def list_properties(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all properties for current user"""
    properties = db.query(Property)\
        .filter(Property.user_id == current_user.id)\
        .offset(skip)\
        .limit(limit)\
        .all()
    return properties

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
    return property

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
    return property

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
    # Verify property ownership
    property = db.query(Property)\
        .filter(Property.id == property_id, Property.user_id == current_user.id)\
        .first()
    
    if not property:
        raise HTTPException(status_code=404, detail="Property not found")
    
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
    # Verify property ownership
    property = db.query(Property)\
        .filter(Property.id == property_id, Property.user_id == current_user.id)\
        .first()
    
    if not property:
        raise HTTPException(status_code=404, detail="Property not found")
    
    units = db.query(Unit).filter(Unit.property_id == property_id).all()
    return units

@router.put("/units/{unit_id}", response_model=UnitResponse)
def update_unit(
    unit_id: UUID,
    unit_update: UnitUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a unit"""
    unit = db.query(Unit)\
        .join(Property)\
        .filter(Unit.id == unit_id, Property.user_id == current_user.id)\
        .first()
    
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    
    for key, value in unit_update.dict(exclude_unset=True).items():
        setattr(unit, key, value)
    
    db.commit()
    db.refresh(unit)
    return unit

@router.delete("/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_unit(
    unit_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a unit"""
    unit = db.query(Unit)\
        .join(Property)\
        .filter(Unit.id == unit_id, Property.user_id == current_user.id)\
        .first()

    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    db.delete(unit)
    db.commit()
    return None


@router.get("/units", response_model=List[UnitResponse])
@router.get("/units/", response_model=List[UnitResponse])
def list_all_units(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all units for current user's properties"""
    properties = db.query(Property)\
        .filter(Property.user_id == current_user.id)\
        .all()

    property_ids = [p.id for p in properties]
    units = db.query(Unit).filter(Unit.property_id.in_(property_ids)).all()
    return units


@router.get("/units/{unit_id}", response_model=UnitResponse)
def get_unit(
    unit_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific unit by ID"""
    unit = db.query(Unit)\
        .join(Property)\
        .filter(Unit.id == unit_id, Property.user_id == current_user.id)\
        .first()

    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    return unit


@router.put("/{property_id}/units/{unit_id}", response_model=UnitResponse)
def update_unit_with_property(
    property_id: UUID,
    unit_id: UUID,
    unit_update: UnitUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a unit (alternative path with property_id)"""
    # Verify property ownership
    property = db.query(Property)\
        .filter(Property.id == property_id, Property.user_id == current_user.id)\
        .first()

    if not property:
        raise HTTPException(status_code=404, detail="Property not found")

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