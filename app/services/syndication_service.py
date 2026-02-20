"""
Syndication Service
Handles publishing listings to external platforms.

Instant platforms (no API key needed):
  - direct_link: generates a public URL
  - whatsapp:    generates a wa.me pre-filled message link
  - facebook:    generates Facebook Sharer URL
  - twitter:     generates Tweet Intent URL

Scaffolded platforms (API key required, graceful fallback):
  - buyrentkenya
  - jiji
  - property24
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Dict, Optional
from urllib.parse import quote as url_quote

from sqlalchemy.orm import Session

from app.models.listing import (
    VacancyListing, ListingSyndication,
    SyndicationPlatform, SyndicationStatus,
)

logger = logging.getLogger(__name__)


def _frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "https://propertechsoftware.com").rstrip("/")


# ── Platform handlers ──────────────────────────────────────────────────────────

class DirectLinkHandler:
    platform = SyndicationPlatform.DIRECT_LINK

    def publish(self, listing: VacancyListing) -> Dict:
        url = f"{_frontend_url()}/listings/{listing.slug}"
        return {
            "status": SyndicationStatus.PUBLISHED,
            "share_url": url,
            "external_url": url,
            "error_message": None,
        }


class WhatsAppHandler:
    platform = SyndicationPlatform.WHATSAPP

    def publish(self, listing: VacancyListing) -> Dict:
        listing_url = f"{_frontend_url()}/listings/{listing.slug}"
        summary = (
            f"*{listing.title}*\n"
            f"Rent: KES {listing.monthly_rent:,.0f}/mo\n"
            f"{listing_url}"
        )
        wa_url = f"https://wa.me/?text={url_quote(summary)}"
        return {
            "status": SyndicationStatus.PUBLISHED,
            "share_url": wa_url,
            "external_url": None,
            "error_message": None,
        }


class FacebookHandler:
    platform = SyndicationPlatform.FACEBOOK

    def publish(self, listing: VacancyListing) -> Dict:
        listing_url = f"{_frontend_url()}/listings/{listing.slug}"
        fb_url = (
            f"https://www.facebook.com/sharer/sharer.php"
            f"?u={url_quote(listing_url)}"
        )
        return {
            "status": SyndicationStatus.PUBLISHED,
            "share_url": fb_url,
            "external_url": None,
            "error_message": None,
        }


class TwitterHandler:
    platform = SyndicationPlatform.TWITTER

    def publish(self, listing: VacancyListing) -> Dict:
        listing_url = f"{_frontend_url()}/listings/{listing.slug}"
        tweet_text = (
            f"{listing.title} – KES {listing.monthly_rent:,.0f}/mo. "
            f"Now available! 🏠 {listing_url} #RealEstate #Kenya #ForRent"
        )
        tw_url = (
            f"https://twitter.com/intent/tweet"
            f"?text={url_quote(tweet_text)}"
        )
        return {
            "status": SyndicationStatus.PUBLISHED,
            "share_url": tw_url,
            "external_url": None,
            "error_message": None,
        }


class BuyRentKenyaHandler:
    """
    Scaffold for BuyRentKenya portal integration.
    Checks for BUYRENTKENYA_API_KEY; falls back gracefully if not set.
    """
    platform = SyndicationPlatform.BUYRENTKENYA

    def publish(self, listing: VacancyListing) -> Dict:
        api_key = os.getenv("BUYRENTKENYA_API_KEY", "")
        if not api_key:
            return {
                "status": SyndicationStatus.PENDING,
                "share_url": None,
                "external_url": None,
                "error_message": (
                    "BuyRentKenya API key not configured. "
                    "Add BUYRENTKENYA_API_KEY to environment variables to enable this integration."
                ),
            }
        # ── Actual integration (implement when API key available) ──────────
        try:
            return self._post_to_api(api_key, listing)
        except Exception as e:
            logger.error(f"[syndication] BuyRentKenya publish failed: {e}")
            return {
                "status": SyndicationStatus.FAILED,
                "share_url": None,
                "external_url": None,
                "error_message": str(e),
            }

    def _post_to_api(self, api_key: str, listing: VacancyListing) -> Dict:
        """Placeholder — implement with BuyRentKenya's actual API spec."""
        import httpx
        base_url = os.getenv("BUYRENTKENYA_API_URL", "https://api.buyrentkenya.com/v1")
        payload = {
            "title": listing.title,
            "description": listing.description,
            "price": listing.monthly_rent,
            "deposit": listing.deposit_amount,
            "type": "rental",
            "amenities": listing.amenities or [],
            "images": listing.photos or [],
            "reference": str(listing.id),
        }
        resp = httpx.post(
            f"{base_url}/listings",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "status": SyndicationStatus.PUBLISHED,
            "share_url": data.get("url"),
            "external_url": data.get("url"),
            "error_message": None,
        }

    def update_listing(self, external_id: str, listing: VacancyListing) -> Dict:
        api_key = os.getenv("BUYRENTKENYA_API_KEY", "")
        if not api_key:
            return {"status": SyndicationStatus.PENDING, "error_message": "API key not configured"}
        logger.info(f"[syndication] BuyRentKenya update_listing placeholder for {external_id}")
        return {"status": SyndicationStatus.PUBLISHED, "error_message": None}

    def delete_listing(self, external_id: str) -> Dict:
        api_key = os.getenv("BUYRENTKENYA_API_KEY", "")
        if not api_key:
            return {"status": SyndicationStatus.PENDING, "error_message": "API key not configured"}
        logger.info(f"[syndication] BuyRentKenya delete_listing placeholder for {external_id}")
        return {"status": SyndicationStatus.EXPIRED, "error_message": None}


