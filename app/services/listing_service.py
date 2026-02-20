"""
Listing Service
Handles auto-population from unit/property data, slug generation,
description templating, and listing lifecycle management.
"""
from __future__ import annotations

import logging
import random
import re
import string
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.listing import (
    VacancyListing, ListingLead, ListingAnalytics,
    ListingStatus, AnalyticsEventType,
)
from app.models.property import Property, Unit

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

_AMENITY_KEYWORDS = {
    "wifi": ["wifi", "internet", "wi-fi", "broadband"],
    "parking": ["parking", "garage", "car port", "carport"],
    "water": ["water", "borehole"],
    "generator": ["generator", "backup power", "genset"],
    "security": ["security", "cctv", "guard", "gated"],
    "gym": ["gym", "fitness"],
    "pool": ["pool", "swimming"],
    "balcony": ["balcony", "terrace"],
    "furnished": ["furnished", "furniture"],
    "pet_friendly": ["pet", "dog", "cat"],
    "garden": ["garden", "compound", "lawn"],
    "lift": ["lift", "elevator"],
}


def _slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text[:80]


def _random_suffix(length: int = 5) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _infer_amenities_from_description(description: str) -> List[str]:
    """Heuristically extract amenity tags from free-text description."""
    desc_lower = description.lower() if description else ""
    found = []
    for tag, keywords in _AMENITY_KEYWORDS.items():
        if any(kw in desc_lower for kw in keywords):
            found.append(tag)
    return found


# ── ListingService ─────────────────────────────────────────────────────────────

