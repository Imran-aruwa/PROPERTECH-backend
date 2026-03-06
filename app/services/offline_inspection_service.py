"""
Offline Inspection Service
Handles batch sync from PWA devices, auto-maintenance job creation,
PDF report generation, and system template seeding.
"""
import logging
import uuid as uuid_module
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.inspection import (
    Inspection, InspectionItem, InspectionMedia,
    InspectionMeterReading, InspectionTemplate, InspectionStatus,
)
from app.models.offline_inspection import InspectionRoom, SyncQueue

logger = logging.getLogger(__name__)

# ============================================
# SYSTEM TEMPLATES (seeded per owner on first use)
# ============================================

SYSTEM_TEMPLATES = [
    {
        "name": "Move-In Inspection",
        "description": "Standard move-in checklist for tenant handover",
        "inspection_type": "move_in",
        "is_external": False,
        "scoring_enabled": True,
        "pass_threshold": 3.0,
        "rooms": ["Living Room", "Kitchen", "Bedroom 1", "Bathroom", "Exterior"],
        "default_items": [
            {"name": "Walls & Ceiling", "category": "structure", "required_photo": True},
            {"name": "Floor Condition", "category": "structure", "required_photo": True},
            {"name": "Windows & Locks", "category": "safety", "required_photo": False},
            {"name": "Plumbing Fixtures", "category": "plumbing", "required_photo": False},
            {"name": "Electrical Outlets", "category": "electrical", "required_photo": False},
            {"name": "Cleanliness", "category": "cleanliness", "required_photo": False},
        ],
    },
    {
        "name": "Move-Out Inspection",
        "description": "Standard move-out inspection for deposit assessment",
        "inspection_type": "move_out",
        "is_external": False,
        "scoring_enabled": True,
        "pass_threshold": 3.0,
        "rooms": ["Living Room", "Kitchen", "Bedroom 1", "Bathroom", "Exterior"],
        "default_items": [
            {"name": "Walls & Ceiling", "category": "structure", "required_photo": True},
            {"name": "Floor Condition", "category": "structure", "required_photo": True},
            {"name": "Windows & Locks", "category": "safety", "required_photo": True},
            {"name": "Plumbing Fixtures", "category": "plumbing", "required_photo": False},
            {"name": "Electrical Outlets", "category": "electrical", "required_photo": False},
            {"name": "Cleanliness", "category": "cleanliness", "required_photo": True},
        ],
    },
    {
        "name": "Routine Inspection",
        "description": "Quarterly routine property condition check",
        "inspection_type": "routine",
        "is_external": False,
        "scoring_enabled": True,
        "pass_threshold": 3.0,
        "rooms": ["Common Areas", "Unit Interior", "Exterior"],
        "default_items": [
            {"name": "General Condition", "category": "structure", "required_photo": False},
            {"name": "Plumbing", "category": "plumbing", "required_photo": False},
            {"name": "Electrical", "category": "electrical", "required_photo": False},
            {"name": "Security & Locks", "category": "safety", "required_photo": False},
            {"name": "Common Area Cleanliness", "category": "cleanliness", "required_photo": False},
        ],
    },
    {
        "name": "Meter Reading Inspection",
        "description": "Monthly water and electricity meter readings",
        "inspection_type": "meter",
        "is_external": False,
        "scoring_enabled": False,
        "pass_threshold": None,
        "rooms": [],
        "default_items": [
            {"name": "Water Meter", "category": "plumbing", "required_photo": True},
            {"name": "Electricity Meter", "category": "electrical", "required_photo": True},
        ],
    },
]


