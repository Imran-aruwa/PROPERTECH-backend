"""
Inspection Routes - Offline-first property inspection system
Supports create, media upload, list, detail, review, and lock operations
"""
import base64
import logging
import math
import os
import uuid as uuid_module
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, desc
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserRole
from app.models.property import Property, Unit
from app.models.inspection import (
    Inspection, InspectionItem, InspectionMedia,
    InspectionMeterReading, InspectionStatus
)
from app.schemas.inspection import (
    InspectionCreateRequest, InspectionMediaUpload,
    InspectionReviewRequest, InspectionListResponse,
    InspectionDetailResponse, InspectionPaginatedResponse,
    InspectionItemResponse, InspectionMediaResponse,
    InspectionMeterReadingResponse
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["inspections"])

# Roles that map to performed_by_role values
INSPECTION_ROLES = {
    UserRole.OWNER: "owner",
    UserRole.AGENT: "agent",
    UserRole.CARETAKER: "caretaker",
}


def get_user_accessible_property_ids(db: Session, user: User) -> Optional[list]:
    """
    Get property IDs accessible to user based on role.
    Returns None if user has no property-based access restrictions (shouldn't happen).
    """
    if user.role == UserRole.OWNER:
        props = db.query(Property.id).filter(Property.user_id == user.id).all()
        return [p.id for p in props]
    elif user.role == UserRole.AGENT:
        # Agents manage all properties in the system (consistent with agent portal)
        props = db.query(Property.id).all()
        return [p.id for p in props]
    return []


def build_inspection_list_response(inspection: Inspection) -> dict:
    """Build list response dict with display fields."""
    data = {
        "id": inspection.id,
        "client_uuid": inspection.client_uuid,
        "property_id": inspection.property_id,
        "unit_id": inspection.unit_id,
        "performed_by_id": inspection.performed_by_id,
        "performed_by_role": inspection.performed_by_role,
        "inspection_type": inspection.inspection_type,
        "status": inspection.status,
        "inspection_date": inspection.inspection_date,
        "notes": inspection.notes,
        "created_at": inspection.created_at,
        "updated_at": inspection.updated_at,
        "property_name": inspection.property.name if inspection.property else None,
        "unit_number": inspection.unit.unit_number if inspection.unit else None,
        "performed_by_name": inspection.performed_by.full_name if inspection.performed_by else None,
    }
    return data