class ListingService:
    def __init__(self, db: Session):
        self.db = db

    # ── Slug management ───────────────────────────────────────────────────────

    def generate_slug(self, property_name: str, unit_name: str) -> str:
        """
        Create a unique URL-safe slug, e.g. 'kuscco-homes-unit-4b'.
        Appends a short random suffix on collision.
        """
        base = _slugify(f"{property_name}-{unit_name}")
        candidate = base
        for _ in range(10):
            exists = (
                self.db.query(VacancyListing)
                .filter(VacancyListing.slug == candidate)
                .first()
            )
            if not exists:
                return candidate
            candidate = f"{base}-{_random_suffix()}"
        # Fallback: fully random slug
        return f"listing-{_random_suffix(8)}"

    def _ensure_unique_slug(self, slug: str, exclude_id: Optional[uuid.UUID] = None) -> str:
        q = self.db.query(VacancyListing).filter(VacancyListing.slug == slug)
        if exclude_id:
            q = q.filter(VacancyListing.id != exclude_id)
        if q.first():
            return f"{slug}-{_random_suffix()}"
        return slug

    # ── Description template ──────────────────────────────────────────────────

    def generate_listing_description(self, unit_data: Dict[str, Any]) -> str:
        """
        Generate a professional listing description from structured unit data.
        No AI required — structured f-string template.
        """
        property_name = unit_data.get("property_name", "the property")
        unit_number = unit_data.get("unit_number", "")
        bedrooms = unit_data.get("bedrooms", 1)
        bathrooms = unit_data.get("bathrooms", 1)
        area = unit_data.get("area", "")
        city = unit_data.get("city", "Nairobi")
        monthly_rent = unit_data.get("monthly_rent", 0)
        deposit = unit_data.get("deposit_amount", 0)
        sq_feet = unit_data.get("square_feet")
        amenities: List[str] = unit_data.get("amenities", [])
        available_from = unit_data.get("available_from")

        # Bedroom label
        if bedrooms == 0:
            bed_label = "Studio"
        elif bedrooms == 1:
            bed_label = "1-bedroom"
        else:
            bed_label = f"{bedrooms}-bedroom"

        # Location string
        location_parts = [p for p in [area, city] if p]
        location = ", ".join(location_parts) if location_parts else city

        # Amenity list
        amenity_str = ""
        if amenities:
            clean = [a.replace("_", " ").title() for a in amenities]
            amenity_str = f"\n\nAmenities include: {', '.join(clean)}."

        # Size
        size_str = f"\nSize: approximately {sq_feet:,} sq ft." if sq_feet else ""

        # Availability
        avail_str = ""
        if available_from:
            if isinstance(available_from, str):
                avail_str = f"\n\nAvailable from: {available_from[:10]}."
            elif isinstance(available_from, datetime):
                avail_str = f"\n\nAvailable from: {available_from.strftime('%d %B %Y')}."

        # Deposit
        deposit_str = (
            f" A deposit of KES {deposit:,.0f} is required."
            if deposit and deposit > 0
            else ""
        )

        description = (
            f"Spacious and well-maintained {bed_label} unit available for rent "
            f"at {property_name}"
            + (f", Unit {unit_number}" if unit_number else "")
            + f", located in {location}."
            + f"\n\nRent: KES {monthly_rent:,.0f} per month.{deposit_str}"
            + size_str
            + amenity_str
            + avail_str
            + f"\n\nThis unit features {bedrooms} bedroom(s) and {bathrooms} bathroom(s), "
            "offering comfortable living in a secure and well-managed property."
            "\n\nFor viewings or inquiries, please use the contact form below or "
            "reach out directly. Don't miss this opportunity!"
        )
        return description

    # ── Auto-populate from unit ───────────────────────────────────────────────

    def auto_populate_from_unit(self, unit_id: uuid.UUID, owner_id: uuid.UUID) -> Dict[str, Any]:
        """
        Pull property/unit data to pre-fill a listing draft.
        Returns a dict matching AutoPopulateResponse schema.
        """
        unit: Optional[Unit] = self.db.query(Unit).filter(Unit.id == unit_id).first()
        if not unit:
            return {}

        prop: Optional[Property] = (
            self.db.query(Property)
            .filter(Property.id == unit.property_id)
            .first()
        )

        property_name = prop.name if prop else "Property"
        unit_number = unit.unit_number or ""
        area = getattr(prop, "area", None) or ""
        city = getattr(prop, "city", None) or "Nairobi"
        monthly_rent = unit.monthly_rent or 0.0

        # Existing photos from property
        photos: List[str] = []
        if prop and prop.photos:
            try:
                import json
                raw = prop.photos
                if isinstance(raw, str):
                    raw = json.loads(raw)
                if isinstance(raw, list):
                    photos = [p for p in raw if isinstance(p, str)]
            except Exception:
                pass
        if prop and prop.image_url:
            if prop.image_url not in photos:
                photos.insert(0, prop.image_url)

        # Infer amenities from unit/property description
        combined_desc = " ".join(filter(None, [
            getattr(unit, "description", ""),
            getattr(prop, "description", ""),
        ]))
        amenities = _infer_amenities_from_description(combined_desc)

        unit_data = {
            "property_name": property_name,
            "unit_number": unit_number,
            "bedrooms": unit.bedrooms or 1,
            "bathrooms": unit.bathrooms or 1,
            "area": area,
            "city": city,
            "monthly_rent": monthly_rent,
            "deposit_amount": 0.0,
            "square_feet": unit.square_feet,
            "amenities": amenities,
        }

        description = self.generate_listing_description(unit_data)
        title = f"{unit_data['bedrooms']}BR at {property_name}"
        if unit_number:
            title = f"Unit {unit_number} – {title}"

        return {
            "title": title,
            "description": description,
            "monthly_rent": monthly_rent,
            "deposit_amount": 0.0,
            "available_from": None,
            "amenities": amenities,
            "photos": photos,
            "property_name": property_name,
            "unit_number": unit_number,
            "bedrooms": unit.bedrooms,
            "bathrooms": unit.bathrooms,
            "area": area,
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def mark_listing_filled(self, listing_id: uuid.UUID) -> Optional[VacancyListing]:
        """
        Set listing status → filled, record filled_at timestamp,
        and update the linked unit status → occupied.
        """
        listing = (
            self.db.query(VacancyListing)
            .filter(VacancyListing.id == listing_id)
            .first()
        )
        if not listing:
            return None

        listing.status = ListingStatus.FILLED
        listing.filled_at = datetime.utcnow()

        # Update linked unit
        if listing.unit_id:
            unit = self.db.query(Unit).filter(Unit.id == listing.unit_id).first()
            if unit:
                unit.status = "occupied"
                unit.updated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(listing)
        logger.info(f"[listing] Listing {listing_id} marked as filled")
        return listing

    # ── Analytics recording ───────────────────────────────────────────────────

    def record_event(
        self,
        listing_id: uuid.UUID,
        event_type: AnalyticsEventType,
        platform: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        event = ListingAnalytics(
            listing_id=listing_id,
            event_type=event_type,
            platform=platform,
            ip_address=ip_address,
            user_agent=user_agent[:500] if user_agent else None,
        )
        self.db.add(event)
        self.db.commit()

    def increment_view_count(self, listing: VacancyListing) -> None:
        listing.view_count = (listing.view_count or 0) + 1
        self.db.commit()

    # ── Analytics summary ─────────────────────────────────────────────────────

    def get_analytics_summary(self, listing_id: uuid.UUID) -> Dict[str, Any]:
        from sqlalchemy import func

        events = (
            self.db.query(ListingAnalytics)
            .filter(ListingAnalytics.listing_id == listing_id)
            .all()
        )

        total_views = sum(1 for e in events if e.event_type == AnalyticsEventType.VIEW)
        total_inquiries = sum(1 for e in events if e.event_type == AnalyticsEventType.INQUIRY)
        total_shares = sum(1 for e in events if e.event_type == AnalyticsEventType.SHARE)

        views_by_platform: Dict[str, int] = {}
        inquiries_by_platform: Dict[str, int] = {}
        for e in events:
            p = e.platform or "direct"
            if e.event_type == AnalyticsEventType.VIEW:
                views_by_platform[p] = views_by_platform.get(p, 0) + 1
            elif e.event_type == AnalyticsEventType.INQUIRY:
                inquiries_by_platform[p] = inquiries_by_platform.get(p, 0) + 1

        # Lead status breakdown
        leads = (
            self.db.query(ListingLead)
            .filter(ListingLead.listing_id == listing_id)
            .all()
        )
        leads_by_status: Dict[str, int] = {}
        for lead in leads:
            leads_by_status[lead.status] = leads_by_status.get(lead.status, 0) + 1

        # Days on market
        listing = self.db.query(VacancyListing).filter(VacancyListing.id == listing_id).first()
        days_on_market: Optional[int] = None
        if listing and listing.published_at:
            end = listing.filled_at or datetime.utcnow()
            days_on_market = (end - listing.published_at).days

        conversion_rate = (total_inquiries / total_views) if total_views > 0 else 0.0

        return {
            "total_views": total_views,
            "total_inquiries": total_inquiries,
            "total_shares": total_shares,
            "days_on_market": days_on_market,
            "conversion_rate": round(conversion_rate, 4),
            "views_by_platform": views_by_platform,
            "inquiries_by_platform": inquiries_by_platform,
            "leads_by_status": leads_by_status,
        }

    # ── Email notification ────────────────────────────────────────────────────

    def notify_owner_new_lead(
        self,
        owner_email: str,
        lead_name: str,
        listing_title: str,
        listing_slug: str,
        phone: Optional[str],
        message: Optional[str],
        frontend_url: str,
    ) -> None:
        """Send email notification to owner when a new lead is received."""
        try:
            from app.services.email_service import send_email  # type: ignore
            subject = f"New inquiry on your listing: {listing_title}"
            body = (
                f"Hello,\n\n"
                f"You have a new inquiry on your listing '{listing_title}'.\n\n"
                f"Name: {lead_name}\n"
                f"Phone: {phone or 'Not provided'}\n"
                f"Message: {message or 'No message'}\n\n"
                f"View the lead: {frontend_url}/owner/listings\n\n"
                f"— PROPERTECH"
            )
            send_email(to=owner_email, subject=subject, body=body)
        except Exception as e:
            # Email is best-effort — never fail the request
            logger.warning(f"[listing] Failed to send lead notification email: {e}")