class InspectionService:
    def __init__(self, db: Session, owner_id):
        self.db = db
        self.owner_id = owner_id

    # ============================================
    # SYNC PROCESSING
    # ============================================

    def process_sync(self, device_id: str, payload: dict) -> dict:
        """
        Process an offline sync payload from a PWA device.
        Payload shape:
          {
            inspections: [{client_uuid, property_id, unit_id, ...}],
            rooms:       [{client_uuid, inspection_client_uuid, name, order_index}],
            items:       [{client_uuid, inspection_client_uuid, room_client_uuid, ...}],
            meter_readings: [{client_uuid, inspection_client_uuid, ...}],
            media_refs:  [{client_uuid, inspection_client_uuid, filename}],
          }
        Returns: {synced: int, skipped: int, errors: list[str]}
        """
        synced = 0
        skipped = 0
        errors = []

        # Map client_uuid → server id for cross-references
        inspection_uuid_map: dict[str, str] = {}
        room_uuid_map: dict[str, str] = {}

        # ---- 1. Inspections ----
        for insp_data in payload.get("inspections", []):
            try:
                client_uuid = insp_data.get("client_uuid")
                if not client_uuid:
                    errors.append("inspection missing client_uuid")
                    skipped += 1
                    continue

                existing = self.db.query(Inspection).filter(
                    Inspection.client_uuid == client_uuid
                ).first()
                if existing:
                    inspection_uuid_map[str(client_uuid)] = str(existing.id)
                    skipped += 1
                    continue

                insp = Inspection(
                    client_uuid=client_uuid,
                    property_id=insp_data["property_id"],
                    unit_id=insp_data["unit_id"],
                    performed_by_id=self.owner_id,
                    performed_by_role=insp_data.get("performed_by_role", "owner"),
                    inspection_type=insp_data.get("inspection_type", "routine"),
                    status=InspectionStatus.SUBMITTED.value,
                    inspection_date=self._parse_dt(insp_data.get("inspection_date")) or datetime.utcnow(),
                    gps_lat=insp_data.get("gps_lat"),
                    gps_lng=insp_data.get("gps_lng"),
                    device_id=device_id,
                    offline_created_at=self._parse_dt(insp_data.get("offline_created_at")),
                    notes=insp_data.get("notes"),
                    is_external=False,
                    template_id=insp_data.get("template_id"),
                )
                self.db.add(insp)
                self.db.flush()
                inspection_uuid_map[str(client_uuid)] = str(insp.id)
                synced += 1

            except Exception as exc:
                self.db.rollback()
                errors.append(f"inspection {insp_data.get('client_uuid','?')}: {exc}")
                skipped += 1

        self.db.flush()

        # ---- 2. Rooms ----
        for room_data in payload.get("rooms", []):
            try:
                client_uuid = room_data.get("client_uuid")
                insp_client_uuid = room_data.get("inspection_client_uuid")
                insp_server_id = inspection_uuid_map.get(str(insp_client_uuid))
                if not insp_server_id:
                    # Try DB lookup in case it was a pre-existing inspection
                    insp = self.db.query(Inspection).filter(
                        Inspection.client_uuid == insp_client_uuid
                    ).first()
                    if insp:
                        insp_server_id = str(insp.id)

                if not insp_server_id:
                    errors.append(f"room {client_uuid}: parent inspection not found")
                    skipped += 1
                    continue

                existing = self.db.query(InspectionRoom).filter(
                    InspectionRoom.client_uuid == client_uuid
                ).first()
                if existing:
                    room_uuid_map[str(client_uuid)] = str(existing.id)
                    skipped += 1
                    continue

                room = InspectionRoom(
                    client_uuid=client_uuid,
                    inspection_id=insp_server_id,
                    name=room_data.get("name", "Room"),
                    order_index=room_data.get("order_index", 0),
                    condition_summary=room_data.get("condition_summary"),
                    notes=room_data.get("notes"),
                )
                self.db.add(room)
                self.db.flush()
                room_uuid_map[str(client_uuid)] = str(room.id)
                synced += 1

            except Exception as exc:
                self.db.rollback()
                errors.append(f"room {room_data.get('client_uuid','?')}: {exc}")
                skipped += 1

        self.db.flush()

        # ---- 3. Items ----
        for item_data in payload.get("items", []):
            try:
                client_uuid = item_data.get("client_uuid")
                existing = self.db.query(InspectionItem).filter(
                    InspectionItem.client_uuid == client_uuid
                ).first()
                if existing:
                    skipped += 1
                    continue

                insp_client_uuid = item_data.get("inspection_client_uuid")
                insp_server_id = inspection_uuid_map.get(str(insp_client_uuid))
                if not insp_server_id:
                    insp = self.db.query(Inspection).filter(
                        Inspection.client_uuid == insp_client_uuid
                    ).first()
                    if insp:
                        insp_server_id = str(insp.id)

                if not insp_server_id:
                    errors.append(f"item {client_uuid}: parent inspection not found")
                    skipped += 1
                    continue

                room_client_uuid = item_data.get("room_client_uuid")
                room_server_id = None
                if room_client_uuid:
                    room_server_id = room_uuid_map.get(str(room_client_uuid))
                    if not room_server_id:
                        room = self.db.query(InspectionRoom).filter(
                            InspectionRoom.client_uuid == room_client_uuid
                        ).first()
                        if room:
                            room_server_id = str(room.id)

                item = InspectionItem(
                    client_uuid=client_uuid,
                    inspection_id=insp_server_id,
                    name=item_data.get("name", "Item"),
                    category=item_data.get("category", "structure"),
                    condition=item_data.get("condition", "good"),
                    comment=item_data.get("comment"),
                    score=item_data.get("score"),
                    severity=item_data.get("severity"),
                    pass_fail=item_data.get("pass_fail"),
                    requires_followup=item_data.get("requires_followup", False),
                    photo_required=item_data.get("photo_required", False),
                )
                # Set room_id if column exists (added via ALTER TABLE)
                if room_server_id:
                    try:
                        item.room_id = room_server_id
                    except AttributeError:
                        pass  # column not yet migrated
                # Set requires_maintenance if column exists
                try:
                    item.requires_maintenance = item_data.get("requires_maintenance", False)
                    item.maintenance_priority = item_data.get("maintenance_priority", "normal")
                except AttributeError:
                    pass

                self.db.add(item)
                synced += 1

            except Exception as exc:
                self.db.rollback()
                errors.append(f"item {item_data.get('client_uuid','?')}: {exc}")
                skipped += 1

        self.db.flush()

        # ---- 4. Meter readings ----
        for mr_data in payload.get("meter_readings", []):
            try:
                client_uuid = mr_data.get("client_uuid")
                existing = self.db.query(InspectionMeterReading).filter(
                    InspectionMeterReading.client_uuid == client_uuid
                ).first()
                if existing:
                    skipped += 1
                    continue

                insp_client_uuid = mr_data.get("inspection_client_uuid")
                insp_server_id = inspection_uuid_map.get(str(insp_client_uuid))
                if not insp_server_id:
                    insp = self.db.query(Inspection).filter(
                        Inspection.client_uuid == insp_client_uuid
                    ).first()
                    if insp:
                        insp_server_id = str(insp.id)

                mr = InspectionMeterReading(
                    client_uuid=client_uuid,
                    inspection_id=insp_server_id,
                    unit_id=mr_data["unit_id"],
                    meter_type=mr_data["meter_type"],
                    previous_reading=mr_data.get("previous_reading", 0),
                    current_reading=mr_data["current_reading"],
                    reading_date=self._parse_dt(mr_data.get("reading_date")) or datetime.utcnow(),
                )
                self.db.add(mr)
                synced += 1

            except Exception as exc:
                self.db.rollback()
                errors.append(f"meter_reading {mr_data.get('client_uuid','?')}: {exc}")
                skipped += 1

        # ---- 5. Recompute scores for synced inspections ----
        for server_id in inspection_uuid_map.values():
            try:
                self._recompute_score(server_id)
            except Exception as exc:
                logger.warning("score recompute failed for %s: %s", server_id, exc)

        self.db.commit()

        return {"synced": synced, "skipped": skipped, "errors": errors}

    def _recompute_score(self, inspection_id: str):
        """Recompute overall_score and pass_fail for an inspection."""
        items = self.db.query(InspectionItem).filter(
            InspectionItem.inspection_id == inspection_id,
            InspectionItem.score.isnot(None)
        ).all()
        if not items:
            return
        avg = sum(i.score for i in items) / len(items)
        insp = self.db.query(Inspection).filter(Inspection.id == inspection_id).first()
        if insp:
            insp.overall_score = round(avg, 2)
            insp.pass_fail = "pass" if avg >= 3.0 else "fail"

    # ============================================
    # AUTO MAINTENANCE JOB CREATION
    # ============================================

    def auto_create_maintenance_jobs(self, inspection_id: str) -> list[dict]:
        """
        Create MaintenanceRequest records for items flagged as requiring maintenance.
        Returns list of created job summaries.
        """
        created = []
        try:
            from app.models.maintenance import MaintenanceRequest
        except ImportError:
            logger.warning("MaintenanceRequest model not available")
            return created

        insp = self.db.query(Inspection).filter(Inspection.id == inspection_id).first()
        if not insp:
            return created

        # Check items with requires_maintenance=True (column may not exist yet)
        try:
            flagged_items = self.db.execute(
                text(
                    "SELECT id, name, category, severity, comment "
                    "FROM inspection_items "
                    "WHERE inspection_id = :insp_id "
                    "AND requires_maintenance = TRUE"
                ),
                {"insp_id": str(inspection_id)}
            ).fetchall()
        except Exception:
            # Column doesn't exist yet — fall back to requires_followup
            flagged_items = self.db.query(InspectionItem).filter(
                InspectionItem.inspection_id == inspection_id,
                InspectionItem.requires_followup == True,
                InspectionItem.severity.in_(["high", "critical"])
            ).all()
            flagged_items = [
                type("Row", (), {
                    "id": str(i.id), "name": i.name,
                    "category": i.category, "severity": i.severity,
                    "comment": i.comment
                })()
                for i in flagged_items
            ]

        for row in flagged_items:
            # Avoid duplicate jobs: check automation_actions_log or just skip if one exists
            try:
                description = (
                    f"[Auto from Inspection #{str(inspection_id)[:8]}] "
                    f"{row.name}: {row.comment or 'No details'}"
                )
                priority_map = {
                    "critical": "urgent", "high": "high",
                    "medium": "normal", "low": "low"
                }
                priority = priority_map.get(row.severity or "medium", "normal")

                req = MaintenanceRequest(
                    property_id=insp.property_id,
                    unit_id=insp.unit_id,
                    reported_by_id=insp.performed_by_id,
                    category=row.category,
                    description=description,
                    priority=priority,
                    status="open",
                )
                self.db.add(req)
                self.db.flush()

                # Log to automation_actions_log
                try:
                    self.db.execute(text(
                        "INSERT INTO automation_actions_log "
                        "(id, owner_id, action_type, entity_type, entity_id, details, created_at) "
                        "VALUES (:id, :owner_id, :action_type, :entity_type, :entity_id, :details, NOW())"
                    ), {
                        "id": str(uuid_module.uuid4()),
                        "owner_id": str(self.owner_id),
                        "action_type": "inspection_auto_maintenance",
                        "entity_type": "maintenance_request",
                        "entity_id": str(req.id),
                        "details": f"Auto-created from inspection {inspection_id}, item: {row.name}",
                    })
                except Exception:
                    pass

                created.append({"item": row.name, "priority": priority, "request_id": str(req.id)})
            except Exception as exc:
                logger.warning("Failed to create job for item %s: %s", row.name, exc)

        if created:
            self.db.commit()
            logger.info("Auto-created %d maintenance jobs from inspection %s", len(created), inspection_id)

        return created

    # ============================================
    # REPORT GENERATION
    # ============================================

    def generate_report(self, inspection_id: str) -> Optional[dict]:
        """
        Generate a structured inspection report dict suitable for PDF rendering.
        Returns None if inspection not found.
        """
        from sqlalchemy.orm import joinedload as jl

        insp = (
            self.db.query(Inspection)
            .options(
                jl(Inspection.property),
                jl(Inspection.unit),
                jl(Inspection.performed_by),
                jl(Inspection.items),
                jl(Inspection.media),
                jl(Inspection.meter_readings),
                jl(Inspection.signatures),
            )
            .filter(Inspection.id == inspection_id)
            .first()
        )
        if not insp:
            return None

        # Group items by room
        rooms_raw = self.db.query(InspectionRoom).filter(
            InspectionRoom.inspection_id == inspection_id
        ).order_by(InspectionRoom.order_index).all()

        rooms_map: dict[str, dict] = {}
        for r in rooms_raw:
            rooms_map[str(r.id)] = {
                "id": str(r.id),
                "name": r.name,
                "condition_summary": r.condition_summary,
                "items": [],
            }

        unassigned_items = []
        for item in insp.items:
            item_dict = {
                "id": str(item.id),
                "name": item.name,
                "category": item.category,
                "condition": item.condition,
                "score": item.score,
                "severity": item.severity,
                "pass_fail": item.pass_fail,
                "requires_followup": item.requires_followup,
                "comment": item.comment,
                "photos": [m.file_url for m in insp.media if True],  # simplified
            }
            room_id = getattr(item, "room_id", None)
            if room_id and str(room_id) in rooms_map:
                rooms_map[str(room_id)]["items"].append(item_dict)
            else:
                unassigned_items.append(item_dict)

        # Score summary
        scored = [i for i in insp.items if i.score is not None]
        category_scores: dict[str, list] = {}
        for item in scored:
            category_scores.setdefault(item.category, []).append(item.score)
        category_summary = {
            cat: round(sum(scores) / len(scores), 2)
            for cat, scores in category_scores.items()
        }

        # Items needing action
        action_items = [
            {"name": i.name, "severity": i.severity, "comment": i.comment}
            for i in insp.items
            if i.severity in ("high", "critical") or i.requires_followup
        ]

        report = {
            "inspection_id": str(insp.id),
            "generated_at": datetime.utcnow().isoformat(),
            "property": {
                "name": insp.property.name if insp.property else None,
                "address": insp.property.address if insp.property else None,
            },
            "unit": {
                "number": insp.unit.unit_number if insp.unit else None,
            },
            "inspector": {
                "name": insp.performed_by.full_name if insp.performed_by else insp.inspector_name,
                "role": insp.performed_by_role,
                "external": insp.is_external,
                "company": insp.inspector_company,
                "credentials": insp.inspector_credentials,
            },
            "inspection_type": insp.inspection_type,
            "inspection_date": insp.inspection_date.isoformat() if insp.inspection_date else None,
            "status": insp.status,
            "overall_score": insp.overall_score,
            "pass_fail": insp.pass_fail,
            "notes": insp.notes,
            "rooms": list(rooms_map.values()),
            "unassigned_items": unassigned_items,
            "action_items": action_items,
            "category_summary": category_summary,
            "meter_readings": [
                {
                    "meter_type": mr.meter_type,
                    "previous": float(mr.previous_reading),
                    "current": float(mr.current_reading),
                    "consumption": float(mr.current_reading - mr.previous_reading),
                    "date": mr.reading_date.isoformat() if mr.reading_date else None,
                }
                for mr in insp.meter_readings
            ],
            "signatures": [
                {
                    "signer_name": sig.signer_name,
                    "signer_role": sig.signer_role,
                    "signed_at": sig.signed_at.isoformat() if sig.signed_at else None,
                    "signature_type": sig.signature_type,
                }
                for sig in insp.signatures
            ],
            "media_count": len(insp.media),
            "items_total": len(insp.items),
            "items_passed": sum(1 for i in insp.items if i.pass_fail == "pass"),
            "items_failed": sum(1 for i in insp.items if i.pass_fail == "fail"),
            "items_flagged": len(action_items),
        }
        return report

    # ============================================
    # TEMPLATE SEEDING
    # ============================================

    def seed_system_templates(self):
        """
        Seed default system inspection templates for this owner.
        Idempotent — skips templates that already exist by name+owner.
        """
        for tpl_data in SYSTEM_TEMPLATES:
            existing = self.db.query(InspectionTemplate).filter(
                InspectionTemplate.owner_id == self.owner_id,
                InspectionTemplate.name == tpl_data["name"],
            ).first()
            if existing:
                continue

            tpl = InspectionTemplate(
                owner_id=self.owner_id,
                name=tpl_data["name"],
                description=tpl_data["description"],
                inspection_type=tpl_data["inspection_type"],
                is_external=tpl_data["is_external"],
                scoring_enabled=tpl_data["scoring_enabled"],
                pass_threshold=tpl_data["pass_threshold"],
                categories=list({i["category"] for i in tpl_data["default_items"]}),
                default_items=tpl_data["default_items"],
                is_active=True,
            )
            self.db.add(tpl)

        try:
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            logger.warning("seed_system_templates failed: %s", exc)

    def get_templates(self) -> list[dict]:
        """Get all active templates for this owner (including system defaults)."""
        templates = self.db.query(InspectionTemplate).filter(
            InspectionTemplate.owner_id == self.owner_id,
            InspectionTemplate.is_active == True,
        ).order_by(InspectionTemplate.created_at).all()

        return [
            {
                "id": str(t.id),
                "name": t.name,
                "description": t.description,
                "inspection_type": t.inspection_type,
                "is_external": t.is_external,
                "scoring_enabled": t.scoring_enabled,
                "pass_threshold": t.pass_threshold,
                "categories": t.categories or [],
                "default_items": t.default_items or [],
                "created_at": t.created_at.isoformat(),
            }
            for t in templates
        ]

    # ============================================
    # HELPERS
    # ============================================

    @staticmethod
    def _parse_dt(value) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None
