"""
Price Optimization Service
Core algorithm that computes rent recommendations using:
  - Market comparables (40% weight)
  - Portfolio median rent (25% weight)
  - Vacancy pressure adjustment (20% weight)
  - Historical fill rate adjustment (15% weight)

All amounts rounded to nearest KES 500.
Never crashes on missing data — graceful fallback to current_rent base.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import median
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.price_optimization import (
    MarketComparable,
    PriceOptimizationSettings,
    RentReview,
    VacancyHistory,
)
from app.models.property import Property, Unit

logger = logging.getLogger(__name__)


def _round_to_500(value: float) -> float:
    """Round to the nearest KES 500."""
    return round(value / 500) * 500


class PriceOptimizationService:
    def __init__(self, db: Session, owner_id: uuid.UUID) -> None:
        self.db = db
        self.owner_id = owner_id

    # ── Settings helpers ──────────────────────────────────────────────────────

    def _get_settings(self) -> PriceOptimizationSettings:
        settings = (
            self.db.query(PriceOptimizationSettings)
            .filter(PriceOptimizationSettings.owner_id == self.owner_id)
            .first()
        )
        if not settings:
            settings = PriceOptimizationSettings(
                id=uuid.uuid4(),
                owner_id=self.owner_id,
            )
            self.db.add(settings)
            self.db.commit()
            self.db.refresh(settings)
        return settings

    # ── Core algorithm ────────────────────────────────────────────────────────

    def calculate_recommendation(self, unit_id: str) -> Dict[str, Any]:
        """
        Compute a rent recommendation for the given unit.
        Never raises — falls back gracefully when data is missing.
        """
        unit_uuid = uuid.UUID(unit_id)

        # ── Step 1: Gather unit context ──────────────────────────────────────
        unit: Optional[Unit] = self.db.query(Unit).filter(Unit.id == unit_uuid).first()
        if not unit:
            raise ValueError(f"Unit {unit_id} not found")

        property_: Optional[Property] = (
            self.db.query(Property)
            .filter(Property.id == unit.property_id)
            .first()
        )

        current_rent = float(unit.monthly_rent or 0)
        unit_type = _infer_unit_type(unit.bedrooms)
        location_area = (property_.area or "") if property_ else ""
        property_id = unit.property_id

        vacancy_records = (
            self.db.query(VacancyHistory)
            .filter(VacancyHistory.unit_id == unit_uuid)
            .order_by(VacancyHistory.created_at.desc())
            .limit(5)
            .all()
        )

        historical_days: List[int] = [
            r.days_vacant for r in vacancy_records if r.days_vacant is not None
        ]
        avg_historical_days = (
            sum(historical_days) / len(historical_days) if historical_days else None
        )

        # Days currently vacant (open vacancy record)
        open_vacancy = next(
            (r for r in vacancy_records if r.vacant_until is None), None
        )
        days_currently_vacant = 0
        if open_vacancy:
            now = datetime.now(timezone.utc)
            vf = open_vacancy.vacant_from
            if vf.tzinfo is None:
                vf = vf.replace(tzinfo=timezone.utc)
            days_currently_vacant = max(0, (now - vf).days)

        # ── Step 2: Market comparables ───────────────────────────────────────
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=90)
        comparables = (
            self.db.query(MarketComparable)
            .filter(
                MarketComparable.owner_id == self.owner_id,
                MarketComparable.unit_type == unit_type,
                MarketComparable.data_date >= cutoff,
            )
            .all()
        )

        market_asking_rents = [float(c.asking_rent) for c in comparables]
        market_actual_rents = [float(c.actual_rent) for c in comparables if c.actual_rent]
        market_vacancy_days_list = [c.vacancy_days for c in comparables if c.vacancy_days is not None]

        market_median_asking = median(market_asking_rents) if market_asking_rents else None
        market_median_actual = median(market_actual_rents) if market_actual_rents else None
        market_avg_vacancy = (
            sum(market_vacancy_days_list) / len(market_vacancy_days_list)
            if market_vacancy_days_list else None
        )

        # Freshness: are any comparables < 30 days old?
        thirty_days_ago = datetime.now(timezone.utc).date() - timedelta(days=30)
        has_fresh_data = any(c.data_date >= thirty_days_ago for c in comparables)

        # ── Step 3: Portfolio context ─────────────────────────────────────────
        # Find all units owned by this owner with the same unit_type
        owner_properties = (
            self.db.query(Property)
            .filter(Property.user_id == self.owner_id)
            .all()
        )
        property_ids = [p.id for p in owner_properties]

        portfolio_units = (
            self.db.query(Unit)
            .filter(
                Unit.property_id.in_(property_ids),
                Unit.bedrooms == unit.bedrooms,
            )
            .all()
        ) if property_ids else []

        portfolio_rents = [float(u.monthly_rent) for u in portfolio_units if u.monthly_rent]
        portfolio_median = median(portfolio_rents) if portfolio_rents else None

        # ── Step 4: Scoring algorithm ─────────────────────────────────────────
        reasoning: List[str] = []
        weighted_sum = 0.0
        weight_total = 0.0

        # Signal A — market median actual rent (40%)
        market_base = market_median_actual or market_median_asking
        if market_base:
            weighted_sum += market_base * 0.40
            weight_total += 0.40
            rent_type = "actual" if market_median_actual else "asking"
            reasoning.append(
                f"Market median {rent_type} rent for {unit_type} units "
                f"in {location_area or 'your area'} is KES {market_base:,.0f} "
                f"({len(comparables)} comparable(s) found)"
            )
        else:
            # No market data — use current_rent as base, cap confidence
            weighted_sum += current_rent * 0.40
            weight_total += 0.40
            reasoning.append(
                f"No market comparables found for {unit_type} — using current rent as base. "
                "Add comparables under Market Data to improve accuracy."
            )

        # Signal B — portfolio median rent (25%)
        if portfolio_median:
            weighted_sum += portfolio_median * 0.25
            weight_total += 0.25
            reasoning.append(
                f"Your portfolio median rent for {unit_type} units is KES {portfolio_median:,.0f} "
                f"({len(portfolio_units)} unit(s))"
            )
        else:
            weighted_sum += current_rent * 0.25
            weight_total += 0.25

        # Signal C — vacancy pressure adjustment (20%)
        settings = self._get_settings()
        target_days = int(settings.target_vacancy_days or 14)
        pressure_base = current_rent
        pressure_adj = 0.0

        if days_currently_vacant > target_days:
            pressure_adj = -0.05  # -5% if vacant too long
            reasoning.append(
                f"Unit has been vacant {days_currently_vacant} days "
                f"(target: {target_days} days) — slight downward pressure applied (-5%)"
            )
        elif days_currently_vacant > 0 and days_currently_vacant < 7:
            pressure_adj = +0.03  # +3% if just became vacant
            reasoning.append(
                f"Unit just became vacant ({days_currently_vacant} days) — "
                "upward pressure applied (+3%)"
            )

        adjusted_by_pressure = pressure_base * (1 + pressure_adj)
        weighted_sum += adjusted_by_pressure * 0.20
        weight_total += 0.20

        # Signal D — historical fill rate (15%)
        fill_adj = 0.0
        if avg_historical_days is not None:
            if avg_historical_days < 10:
                fill_adj = +0.05
                reasoning.append(
                    f"Historically this unit fills in {avg_historical_days:.0f} days — "
                    "strong demand, slight upward adjustment (+5%)"
                )
            elif avg_historical_days > 21:
                fill_adj = -0.05
                reasoning.append(
                    f"Historically this unit takes {avg_historical_days:.0f} days to fill — "
                    "slight downward adjustment (-5%)"
                )
            else:
                reasoning.append(
                    f"Historically this unit fills in {avg_historical_days:.0f} days — "
                    "within target range, no adjustment"
                )
            fill_base = current_rent * (1 + fill_adj)
            weighted_sum += fill_base * 0.15
            weight_total += 0.15
        else:
            # No history — skip this signal, redistribute weight proportionally
            weighted_sum += current_rent * 0.15
            weight_total += 0.15
            reasoning.append("No vacancy history found — fill rate adjustment skipped")

        # Normalise (weight_total should always be 1.0 but guard anyway)
        raw_recommended = (weighted_sum / weight_total) if weight_total > 0 else current_rent
        recommended_rent = _round_to_500(raw_recommended)

        # ── Guardrails ────────────────────────────────────────────────────────
        max_inc_pct = float(settings.max_increase_pct or 10)
        max_dec_pct = float(settings.max_decrease_pct or 15)
        min_floor = float(settings.min_rent_floor) if settings.min_rent_floor else None

        max_allowed = current_rent * (1 + max_inc_pct / 100)
        min_allowed = current_rent * (1 - max_dec_pct / 100)

        if min_floor:
            min_allowed = max(min_allowed, min_floor)

        if recommended_rent > max_allowed:
            recommended_rent = _round_to_500(max_allowed)
            reasoning.append(
                f"Recommendation capped at +{max_inc_pct}% above current rent (KES {recommended_rent:,.0f})"
            )
        if recommended_rent < min_allowed:
            recommended_rent = _round_to_500(min_allowed)
            reasoning.append(
                f"Recommendation floored at -{max_dec_pct}% below current rent (KES {recommended_rent:,.0f})"
            )
        if min_floor and recommended_rent < min_floor:
            recommended_rent = _round_to_500(min_floor)
            reasoning.append(f"Applied absolute minimum rent floor of KES {min_floor:,.0f}")

        # ── Confidence score ──────────────────────────────────────────────────
        confidence = 50
        if len(comparables) >= 3:
            confidence += 20
        if len(historical_days) >= 3:
            confidence += 10
        if len(portfolio_units) >= 5:
            confidence += 10
        if has_fresh_data:
            confidence += 10
        # If no market comparables, cap at 40
        if not comparables:
            confidence = min(confidence, 40)
        confidence = min(confidence, 100)

        # min/max rents
        min_rent = _round_to_500(current_rent * (1 - max_dec_pct / 100))
        if min_floor:
            min_rent = max(min_rent, _round_to_500(min_floor))
        max_rent = _round_to_500(current_rent * (1 + max_inc_pct / 100))

        market_snapshot: Dict[str, Any] = {
            "market_median_actual": market_median_actual,
            "market_median_asking": market_median_asking,
            "market_avg_vacancy_days": market_avg_vacancy,
            "comparable_count": len(comparables),
            "portfolio_median": portfolio_median,
            "portfolio_unit_count": len(portfolio_units),
            "days_currently_vacant": days_currently_vacant,
            "avg_historical_days_vacant": avg_historical_days,
            "location_area": location_area,
            "unit_type": unit_type,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "unit_id": unit_id,
            "property_id": str(property_id),
            "current_rent": current_rent,
            "recommended_rent": float(recommended_rent),
            "min_rent": float(min_rent),
            "max_rent": float(max_rent),
            "confidence_score": confidence,
            "reasoning": reasoning,
            "market_data_snapshot": market_snapshot,
        }

    def create_review(self, unit_id: str, trigger: str) -> RentReview:
        """Calculate recommendation and persist a RentReview row with status=pending."""
        rec = self.calculate_recommendation(unit_id)

        unit = self.db.query(Unit).filter(Unit.id == uuid.UUID(unit_id)).first()
        if not unit:
            raise ValueError(f"Unit {unit_id} not found")

        review = RentReview(
            id=uuid.uuid4(),
            owner_id=self.owner_id,
            unit_id=uuid.UUID(unit_id),
            property_id=unit.property_id,
            trigger=trigger,
            current_rent=rec["current_rent"],
            recommended_rent=rec["recommended_rent"],
            min_rent=rec["min_rent"],
            max_rent=rec["max_rent"],
            confidence_score=rec["confidence_score"],
            reasoning=rec["reasoning"],
            market_data_snapshot=rec["market_data_snapshot"],
            status="pending",
        )
        self.db.add(review)
        self.db.commit()
        self.db.refresh(review)
        logger.info(
            f"[price_opt] Created RentReview {review.id} for unit {unit_id} "
            f"trigger={trigger} recommended=KES {rec['recommended_rent']:,.0f} "
            f"confidence={rec['confidence_score']}"
        )
        return review

    def apply_recommendation(
        self,
        review_id: str,
        accepted_rent: float,
        reviewed_by: uuid.UUID,
    ) -> RentReview:
        """
        Accept a review: update review status, update unit's monthly_rent.
        Returns the updated RentReview.
        """
        review = (
            self.db.query(RentReview)
            .filter(
                RentReview.id == uuid.UUID(review_id),
                RentReview.owner_id == self.owner_id,
            )
            .first()
        )
        if not review:
            raise ValueError(f"RentReview {review_id} not found")

        now = datetime.now(timezone.utc)
        review.status = "accepted"
        review.accepted_rent = accepted_rent
        review.reviewed_by = reviewed_by
        review.reviewed_at = now
        self.db.commit()

        # Apply to unit
        unit = self.db.query(Unit).filter(Unit.id == review.unit_id).first()
        if unit:
            old_rent = float(unit.monthly_rent or 0)
            unit.monthly_rent = accepted_rent
            self.db.commit()
            logger.info(
                f"[price_opt] Applied rent change for unit {unit.id}: "
                f"KES {old_rent:,.0f} → KES {accepted_rent:,.0f}"
            )

        review.status = "applied"
        review.applied_at = now
        self.db.commit()
        self.db.refresh(review)
        return review

    def get_portfolio_health(self) -> Dict[str, Any]:
        """Compute portfolio-wide health metrics for the owner."""
        owner_properties = (
            self.db.query(Property)
            .filter(Property.user_id == self.owner_id)
            .all()
        )
        property_ids = [p.id for p in owner_properties]
        property_map = {p.id: p for p in owner_properties}

        if not property_ids:
            return {
                "total_units": 0,
                "occupied_count": 0,
                "vacant_count": 0,
                "occupancy_rate": 0.0,
                "units_with_pending_review": 0,
                "avg_days_to_fill": 0.0,
                "estimated_monthly_revenue_loss": 0.0,
                "top_3_units_to_review": [],
            }

        all_units = (
            self.db.query(Unit)
            .filter(Unit.property_id.in_(property_ids))
            .all()
        )
        total = len(all_units)
        vacant_units = [u for u in all_units if u.status in ("vacant", "available")]
        occupied_count = total - len(vacant_units)
        occupancy_rate = round(occupied_count / total * 100, 1) if total else 0.0

        # Pending reviews
        pending_reviews = (
            self.db.query(RentReview)
            .filter(
                RentReview.owner_id == self.owner_id,
                RentReview.status == "pending",
            )
            .all()
        )
        pending_unit_ids = {str(r.unit_id) for r in pending_reviews}

        # Avg days to fill from vacancy history
        filled_records = (
            self.db.query(VacancyHistory)
            .filter(
                VacancyHistory.owner_id == self.owner_id,
                VacancyHistory.days_vacant != None,  # noqa: E711
            )
            .all()
        )
        avg_days_to_fill = 0.0
        if filled_records:
            avg_days_to_fill = round(
                sum(r.days_vacant for r in filled_records) / len(filled_records), 1
            )

        # Estimated monthly revenue loss from vacant units
        revenue_loss = sum(float(u.monthly_rent or 0) for u in vacant_units)

        # Top 3 units to review: vacant, no pending review, longest vacant
        vacant_no_review = []
        for u in vacant_units:
            if str(u.id) in pending_unit_ids:
                continue
            # Find open vacancy record
            open_vac = (
                self.db.query(VacancyHistory)
                .filter(
                    VacancyHistory.unit_id == u.id,
                    VacancyHistory.vacant_until == None,  # noqa: E711
                )
                .order_by(VacancyHistory.vacant_from.desc())
                .first()
            )
            days_vacant = 0
            if open_vac:
                now = datetime.now(timezone.utc)
                vf = open_vac.vacant_from
                if vf.tzinfo is None:
                    vf = vf.replace(tzinfo=timezone.utc)
                days_vacant = max(0, (now - vf).days)

            prop = property_map.get(u.property_id)
            vacant_no_review.append({
                "unit_id": str(u.id),
                "unit_number": u.unit_number,
                "property_name": prop.name if prop else "",
                "days_vacant": days_vacant,
                "current_rent": float(u.monthly_rent or 0),
            })

        top_3 = sorted(vacant_no_review, key=lambda x: x["days_vacant"], reverse=True)[:3]

        return {
            "total_units": total,
            "occupied_count": occupied_count,
            "vacant_count": len(vacant_units),
            "occupancy_rate": occupancy_rate,
            "units_with_pending_review": len(pending_unit_ids),
            "avg_days_to_fill": avg_days_to_fill,
            "estimated_monthly_revenue_loss": revenue_loss,
            "top_3_units_to_review": top_3,
        }


# ── Helper ─────────────────────────────────────────────────────────────────────

def _infer_unit_type(bedrooms: Optional[int]) -> str:
    """Map bedroom count to unit_type label matching MarketComparable.unit_type."""
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
