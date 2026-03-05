"""
Vacancy History Service
Tracks when units go vacant and when they are filled.
Called by event bus subscriptions on unit_vacated / tenant_onboarded events.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.price_optimization import VacancyHistory

logger = logging.getLogger(__name__)


class VacancyHistoryService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def start_vacancy(
        self,
        unit_id: str,
        owner_id: str,
        rent_at_vacancy: float,
    ) -> VacancyHistory:
        """
        Called when a unit_vacated event fires.
        Creates a new VacancyHistory row with vacant_from=now.
        """
        try:
            record = VacancyHistory(
                id=uuid.uuid4(),
                unit_id=uuid.UUID(unit_id),
                owner_id=uuid.UUID(owner_id),
                vacant_from=datetime.now(timezone.utc),
                rent_at_vacancy=rent_at_vacancy,
            )
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
            logger.info(
                f"[vacancy_history] Started vacancy for unit {unit_id} "
                f"at rent KES {rent_at_vacancy}"
            )
            return record
        except Exception as exc:
            logger.error(f"[vacancy_history] start_vacancy failed: {exc}", exc_info=True)
            self.db.rollback()
            raise

    def end_vacancy(
        self,
        unit_id: str,
        tenant_id: Optional[str],
        rent_when_filled: float,
    ) -> Optional[VacancyHistory]:
        """
        Called when a tenant_onboarded event fires.
        Closes the open VacancyHistory row for this unit.
        """
        try:
            record = (
                self.db.query(VacancyHistory)
                .filter(
                    VacancyHistory.unit_id == uuid.UUID(unit_id),
                    VacancyHistory.vacant_until == None,  # noqa: E711
                )
                .order_by(VacancyHistory.vacant_from.desc())
                .first()
            )
            if not record:
                logger.info(
                    f"[vacancy_history] No open vacancy record for unit {unit_id} — skipping end_vacancy"
                )
                return None

            now = datetime.now(timezone.utc)
            delta = now - record.vacant_from.replace(tzinfo=timezone.utc) \
                if record.vacant_from.tzinfo is None \
                else now - record.vacant_from
            days_vacant = max(0, delta.days)

            record.vacant_until = now
            record.days_vacant = days_vacant
            record.rent_when_filled = rent_when_filled
            if tenant_id:
                try:
                    record.filled_by_tenant_id = uuid.UUID(tenant_id)
                except ValueError:
                    pass

            self.db.commit()
            self.db.refresh(record)
            logger.info(
                f"[vacancy_history] Closed vacancy for unit {unit_id}: "
                f"{days_vacant} days vacant, filled at KES {rent_when_filled}"
            )
            return record
        except Exception as exc:
            logger.error(f"[vacancy_history] end_vacancy failed: {exc}", exc_info=True)
            self.db.rollback()
            raise
