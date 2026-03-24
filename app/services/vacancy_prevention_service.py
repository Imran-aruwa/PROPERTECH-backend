"""
Vacancy Prevention Service
Handles lead capture, renewal campaigns, listing syndication,
and pipeline analytics to reduce vacancy duration.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.vacancy_prevention import (
    VacancyPreventionListing as ListingSyndication,  # renamed to avoid table conflict
    RenewalCampaign,
    VacancyLead,
    VacancyLeadActivity,
    VacancyPreventionSettings,
)
from app.models.property import Property, Unit
from app.models.lease import Lease, LeaseStatus
from app.models.user import User

logger = logging.getLogger(__name__)

# ── SMS helper (re-use Africa's Talking pattern from action_library) ──────────

def _send_sms(phone: str, message: str) -> None:
    """Best-effort SMS — logs in dev mode if AT key missing."""
    from app.core.config import settings
    at_key = getattr(settings, "AT_API_KEY", None)
    at_user = getattr(settings, "AT_USERNAME", "sandbox")
    sender = getattr(settings, "AT_SENDER_ID", None)

    if not phone:
        return
    if not at_key:
        logger.info(f"[vacancy] DEV SMS to {phone}: {message[:120]}")
        return
    try:
        import africastalking
        africastalking.initialize(at_user, at_key)
        kwargs = {"message": message, "recipients": [phone]}
        if sender:
            kwargs["sender_id"] = sender
        africastalking.SMS.send(**kwargs)
        logger.info(f"[vacancy] SMS sent to {phone}")
    except Exception as exc:
        logger.warning(f"[vacancy] SMS failed to {phone}: {exc}")


class VacancyPreventionService:
    def __init__(self, db: Session, owner_id: uuid.UUID) -> None:
        self.db = db
        self.owner_id = owner_id

    # ── Settings ──────────────────────────────────────────────────────────────

    def get_or_create_settings(self) -> VacancyPreventionSettings:
        s = (
            self.db.query(VacancyPreventionSettings)
            .filter(VacancyPreventionSettings.owner_id == self.owner_id)
            .first()
        )
        if not s:
            s = VacancyPreventionSettings(
                id=uuid.uuid4(),
                owner_id=self.owner_id,
                renewal_campaign_days=[60, 30, 7],
            )
            self.db.add(s)
            self.db.commit()
            self.db.refresh(s)
        return s

    # ── handle_unit_vacated ───────────────────────────────────────────────────

    def handle_unit_vacated(self, unit_id: str) -> Optional[ListingSyndication]:
        """
        Called on unit_vacated event.
        Idempotent — checks for existing active syndication before creating.
        """
        try:
            unit_uuid = uuid.UUID(unit_id)
        except ValueError:
            logger.warning(f"[vacancy] handle_unit_vacated: invalid unit_id {unit_id}")
            return None

        # Idempotency — skip if active syndication already exists
        existing = (
            self.db.query(ListingSyndication)
            .filter(
                ListingSyndication.unit_id == unit_uuid,
                ListingSyndication.owner_id == self.owner_id,
                ListingSyndication.status.in_(["draft", "active"]),
            )
            .first()
        )
        if existing:
            logger.info(f"[vacancy] Syndication already exists for unit {unit_id} — skipping")
            return existing

        unit = self.db.query(Unit).filter(Unit.id == unit_uuid).first()
        if not unit:
            return None
        prop = (
            self.db.query(Property).filter(Property.id == unit.property_id).first()
            if unit.property_id else None
        )

        settings = self.get_or_create_settings()
        unit_type = _infer_unit_type(unit.bedrooms)
        initial_status = "active" if settings.auto_create_listing else "draft"

        syndication = ListingSyndication(
            id=uuid.uuid4(),
            owner_id=self.owner_id,
            unit_id=unit_uuid,
            title=f"{unit_type} available — {prop.name if prop else 'Property'}",
            description=(
                unit.description or
                f"Available {unit_type} unit in {prop.name if prop else 'our property'}. "
                "Contact us to arrange a viewing."
            ),
            monthly_rent=unit.monthly_rent or 0,
            bedrooms=unit.bedrooms,
            bathrooms=int(unit.bathrooms) if unit.bathrooms else None,
            unit_type=unit_type,
            amenities=[],
            photos=[],
            location_area=prop.area if prop else None,
            status=initial_status,
            view_count=0,
            enquiry_count=0,
            platforms=[],
            published_at=datetime.now(timezone.utc) if initial_status == "active" else None,
        )
        self.db.add(syndication)

        # Match any existing leads for this unit type
        self._match_leads_to_unit(unit_uuid, unit_type, float(unit.monthly_rent or 0), settings)

        self.db.commit()
        self.db.refresh(syndication)
        logger.info(
            f"[vacancy] Created ListingSyndication {syndication.id} for unit {unit_id} "
            f"status={initial_status}"
        )
        return syndication

    def _match_leads_to_unit(
        self,
        unit_uuid: uuid.UUID,
        unit_type: str,
        rent: float,
        settings: VacancyPreventionSettings,
    ) -> None:
        """Assign matching leads to the newly vacated unit and set follow-up."""
        now = datetime.now(timezone.utc)
        follow_up_delta = timedelta(hours=settings.lead_follow_up_hours or 24)

        leads = (
            self.db.query(VacancyLead)
            .filter(
                VacancyLead.owner_id == self.owner_id,
                VacancyLead.status.in_(["new", "contacted", "viewing_scheduled"]),
                VacancyLead.unit_id == None,  # noqa: E711
            )
            .all()
        )
        matched = 0
        for lead in leads:
            type_match = (
                not lead.preferred_unit_type
                or lead.preferred_unit_type == unit_type
            )
            budget_ok = True
            if lead.budget_max and rent > float(lead.budget_max):
                budget_ok = False
            if lead.budget_min and rent < float(lead.budget_min):
                budget_ok = False

            if type_match and budget_ok:
                lead.unit_id = unit_uuid
                lead.follow_up_due_at = now + follow_up_delta
                matched += 1

        if matched:
            logger.info(f"[vacancy] Matched {matched} leads to unit {unit_uuid}")

    # ── handle_lease_expiring ─────────────────────────────────────────────────

    def handle_lease_expiring(self, lease_id: str, days_before: int) -> Optional[RenewalCampaign]:
        """
        Called on lease_expiring_60d / _30d / _7d events.
        Idempotent — one campaign per (lease_id, trigger_days_before_expiry).
        """
        try:
            lease_uuid = uuid.UUID(lease_id)
        except ValueError:
            logger.warning(f"[vacancy] handle_lease_expiring: invalid lease_id {lease_id}")
            return None

        # Idempotency check
        existing = (
            self.db.query(RenewalCampaign)
            .filter(
                RenewalCampaign.lease_id == lease_uuid,
                RenewalCampaign.trigger_days_before_expiry == days_before,
                RenewalCampaign.owner_id == self.owner_id,
            )
            .first()
        )
        if existing:
            logger.info(
                f"[vacancy] Campaign already exists for lease {lease_id} "
                f"at {days_before}d — skipping"
            )
            return existing

        lease = self.db.query(Lease).filter(Lease.id == lease_uuid).first()
        if not lease or not lease.unit_id:
            return None

        # Check for earlier unresponded campaigns (for 7d escalation logic)
        earlier_no_response = (
            self.db.query(RenewalCampaign)
            .filter(
                RenewalCampaign.lease_id == lease_uuid,
                RenewalCampaign.tenant_response == None,  # noqa: E711
                RenewalCampaign.owner_id == self.owner_id,
            )
            .first()
        )
        offer_type = "standard"
        incentive = None
        if days_before == 7 and earlier_no_response:
            offer_type = "incentive"
            incentive = "Renew within 7 days to lock in your current rate."

        campaign = RenewalCampaign(
            id=uuid.uuid4(),
            owner_id=self.owner_id,
            lease_id=lease_uuid,
            tenant_id=lease.tenant_id,
            unit_id=lease.unit_id,
            campaign_status="active",
            trigger_days_before_expiry=days_before,
            offer_type=offer_type,
            incentive_description=incentive,
            proposed_rent=lease.rent_amount,
            current_rent=lease.rent_amount,
        )
        self.db.add(campaign)
        self.db.commit()
        self.db.refresh(campaign)

        # Send renewal SMS
        self._send_renewal_sms(lease, days_before, campaign)

        logger.info(
            f"[vacancy] Created RenewalCampaign {campaign.id} for lease {lease_id} "
            f"at {days_before}d trigger"
        )
        return campaign

    def _send_renewal_sms(
        self, lease: Lease, days_before: int, campaign: RenewalCampaign
    ) -> None:
        phone = lease.tenant_phone
        if not phone:
            return

        unit_label = str(lease.unit_id)[:8] if lease.unit_id else "your unit"
        # Try to get proper unit number
        if lease.unit_id:
            unit = self.db.query(Unit).filter(Unit.id == lease.unit_id).first()
            if unit:
                unit_label = f"Unit {unit.unit_number}"

        owner = self.db.query(User).filter(User.id == self.owner_id).first()
        owner_phone = owner.phone if owner and hasattr(owner, "phone") else ""
        tenant_name = lease.tenant_name or "Tenant"
        end_date = lease.end_date.strftime("%d %b %Y") if lease.end_date else "soon"
        rent = f"{float(lease.rent_amount or 0):,.0f}"

        if days_before == 60:
            msg = (
                f"Hi {tenant_name}, your lease for {unit_label} expires on {end_date}. "
                f"We'd love to have you stay! Reply YES to renew at KES {rent}/month "
                f"or call {owner_phone} to discuss. PROPERTECH"
            )
        elif days_before == 30:
            msg = (
                f"Hi {tenant_name}, 30 days until your lease ends for {unit_label}. "
                f"Have you decided to renew? Reply YES to lock in KES {rent}/month. "
                f"Act now to keep your home. PROPERTECH"
            )
        else:  # 7
            msg = (
                f"URGENT: Hi {tenant_name}, your lease for {unit_label} expires in 7 days. "
                f"Please contact us immediately to avoid disruption. "
                f"Call {owner_phone}. PROPERTECH"
            )

        _send_sms(phone, msg)
        campaign.last_follow_up_at = datetime.now(timezone.utc)

    # ── create_lead ───────────────────────────────────────────────────────────

    def create_lead(self, data: Dict[str, Any]) -> VacancyLead:
        settings = self.get_or_create_settings()
        now = datetime.now(timezone.utc)
        follow_up_at = now + timedelta(hours=settings.lead_follow_up_hours or 24)

        unit_uuid = None
        if data.get("unit_id"):
            try:
                unit_uuid = uuid.UUID(data["unit_id"])
            except ValueError:
                pass

        property_uuid = None
        if data.get("property_id"):
            try:
                property_uuid = uuid.UUID(data["property_id"])
            except ValueError:
                pass

        lead = VacancyLead(
            id=uuid.uuid4(),
            owner_id=self.owner_id,
            property_id=property_uuid,
            unit_id=unit_uuid,
            lead_name=data["lead_name"],
            lead_phone=data["lead_phone"],
            lead_email=data.get("lead_email"),
            source=data.get("source", "manual"),
            status="new",
            preferred_unit_type=data.get("preferred_unit_type"),
            preferred_move_in=data.get("preferred_move_in"),
            budget_min=data.get("budget_min"),
            budget_max=data.get("budget_max"),
            notes=data.get("notes"),
            follow_up_due_at=follow_up_at,
        )
        self.db.add(lead)
        self.db.commit()
        self.db.refresh(lead)

        # Auto-SMS new lead
        if settings.auto_sms_new_leads and lead.lead_phone:
            prop = (
                self.db.query(Property).filter(Property.id == property_uuid).first()
                if property_uuid else None
            )
            prop_name = prop.name if prop else "our property"
            msg = (
                f"Hi {lead.lead_name}, thanks for your interest in {prop_name}. "
                f"We'll be in touch shortly to arrange a viewing. PROPERTECH"
            )
            _send_sms(lead.lead_phone, msg)

        logger.info(f"[vacancy] Created lead {lead.id} — {lead.lead_name}")
        return lead

    # ── log_activity ──────────────────────────────────────────────────────────

    def log_activity(
        self,
        lead_id: str,
        activity_type: str,
        content: str,
        performed_by: uuid.UUID,
    ) -> VacancyLeadActivity:
        lead_uuid = uuid.UUID(lead_id)
        lead = (
            self.db.query(VacancyLead)
            .filter(
                VacancyLead.id == lead_uuid,
                VacancyLead.owner_id == self.owner_id,
            )
            .first()
        )
        if not lead:
            raise ValueError(f"Lead {lead_id} not found")

        activity = VacancyLeadActivity(
            id=uuid.uuid4(),
            lead_id=lead_uuid,
            owner_id=self.owner_id,
            activity_type=activity_type,
            content=content,
            performed_by=performed_by,
        )
        self.db.add(activity)

        now = datetime.now(timezone.utc)
        lead.last_contacted_at = now

        if activity_type == "status_change":
            # Extract new status from content e.g. "Status changed to: contacted"
            for status_val in [
                "contacted", "viewing_scheduled", "viewed",
                "applied", "approved", "rejected", "converted", "lost",
            ]:
                if status_val in content.lower():
                    lead.status = status_val
                    break

        # Reset follow-up timer
        settings = self.get_or_create_settings()
        lead.follow_up_due_at = now + timedelta(hours=settings.lead_follow_up_hours or 24)

        self.db.commit()
        self.db.refresh(activity)
        return activity

    # ── get_pipeline_stats ────────────────────────────────────────────────────

    def get_pipeline_stats(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)

        inactive = {"converted", "lost", "rejected"}

        all_leads = (
            self.db.query(VacancyLead)
            .filter(VacancyLead.owner_id == self.owner_id)
            .all()
        )

        active_leads = [l for l in all_leads if l.status not in inactive]
        overdue = [
            l for l in active_leads
            if l.follow_up_due_at and _to_utc(l.follow_up_due_at) < now
        ]

        leads_by_status: Dict[str, int] = {}
        for lead in all_leads:
            leads_by_status[lead.status] = leads_by_status.get(lead.status, 0) + 1

        # Avg days to conversion
        converted = [
            l for l in all_leads
            if l.status == "converted" and l.converted_tenant_id
        ]
        avg_days = 0.0
        if converted:
            deltas = [
                (_to_utc(l.updated_at) - _to_utc(l.created_at)).days
                for l in converted
                if l.updated_at and l.created_at
            ]
            avg_days = round(sum(deltas) / len(deltas), 1) if deltas else 0.0

        # Listing stats
        syndications = (
            self.db.query(ListingSyndication)
            .filter(
                ListingSyndication.owner_id == self.owner_id,
                ListingSyndication.status == "active",
            )
            .all()
        )
        total_views = sum(s.view_count or 0 for s in syndications)
        total_enquiries = sum(s.enquiry_count or 0 for s in syndications)

        # Campaign stats
        campaigns = (
            self.db.query(RenewalCampaign)
            .filter(
                RenewalCampaign.owner_id == self.owner_id,
                RenewalCampaign.campaign_status.in_(["scheduled", "active"]),
            )
            .all()
        )
        at_risk = [
            c for c in campaigns
            if c.trigger_days_before_expiry == 7
            and (c.tenant_response is None or c.tenant_response == "no_response")
        ]

        return {
            "total_active_leads": len(active_leads),
            "leads_by_status": leads_by_status,
            "overdue_follow_ups": len(overdue),
            "avg_days_lead_to_conversion": avg_days,
            "active_listings": len(syndications),
            "total_listing_views": total_views,
            "total_listing_enquiries": total_enquiries,
            "active_renewal_campaigns": len(campaigns),
            "renewals_at_risk": len(at_risk),
        }

    # ── get_units_at_risk ─────────────────────────────────────────────────────

    def get_units_at_risk(self) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=90)

        leases = (
            self.db.query(Lease)
            .filter(
                Lease.owner_id == self.owner_id,
                Lease.status == LeaseStatus.ACTIVE,
                Lease.end_date.isnot(None),
            )
            .all()
        )

        result = []
        for lease in leases:
            end = lease.end_date
            if hasattr(end, "tzinfo") and end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            if end > cutoff:
                continue

            days_left = max(0, (end - now).days)

            unit = (
                self.db.query(Unit).filter(Unit.id == lease.unit_id).first()
                if lease.unit_id else None
            )
            prop = (
                self.db.query(Property).filter(Property.id == lease.property_id).first()
                if lease.property_id else None
            )

            # Check for existing campaign
            campaign = (
                self.db.query(RenewalCampaign)
                .filter(
                    RenewalCampaign.lease_id == lease.id,
                    RenewalCampaign.owner_id == self.owner_id,
                    RenewalCampaign.campaign_status.in_(["scheduled", "active", "responded"]),
                )
                .order_by(RenewalCampaign.created_at.desc())
                .first()
            )

            result.append({
                "unit_id": str(lease.unit_id) if lease.unit_id else "",
                "unit_number": unit.unit_number if unit else "—",
                "property_name": prop.name if prop else "—",
                "tenant_name": lease.tenant_name or "—",
                "expiry_date": end.date().isoformat(),
                "days_until_expiry": days_left,
                "has_active_campaign": campaign is not None,
                "campaign_status": campaign.campaign_status if campaign else None,
            })

        result.sort(key=lambda x: x["days_until_expiry"])
        return result


# ── Utility ───────────────────────────────────────────────────────────────────

def _infer_unit_type(bedrooms: Optional[int]) -> str:
    if bedrooms is None or bedrooms == 0:
        return "Studio"
    elif bedrooms == 1:
        return "1BR"
    elif bedrooms == 2:
        return "2BR"
    elif bedrooms == 3:
        return "3BR"
    else:
        return "4BR+"


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
