"""
Inspection Routes - Universal Inspection Engine
Supports internal + external inspections, templates, scoring, signatures,
audit trails, and subscription gating.
"""
import base64
import logging
import math
import os
import uuid as uuid_module
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import and_, desc
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserRole
from app.models.property import Property, Unit
from app.models.inspection import (
    Inspection, InspectionItem, InspectionMedia,
    InspectionMeterReading, InspectionStatus, InspectionTemplate,
    InspectionSignature
)
from app.schemas.inspection import (
    InspectionCreateRequest, InspectionMediaUpload,
    InspectionReviewRequest, InspectionListResponse,
    InspectionDetailResponse, InspectionPaginatedResponse,
    InspectionItemResponse, InspectionMediaResponse,
    InspectionMeterReadingResponse, InspectionSignatureResponse,
    InspectionTemplateCreate, InspectionTemplateUpdate,
    InspectionTemplateResponse, InspectionSignatureCreate
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["inspections"])

# Roles that map to performed_by_role values
INSPECTION_ROLES = {
    UserRole.OWNER: "owner",
    UserRole.AGENT: "agent",
    UserRole.CARETAKER: "caretaker",
}

# External inspection types require premium
EXTERNAL_TYPES = {"pre_purchase", "insurance", "valuation"}


def get_user_accessible_property_ids(db: Session, user: User) -> Optional[list]:
    """Get property IDs accessible to user based on role."""
    if user.role == UserRole.OWNER:
        props = db.query(Property.id).filter(Property.user_id == user.id).all()
        return [p.id for p in props]
    elif user.role == UserRole.AGENT:
        props = db.query(Property.id).all()
        return [p.id for p in props]
    return []


def build_inspection_list_response(inspection: Inspection) -> dict:
    """Build list response dict with display fields."""
    return {
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
        "is_external": inspection.is_external,
        "overall_score": inspection.overall_score,
        "pass_fail": inspection.pass_fail,
        "inspector_name": inspection.inspector_name,
        "created_at": inspection.created_at,
        "updated_at": inspection.updated_at,
        "property_name": inspection.property.name if inspection.property else None,
        "unit_number": inspection.unit.unit_number if inspection.unit else None,
        "performed_by_name": inspection.performed_by.full_name if inspection.performed_by else None,
    }


def compute_inspection_score(items: list) -> tuple:
    """Compute overall score and pass/fail from scored items."""
    scored = [i for i in items if i.score is not None]
    if not scored:
        return None, None
    avg = sum(i.score for i in scored) / len(scored)
    return round(avg, 2), "pass" if avg >= 3.0 else "fail"