# === 1. POST /api/inspections/ - Create inspection ===

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_inspection(
    request: InspectionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new inspection with items and meter readings (offline-sync)."""
    # Check role permission
    if current_user.role not in INSPECTION_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners, agents, and caretakers can create inspections"
        )

    # Check for duplicate client_uuid
    existing = db.query(Inspection).filter(
        Inspection.client_uuid == request.client_uuid
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"detail": "duplicate", "inspection_id": str(existing.id)}
        )

    # Verify property and unit exist
    prop = db.query(Property).filter(Property.id == request.inspection.property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    unit = db.query(Unit).filter(Unit.id == request.inspection.unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    # Create inspection
    inspection = Inspection(
        client_uuid=request.client_uuid,
        property_id=request.inspection.property_id,
        unit_id=request.inspection.unit_id,
        performed_by_id=current_user.id,
        performed_by_role=INSPECTION_ROLES[current_user.role],
        inspection_type=request.inspection.inspection_type,
        status=InspectionStatus.SUBMITTED.value,
        inspection_date=request.inspection.inspection_date,
        gps_lat=request.inspection.gps_lat,
        gps_lng=request.inspection.gps_lng,
        device_id=request.inspection.device_id,
        offline_created_at=request.inspection.offline_created_at,
        notes=request.inspection.notes,
    )
    db.add(inspection)
    db.flush()  # Get the ID without committing

    # Create inspection items
    for item_data in request.items:
        item = InspectionItem(
            inspection_id=inspection.id,
            client_uuid=item_data.client_uuid,
            name=item_data.name,
            category=item_data.category,
            condition=item_data.condition,
            comment=item_data.comment,
        )
        db.add(item)

    # Create meter readings
    for reading_data in request.meter_readings:
        reading = InspectionMeterReading(
            inspection_id=inspection.id,
            client_uuid=reading_data.client_uuid,
            unit_id=reading_data.unit_id,
            meter_type=reading_data.meter_type,
            previous_reading=reading_data.previous_reading,
            current_reading=reading_data.current_reading,
            reading_date=reading_data.reading_date,
        )
        db.add(reading)

    db.commit()
    db.refresh(inspection)

    # Expire to force reload of relationships
    db.expire(inspection)

    response = build_inspection_list_response(inspection)
    response["gps_lat"] = inspection.gps_lat
    response["gps_lng"] = inspection.gps_lng
    response["device_id"] = inspection.device_id
    response["offline_created_at"] = inspection.offline_created_at
    response["items"] = [
        InspectionItemResponse.model_validate(i).model_dump() for i in inspection.items
    ]
    response["meter_readings"] = [
        InspectionMeterReadingResponse.model_validate(r).model_dump() for r in inspection.meter_readings
    ]
    response["media"] = []

    return response


# === 2. POST /api/inspections/{id}/media/ - Upload media ===

@router.post("/{inspection_id}/media/", status_code=status.HTTP_201_CREATED)
def upload_inspection_media(
    inspection_id: uuid_module.UUID,
    media_data: InspectionMediaUpload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload media (photo/video) for an inspection."""
    inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")

    # Only the person who performed the inspection can upload media
    if inspection.performed_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Cannot add media to locked inspections
    if inspection.status == InspectionStatus.LOCKED.value:
        raise HTTPException(status_code=400, detail="Cannot modify locked inspection")

    # Check duplicate media client_uuid
    existing = db.query(InspectionMedia).filter(
        InspectionMedia.client_uuid == media_data.client_uuid
    ).first()
    if existing:
        return InspectionMediaResponse.model_validate(existing).model_dump()

    # Decode base64 and save file
    try:
        # Strip data URI prefix if present (e.g., "data:image/jpeg;base64,")
        file_content = media_data.file_data
        if ";base64," in file_content:
            file_content = file_content.split(";base64,")[1]
        file_bytes = base64.b64decode(file_content)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 file data")

    # Save to local uploads directory (replace with Cloudinary/S3 in production)
    upload_dir = os.path.join("uploads", "inspections", str(inspection_id))
    os.makedirs(upload_dir, exist_ok=True)

    ext = "jpg" if media_data.file_type == "photo" else "mp4"
    filename = f"{media_data.client_uuid}.{ext}"
    filepath = os.path.join(upload_dir, filename)

    with open(filepath, "wb") as f:
        f.write(file_bytes)

    file_url = f"/uploads/inspections/{inspection_id}/{filename}"

    media = InspectionMedia(
        inspection_id=inspection_id,
        client_uuid=media_data.client_uuid,
        file_url=file_url,
        file_type=media_data.file_type,
        captured_at=media_data.captured_at,
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    return InspectionMediaResponse.model_validate(media).model_dump()


# === 3. GET /api/inspections/ - List inspections ===

@router.get("/")
def list_inspections(
    property_id: Optional[uuid_module.UUID] = None,
    status_filter: Optional[str] = None,
    type_filter: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List inspections with role-based filtering."""
    if current_user.role not in [UserRole.OWNER, UserRole.AGENT, UserRole.CARETAKER, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Inspection).options(
        joinedload(Inspection.property),
        joinedload(Inspection.unit),
        joinedload(Inspection.performed_by),
    )

    # Role-based filtering
    if current_user.role == UserRole.CARETAKER:
        # Caretakers see only their own inspections
        query = query.filter(Inspection.performed_by_id == current_user.id)
    elif current_user.role == UserRole.OWNER:
        # Owners see all inspections for their properties
        owner_property_ids = get_user_accessible_property_ids(db, current_user)
        query = query.filter(Inspection.property_id.in_(owner_property_ids))
    elif current_user.role == UserRole.AGENT:
        # Agents see own inspections + caretaker inspections for managed properties
        agent_property_ids = get_user_accessible_property_ids(db, current_user)
        query = query.filter(
            and_(
                Inspection.property_id.in_(agent_property_ids),
                (
                    (Inspection.performed_by_id == current_user.id) |
                    (Inspection.performed_by_role == "caretaker")
                )
            )
        )
    # Admin sees everything (no filter)

    # Apply query filters
    if property_id:
        query = query.filter(Inspection.property_id == property_id)
    if status_filter:
        query = query.filter(Inspection.status == status_filter)
    if type_filter:
        query = query.filter(Inspection.inspection_type == type_filter)

    # Get total count
    total = query.count()

    # Pagination
    size = min(size, 100)
    offset = (page - 1) * size
    inspections = query.order_by(desc(Inspection.created_at)).offset(offset).limit(size).all()

    items = [build_inspection_list_response(i) for i in inspections]

    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "pages": math.ceil(total / size) if size > 0 else 0,
    }


# === 4. GET /api/inspections/{id}/ - Get detail ===

@router.get("/{inspection_id}/")
def get_inspection_detail(
    inspection_id: uuid_module.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get full inspection detail with items, media, and meter readings."""
    inspection = db.query(Inspection).options(
        joinedload(Inspection.property),
        joinedload(Inspection.unit),
        joinedload(Inspection.performed_by),
        joinedload(Inspection.items),
        joinedload(Inspection.media),
        joinedload(Inspection.meter_readings),
    ).filter(Inspection.id == inspection_id).first()

    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")

    # Permission check
    has_access = False
    if current_user.role == UserRole.ADMIN:
        has_access = True
    elif current_user.role == UserRole.CARETAKER:
        has_access = inspection.performed_by_id == current_user.id
    elif current_user.role == UserRole.OWNER:
        owner_property_ids = get_user_accessible_property_ids(db, current_user)
        has_access = inspection.property_id in owner_property_ids
    elif current_user.role == UserRole.AGENT:
        agent_property_ids = get_user_accessible_property_ids(db, current_user)
        has_access = (
            inspection.property_id in agent_property_ids and
            (inspection.performed_by_id == current_user.id or inspection.performed_by_role == "caretaker")
        )

    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied")

    response = build_inspection_list_response(inspection)
    response["gps_lat"] = inspection.gps_lat
    response["gps_lng"] = inspection.gps_lng
    response["device_id"] = inspection.device_id
    response["offline_created_at"] = inspection.offline_created_at
    response["items"] = [
        InspectionItemResponse.model_validate(i).model_dump() for i in inspection.items
    ]
    response["media"] = [
        InspectionMediaResponse.model_validate(m).model_dump() for m in inspection.media
    ]
    response["meter_readings"] = [
        InspectionMeterReadingResponse.model_validate(r).model_dump() for r in inspection.meter_readings
    ]

    return response


# === 5. PATCH /api/inspections/{id}/review/ - Mark reviewed ===

@router.patch("/{inspection_id}/review/")
def review_inspection(
    inspection_id: uuid_module.UUID,
    review_data: InspectionReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark an inspection as reviewed. Only owner/agent can call."""
    if current_user.role not in [UserRole.OWNER, UserRole.AGENT, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Only owners and agents can review inspections")

    inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")

    if inspection.status != InspectionStatus.SUBMITTED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot review inspection with status '{inspection.status}'. Must be 'submitted'."
        )

    inspection.status = InspectionStatus.REVIEWED.value
    if review_data.notes:
        # Append review notes
        existing_notes = inspection.notes or ""
        inspection.notes = f"{existing_notes}\n[Review] {review_data.notes}".strip()
    inspection.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(inspection)

    return {"success": True, "status": inspection.status, "id": str(inspection.id)}


# === 6. PATCH /api/inspections/{id}/lock/ - Lock inspection ===

@router.patch("/{inspection_id}/lock/")
def lock_inspection(
    inspection_id: uuid_module.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lock an inspection permanently. Only owner can call."""
    if current_user.role not in [UserRole.OWNER, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Only owners can lock inspections")

    inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")

    if inspection.status != InspectionStatus.REVIEWED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot lock inspection with status '{inspection.status}'. Must be 'reviewed'."
        )

    inspection.status = InspectionStatus.LOCKED.value
    inspection.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(inspection)

    return {"success": True, "status": inspection.status, "id": str(inspection.id)}