class JijiHandler:
    """
    Scaffold for Jiji.co.ke portal integration.
    Checks for JIJI_API_KEY; falls back gracefully if not set.
    """
    platform = SyndicationPlatform.JIJI

    def publish(self, listing: VacancyListing) -> Dict:
        api_key = os.getenv("JIJI_API_KEY", "")
        if not api_key:
            return {
                "status": SyndicationStatus.PENDING,
                "share_url": None,
                "external_url": None,
                "error_message": (
                    "Jiji API key not configured. "
                    "Add JIJI_API_KEY to environment variables to enable this integration."
                ),
            }
        try:
            return self._post_to_api(api_key, listing)
        except Exception as e:
            logger.error(f"[syndication] Jiji publish failed: {e}")
            return {
                "status": SyndicationStatus.FAILED,
                "share_url": None,
                "external_url": None,
                "error_message": str(e),
            }

    def _post_to_api(self, api_key: str, listing: VacancyListing) -> Dict:
        """Placeholder — implement with Jiji's actual API spec."""
        import httpx
        base_url = os.getenv("JIJI_API_URL", "https://jiji.co.ke/api/v1")
        payload = {
            "title": listing.title,
            "body": listing.description,
            "price": listing.monthly_rent,
            "category": "houses_apartments_for_rent",
        }
        resp = httpx.post(
            f"{base_url}/ads",
            json=payload,
            headers={"Authorization": f"Api-Key {api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "status": SyndicationStatus.PUBLISHED,
            "share_url": data.get("ad_url"),
            "external_url": data.get("ad_url"),
            "error_message": None,
        }

    def update_listing(self, external_id: str, listing: VacancyListing) -> Dict:
        api_key = os.getenv("JIJI_API_KEY", "")
        if not api_key:
            return {"status": SyndicationStatus.PENDING, "error_message": "API key not configured"}
        logger.info(f"[syndication] Jiji update_listing placeholder for {external_id}")
        return {"status": SyndicationStatus.PUBLISHED, "error_message": None}

    def delete_listing(self, external_id: str) -> Dict:
        api_key = os.getenv("JIJI_API_KEY", "")
        if not api_key:
            return {"status": SyndicationStatus.PENDING, "error_message": "API key not configured"}
        logger.info(f"[syndication] Jiji delete_listing placeholder for {external_id}")
        return {"status": SyndicationStatus.EXPIRED, "error_message": None}


class Property24Handler:
    """
    Scaffold for Property24 Kenya portal integration.
    Checks for PROPERTY24_API_KEY; falls back gracefully if not set.
    """
    platform = SyndicationPlatform.PROPERTY24

    def publish(self, listing: VacancyListing) -> Dict:
        api_key = os.getenv("PROPERTY24_API_KEY", "")
        if not api_key:
            return {
                "status": SyndicationStatus.PENDING,
                "share_url": None,
                "external_url": None,
                "error_message": (
                    "Property24 API key not configured. "
                    "Add PROPERTY24_API_KEY to environment variables to enable this integration."
                ),
            }
        try:
            return self._post_to_api(api_key, listing)
        except Exception as e:
            logger.error(f"[syndication] Property24 publish failed: {e}")
            return {
                "status": SyndicationStatus.FAILED,
                "share_url": None,
                "external_url": None,
                "error_message": str(e),
            }

    def _post_to_api(self, api_key: str, listing: VacancyListing) -> Dict:
        """Placeholder — implement with Property24's actual API spec."""
        import httpx
        base_url = os.getenv("PROPERTY24_API_URL", "https://api.property24.com/v1")
        payload = {
            "Title": listing.title,
            "Description": listing.description,
            "Price": listing.monthly_rent,
            "PropertyType": "Apartment",
            "ListingType": "ToRent",
        }
        resp = httpx.post(
            f"{base_url}/listings",
            json=payload,
            headers={"x-api-key": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "status": SyndicationStatus.PUBLISHED,
            "share_url": data.get("ListingUrl"),
            "external_url": data.get("ListingUrl"),
            "error_message": None,
        }

    def update_listing(self, external_id: str, listing: VacancyListing) -> Dict:
        api_key = os.getenv("PROPERTY24_API_KEY", "")
        if not api_key:
            return {"status": SyndicationStatus.PENDING, "error_message": "API key not configured"}
        logger.info(f"[syndication] Property24 update_listing placeholder for {external_id}")
        return {"status": SyndicationStatus.PUBLISHED, "error_message": None}

    def delete_listing(self, external_id: str) -> Dict:
        api_key = os.getenv("PROPERTY24_API_KEY", "")
        if not api_key:
            return {"status": SyndicationStatus.PENDING, "error_message": "API key not configured"}
        logger.info(f"[syndication] Property24 delete_listing placeholder for {external_id}")
        return {"status": SyndicationStatus.EXPIRED, "error_message": None}


# ── Registry ───────────────────────────────────────────────────────────────────

_HANDLERS = {
    SyndicationPlatform.DIRECT_LINK: DirectLinkHandler(),
    SyndicationPlatform.WHATSAPP: WhatsAppHandler(),
    SyndicationPlatform.FACEBOOK: FacebookHandler(),
    SyndicationPlatform.TWITTER: TwitterHandler(),
    SyndicationPlatform.BUYRENTKENYA: BuyRentKenyaHandler(),
    SyndicationPlatform.JIJI: JijiHandler(),
    SyndicationPlatform.PROPERTY24: Property24Handler(),
}


# ── SyndicationService ─────────────────────────────────────────────────────────

class SyndicationService:
    def __init__(self, db: Session):
        self.db = db

    def syndicate(self, listing: VacancyListing, platform_key: str) -> ListingSyndication:
        """
        Publish or re-syndicate a listing to a given platform.
        Creates or updates the ListingSyndication row.
        """
        try:
            platform = SyndicationPlatform(platform_key)
        except ValueError:
            raise ValueError(f"Unknown platform: {platform_key}")

        handler = _HANDLERS.get(platform)
        if not handler:
            raise ValueError(f"No handler registered for platform: {platform_key}")

        result = handler.publish(listing)

        # Upsert syndication row
        syndication = (
            self.db.query(ListingSyndication)
            .filter(
                ListingSyndication.listing_id == listing.id,
                ListingSyndication.platform == platform,
            )
            .first()
        )
        if not syndication:
            syndication = ListingSyndication(
                listing_id=listing.id,
                platform=platform,
            )
            self.db.add(syndication)

        syndication.status = result["status"]
        syndication.share_url = result.get("share_url")
        syndication.external_url = result.get("external_url")
        syndication.error_message = result.get("error_message")
        syndication.last_synced_at = datetime.utcnow()
        if result["status"] == SyndicationStatus.PUBLISHED and not syndication.published_at:
            syndication.published_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(syndication)
        logger.info(
            f"[syndication] Platform={platform_key} "
            f"status={result['status']} listing={listing.id}"
        )
        return syndication

    def syndicate_all(self, listing: VacancyListing, platforms: list[str]) -> list[ListingSyndication]:
        """Syndicate to multiple platforms; always include direct_link."""
        all_platforms = list(set(["direct_link"] + platforms))
        results = []
        for p in all_platforms:
            try:
                s = self.syndicate(listing, p)
                results.append(s)
            except Exception as e:
                logger.error(f"[syndication] Failed for platform {p}: {e}")
        return results