# ============================================
# 1. POST /api/inspections/ - Create inspection
# ============================================

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_inspection(
    request_data: InspectionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new inspection with items and meter readings (offline-sync)."""
    if current_user.role not in INSPECTION_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners, agents, and caretakers can create inspections"
        )

    # Check for duplicate client_uuid
    existing = db.query(Inspection).filter(
        Inspection.client_uuid == request_data.client_uuid
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"detail": "duplicate", "inspection_id": str(existing.id)}
        )

    # Verify property and unit exist
    prop = db.query(Property).filter(Property.id == request_data.inspection.property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    unit = db.query(Unit).filter(Unit.id == request_data.inspection.unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    # Create inspection
    inspection = Inspection(
        client_uuid=request_data.client_uuid,
        property_id=request_data.inspection.property_id,
        unit_id=request_data.inspection.unit_id,
        performed_by_id=current_user.id,
        performed_by_role=INSPECTION_ROLES[current_user.role],
        inspection_type=request_data.inspection.inspection_type,
        status=InspectionStatus.SUBMITTED.value,
        inspection_date=request_data.inspection.inspection_date,
        gps_lat=request_data.inspection.gps_lat,
        gps_lng=request_data.inspection.gps_lng,
        device_id=request_data.inspection.device_id,
        offline_created_at=request_data.inspection.offline_created_at,
        notes=request_data.inspection.notes,
        is_external=request_data.inspection.is_external or False,
        template_id=request_data.inspection.template_id,
        inspector_name=request_data.inspection.inspector_name,
        inspector_credentials=request_data.inspection.inspector_credentials,
        inspector_company=request_data.inspection.inspector_company,
    )
    db.add(inspection)
    db.flush()

    # Create inspection items
    for item_data in request_data.items:
        item = InspectionItem(
            inspection_id=inspection.id,
            client_uuid=item_data.client_uuid,
            name=item_data.name,
            category=item_data.category,
            condition=item_data.condition,
            comment=item_data.comment,
            score=item_data.score,
            severity=item_data.severity,
            pass_fail=item_data.pass_fail,
            requires_followup=item_data.requires_followup or False,
            photo_required=item_data.photo_required or False,
        )
        db.add(item)

    # Create meter readings
    for reading_data in request_data.meter_readings:
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

    # Compute score from items
    if request_data.items:
        db.expire(inspection)
        score, pf = compute_inspection_score(inspection.items)
        if score is not None:
            inspection.overall_score = score
            inspection.pass_fail = pf
            db.commit()
            db.refresh(inspection)

    db.expire(inspection)

    response = build_inspection_list_response(inspection)
    response["gps_lat"] = inspection.gps_lat
    response["gps_lng"] = inspection.gps_lng
    response["device_id"] = inspection.device_id
    response["offline_created_at"] = inspection.offline_created_at
    response["template_id"] = inspection.template_id
    response["inspector_credentials"] = inspection.inspector_credentials
    response["inspector_company"] = inspection.inspector_company
    response["report_url"] = inspection.report_url
    response["items"] = [
        InspectionItemResponse.model_validate(i).model_dump() for i in inspection.items
    ]
    response["meter_readings"] = [
        InspectionMeterReadingResponse.model_validate(r).model_dump() for r in inspection.meter_readings
    ]
    response["media"] = []
    response["signatures"] = []

    return response


# ============================================
# 2. POST /api/inspections/{id}/media/ - Upload media
# ============================================

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

    if inspection.performed_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if inspection.status == InspectionStatus.LOCKED.value:
        raise HTTPException(status_code=400, detail="Cannot modify locked inspection")

    # Check duplicate
    existing = db.query(InspectionMedia).filter(
        InspectionMedia.client_uuid == media_data.client_uuid
    ).first()
    if existing:
        return InspectionMediaResponse.model_validate(existing).model_dump()

    # Decode base64
    try:
        file_content = media_data.file_data
        if ";base64," in file_content:
            file_content = file_content.split(";base64,")[1]
        file_bytes = base64.b64decode(file_content)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 file data")

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


# ============================================
# 3. GET /api/inspections/ - List inspections
# ============================================

@router.get("/")
def list_inspections(
    property_id: Optional[uuid_module.UUID] = None,
    status_filter: Optional[str] = None,
    type_filter: Optional[str] = None,
    is_external: Optional[bool] = None,
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
        query = query.filter(Inspection.performed_by_id == current_user.id)
    elif current_user.role == UserRole.OWNER:
        owner_property_ids = get_user_accessible_property_ids(db, current_user)
        query = query.filter(Inspection.property_id.in_(owner_property_ids))
    elif current_user.role == UserRole.AGENT:
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

    # Apply filters
    if property_id:
        query = query.filter(Inspection.property_id == property_id)
    if status_filter:
        query = query.filter(Inspection.status == status_filter)
    if type_filter:
        query = query.filter(Inspection.inspection_type == type_filter)
    if is_external is not None:
        query = query.filter(Inspection.is_external == is_external)

    total = query.count()
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


# ============================================
# 4. GET /api/inspections/{id}/ - Get detail
# ============================================

@router.get("/{inspection_id}/")
def get_inspection_detail(
    inspection_id: uuid_module.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get full inspection detail with items, media, meter readings, signatures."""
    inspection = db.query(Inspection).options(
        joinedload(Inspection.property),
        joinedload(Inspection.unit),
        joinedload(Inspection.performed_by),
        joinedload(Inspection.items),
        joinedload(Inspection.media),
        joinedload(Inspection.meter_readings),
        joinedload(Inspection.signatures),
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
    response["template_id"] = inspection.template_id
    response["inspector_credentials"] = inspection.inspector_credentials
    response["inspector_company"] = inspection.inspector_company
    response["report_url"] = inspection.report_url
    response["items"] = [
        InspectionItemResponse.model_validate(i).model_dump() for i in inspection.items
    ]
    response["media"] = [
        InspectionMediaResponse.model_validate(m).model_dump() for m in inspection.media
    ]
    response["meter_readings"] = [
        InspectionMeterReadingResponse.model_validate(r).model_dump() for r in inspection.meter_readings
    ]
    response["signatures"] = [
        InspectionSignatureResponse.model_validate(s).model_dump() for s in inspection.signatures
    ]

    return response


# ============================================
# 5. PATCH /api/inspections/{id}/review/
# ============================================

@router.patch("/{inspection_id}/review/")
def review_inspection(
    inspection_id: uuid_module.UUID,
    review_data: InspectionReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark an inspection as reviewed."""
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
        existing_notes = inspection.notes or ""
        inspection.notes = f"{existing_notes}\n[Review] {review_data.notes}".strip()
    inspection.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(inspection)

    return {"success": True, "status": inspection.status, "id": str(inspection.id)}


# ============================================
# 6. PATCH /api/inspections/{id}/lock/
# ============================================

@router.patch("/{inspection_id}/lock/")
def lock_inspection(
    inspection_id: uuid_module.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lock an inspection permanently."""
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


# ============================================
# 7. POST /api/inspections/{id}/sign/ - Digital signature
# ============================================

@router.post("/{inspection_id}/sign/", status_code=status.HTTP_201_CREATED)
def sign_inspection(
    inspection_id: uuid_module.UUID,
    sig_data: InspectionSignatureCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a digital signature to an inspection report."""
    inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")

    # Get client IP for audit trail
    client_ip = request.client.host if request.client else None

    signature = InspectionSignature(
        inspection_id=inspection_id,
        signer_id=current_user.id,
        signer_name=sig_data.signer_name,
        signer_role=sig_data.signer_role,
        signature_type=sig_data.signature_type,
        signature_data=sig_data.signature_data,
        signed_at=datetime.utcnow(),
        ip_address=sig_data.ip_address or client_ip,
        device_fingerprint=sig_data.device_fingerprint,
        gps_lat=sig_data.gps_lat,
        gps_lng=sig_data.gps_lng,
    )
    db.add(signature)
    db.commit()
    db.refresh(signature)

    return InspectionSignatureResponse.model_validate(signature).model_dump()


# ============================================
# 8. GET /api/inspections/{id}/signatures/
# ============================================

@router.get("/{inspection_id}/signatures/")
def get_inspection_signatures(
    inspection_id: uuid_module.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all signatures for an inspection."""
    inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")

    signatures = db.query(InspectionSignature).filter(
        InspectionSignature.inspection_id == inspection_id
    ).order_by(InspectionSignature.signed_at).all()

    return [InspectionSignatureResponse.model_validate(s).model_dump() for s in signatures]


# ============================================
# TEMPLATE CRUD
# ============================================

@router.post("/templates/", status_code=status.HTTP_201_CREATED)
def create_template(
    template_data: InspectionTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an inspection template."""
    if current_user.role not in [UserRole.OWNER, UserRole.AGENT, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Only owners and agents can create templates")

    template = InspectionTemplate(
        owner_id=current_user.id,
        name=template_data.name,
        description=template_data.description,
        inspection_type=template_data.inspection_type,
        is_external=template_data.is_external or False,
        categories=template_data.categories,
        default_items=template_data.default_items,
        scoring_enabled=template_data.scoring_enabled if template_data.scoring_enabled is not None else True,
        pass_threshold=template_data.pass_threshold,
    )
    db.add(template)
    db.commit()
    db.refresh(template)

    return InspectionTemplateResponse.model_validate(template).model_dump()


@router.get("/templates/")
def list_templates(
    inspection_type: Optional[str] = None,
    is_external: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List inspection templates for the current user."""
    query = db.query(InspectionTemplate).filter(
        InspectionTemplate.owner_id == current_user.id,
        InspectionTemplate.is_active == True,
    )
    if inspection_type:
        query = query.filter(InspectionTemplate.inspection_type == inspection_type)
    if is_external is not None:
        query = query.filter(InspectionTemplate.is_external == is_external)

    templates = query.order_by(desc(InspectionTemplate.created_at)).all()
    return [InspectionTemplateResponse.model_validate(t).model_dump() for t in templates]


@router.get("/templates/{template_id}/")
def get_template(
    template_id: uuid_module.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single inspection template."""
    template = db.query(InspectionTemplate).filter(
        InspectionTemplate.id == template_id
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return InspectionTemplateResponse.model_validate(template).model_dump()


@router.put("/templates/{template_id}/")
def update_template(
    template_id: uuid_module.UUID,
    template_data: InspectionTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an inspection template."""
    template = db.query(InspectionTemplate).filter(
        InspectionTemplate.id == template_id,
        InspectionTemplate.owner_id == current_user.id,
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    update_fields = template_data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(template, field, value)
    template.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(template)

    return InspectionTemplateResponse.model_validate(template).model_dump()


@router.delete("/templates/{template_id}/")
def delete_template(
    template_id: uuid_module.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft-delete an inspection template."""
    template = db.query(InspectionTemplate).filter(
        InspectionTemplate.id == template_id,
        InspectionTemplate.owner_id == current_user.id,
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    template.is_active = False
    template.updated_at = datetime.utcnow()
    db.commit()

    return {"success": True, "detail": "Template deleted"}
