"""
Market Intelligence Service
Computes and caches neighbourhood-level market metrics by aggregating
platform data: properties, units, tenants, maintenance requests.

Area Health Score formula (0–100):
  - Occupancy score  : (1 - vacancy_rate) × 35          → max 35 pts
  - Tenancy stability: min(avg_months / 24, 1.0) × 30   → max 30 pts
  - Maintenance load : max(0, 1 - maint_rate × 2) × 25  → max 25 pts
  - Data quality     : min(data_points / 3, 1.0) × 10   → max 10 pts
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.models.market import AreaMetrics
from app.models.property import Property, Unit
from app.models.tenant import Tenant
from app.models.maintenance import MaintenanceRequest
from app.schemas.market import (
    AreaSummary,
    AreaDetail,
    RentByBedrooms,
    VacancyTrendPoint,
    PropertyBenchmark,
    UnitBenchmark,
    BenchmarkSummary,
    MyPropertiesBenchmarkResponse,
)

logger = logging.getLogger(__name__)


# ── Helper functions (must be defined before module-level constants) ────────

def _month_label(months_ago: int) -> str:
    """Return 'YYYY-MM' string for N months in the past."""
    dt = datetime.utcnow() - timedelta(days=30 * months_ago)
    return dt.strftime("%Y-%m")


def _compute_health_score(
    vacancy_rate: float,
    avg_tenancy_months: Optional[float],
    maintenance_rate: Optional[float],
    data_points: int,
) -> float:
    """Derive a 0–100 area health score from the four core metrics."""
    occupancy_score = (1.0 - min(vacancy_rate, 1.0)) * 35.0
    tenancy_score = min((avg_tenancy_months or 0) / 24.0, 1.0) * 30.0
    maint_score = max(0.0, 1.0 - min((maintenance_rate or 0) * 2.0, 1.0)) * 25.0
    data_score = min(data_points / 3.0, 1.0) * 10.0
    return round(occupancy_score + tenancy_score + maint_score + data_score, 1)


def _avg_rent_for_bedroom(
    rents_by_br: Dict[int, List[float]], bedrooms: int
) -> Optional[float]:
    """Return mean rent for a bedroom count, or None if no data."""
    vals = rents_by_br.get(bedrooms, [])
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


# ── Seed data for Nairobi neighbourhoods ───────────────────────────────────
# Inserted once when area_metrics is empty. Reflects realistic 2024 KES values.
# These records are replaced by real computed data once properties are added
# in those areas (data_points will become > 0).
_NAIROBI_SEED: List[Dict[str, Any]] = [
    {
        "area_name": "Westlands",
        "city": "Nairobi",
        "avg_rent_studio": 22_000.0,
        "avg_rent_1br": 38_000.0,
        "avg_rent_2br": 60_000.0,
        "avg_rent_3br": 95_000.0,
        "avg_rent_4br_plus": 160_000.0,
        "total_units": 0,
        "vacant_units": 0,
        "vacancy_rate": 0.08,
        "avg_tenancy_months": 18.5,
        "maintenance_rate": 0.18,
        "area_health_score": 83.0,
        "vacancy_trend": [
            {"month": _month_label(5), "rate": 0.10},
            {"month": _month_label(4), "rate": 0.09},
            {"month": _month_label(3), "rate": 0.09},
            {"month": _month_label(2), "rate": 0.08},
            {"month": _month_label(1), "rate": 0.08},
            {"month": _month_label(0), "rate": 0.08},
        ],
    },
    {
        "area_name": "Kilimani",
        "city": "Nairobi",
        "avg_rent_studio": 25_000.0,
        "avg_rent_1br": 42_000.0,
        "avg_rent_2br": 68_000.0,
        "avg_rent_3br": 105_000.0,
        "avg_rent_4br_plus": 175_000.0,
        "total_units": 0,
        "vacant_units": 0,
        "vacancy_rate": 0.06,
        "avg_tenancy_months": 21.0,
        "maintenance_rate": 0.14,
        "area_health_score": 87.0,
        "vacancy_trend": [
            {"month": _month_label(5), "rate": 0.08},
            {"month": _month_label(4), "rate": 0.07},
            {"month": _month_label(3), "rate": 0.07},
            {"month": _month_label(2), "rate": 0.06},
            {"month": _month_label(1), "rate": 0.06},
            {"month": _month_label(0), "rate": 0.06},
        ],
    },
    {
        "area_name": "Kasarani",
        "city": "Nairobi",
        "avg_rent_studio": 10_000.0,
        "avg_rent_1br": 14_000.0,
        "avg_rent_2br": 22_000.0,
        "avg_rent_3br": 32_000.0,
        "avg_rent_4br_plus": 50_000.0,
        "total_units": 0,
        "vacant_units": 0,
        "vacancy_rate": 0.15,
        "avg_tenancy_months": 13.5,
        "maintenance_rate": 0.30,
        "area_health_score": 64.0,
        "vacancy_trend": [
            {"month": _month_label(5), "rate": 0.18},
            {"month": _month_label(4), "rate": 0.17},
            {"month": _month_label(3), "rate": 0.16},
            {"month": _month_label(2), "rate": 0.16},
            {"month": _month_label(1), "rate": 0.15},
            {"month": _month_label(0), "rate": 0.15},
        ],
    },
    {
        "area_name": "Ruaka",
        "city": "Nairobi",
        "avg_rent_studio": 12_000.0,
        "avg_rent_1br": 18_000.0,
        "avg_rent_2br": 28_000.0,
        "avg_rent_3br": 40_000.0,
        "avg_rent_4br_plus": 60_000.0,
        "total_units": 0,
        "vacant_units": 0,
        "vacancy_rate": 0.12,
        "avg_tenancy_months": 15.0,
        "maintenance_rate": 0.24,
        "area_health_score": 70.0,
        "vacancy_trend": [
            {"month": _month_label(5), "rate": 0.14},
            {"month": _month_label(4), "rate": 0.13},
            {"month": _month_label(3), "rate": 0.13},
            {"month": _month_label(2), "rate": 0.12},
            {"month": _month_label(1), "rate": 0.12},
            {"month": _month_label(0), "rate": 0.12},
        ],
    },
    {
        "area_name": "Lang'ata",
        "city": "Nairobi",
        "avg_rent_studio": 13_000.0,
        "avg_rent_1br": 20_000.0,
        "avg_rent_2br": 32_000.0,
        "avg_rent_3br": 48_000.0,
        "avg_rent_4br_plus": 75_000.0,
        "total_units": 0,
        "vacant_units": 0,
        "vacancy_rate": 0.10,
        "avg_tenancy_months": 16.5,
        "maintenance_rate": 0.22,
        "area_health_score": 73.0,
        "vacancy_trend": [
            {"month": _month_label(5), "rate": 0.12},
            {"month": _month_label(4), "rate": 0.11},
            {"month": _month_label(3), "rate": 0.11},
            {"month": _month_label(2), "rate": 0.10},
            {"month": _month_label(1), "rate": 0.10},
            {"month": _month_label(0), "rate": 0.10},
        ],
    },
]


class MarketService:
    """Aggregation and retrieval logic for market intelligence data."""

    # How old area_metrics must be before triggering a re-computation.
    STALE_HOURS = 24

    def __init__(self, db: Session):
        self.db = db

    # ─────────────────────────────────────────────────────────────────────
    # Public API methods
    # ─────────────────────────────────────────────────────────────────────

    def get_or_refresh_all_areas(
        self, city_filter: Optional[str] = None
    ) -> List[AreaSummary]:
        """
        Return area summaries, triggering a re-aggregation for stale areas
        that have real property data (data_points > 0).
        Also ensures seed data exists.
        """
        self._ensure_seeds()
        self._refresh_stale_areas()

        query = self.db.query(AreaMetrics)
        if city_filter:
            query = query.filter(AreaMetrics.city.ilike(f"%{city_filter}%"))
        rows = query.order_by(AreaMetrics.area_health_score.desc().nullslast()).all()
        return [self._row_to_summary(r) for r in rows]

    def get_area_detail(self, area_name: str) -> Optional[AreaDetail]:
        """Return full detail for a named area, refreshing if stale."""
        self._ensure_seeds()

        row = (
            self.db.query(AreaMetrics)
            .filter(AreaMetrics.area_name.ilike(area_name))
            .first()
        )
        if not row:
            return None

        # Refresh if it has real data and is stale
        if row.data_points > 0 and self._is_stale(row):
            self._aggregate_and_upsert(row.area_name)
            self.db.refresh(row)

        return self._row_to_detail(row)

    def get_my_properties_benchmark(
        self, owner_id
    ) -> MyPropertiesBenchmarkResponse:
        """
        Compare each of an owner's properties against the area average rent
        for matching bedroom counts.
        """
        self._ensure_seeds()

        properties = (
            self.db.query(Property)
            .filter(Property.user_id == owner_id)
            .all()
        )

        result_properties: List[PropertyBenchmark] = []
        all_delta_pcts: List[float] = []
        above = 0
        below = 0

        for prop in properties:
            area_label = (prop.area or prop.city or "Unknown").strip()

            area_row = (
                self.db.query(AreaMetrics)
                .filter(AreaMetrics.area_name.ilike(area_label))
                .first()
            )

            unit_benchmarks: List[UnitBenchmark] = []
            prop_has_above = False
            prop_has_below = False

            for unit in prop.units:
                area_avg = self._area_avg_for_bedrooms(area_row, unit.bedrooms or 1)
                delta: Optional[float] = None
                delta_pct: Optional[float] = None
                if area_avg and area_avg > 0 and unit.monthly_rent and unit.monthly_rent > 0:
                    delta = round(unit.monthly_rent - area_avg, 2)
                    delta_pct = round((delta / area_avg) * 100, 1)
                    all_delta_pcts.append(delta_pct)
                    if delta > 0:
                        prop_has_above = True
                    elif delta < 0:
                        prop_has_below = True

                unit_benchmarks.append(
                    UnitBenchmark(
                        unit_id=str(unit.id),
                        unit_number=unit.unit_number,
                        bedrooms=unit.bedrooms or 1,
                        monthly_rent=unit.monthly_rent or 0.0,
                        area_avg_rent=area_avg,
                        delta=delta,
                        delta_pct=delta_pct,
                    )
                )

            if prop_has_above:
                above += 1
            elif prop_has_below:
                below += 1

            result_properties.append(
                PropertyBenchmark(
                    property_id=str(prop.id),
                    property_name=prop.name,
                    area_name=area_label,
                    city=prop.city,
                    area_health_score=area_row.area_health_score if area_row else None,
                    units=unit_benchmarks,
                )
            )

        avg_delta_pct: Optional[float] = (
            round(sum(all_delta_pcts) / len(all_delta_pcts), 1)
            if all_delta_pcts
            else None
        )

        summary = BenchmarkSummary(
            total_properties=len(properties),
            total_units=sum(len(p.units) for p in properties),
            properties_above_market=above,
            properties_below_market=below,
            avg_delta_pct=avg_delta_pct,
        )

        return MyPropertiesBenchmarkResponse(
            properties=result_properties,
            summary=summary,
        )

    # ─────────────────────────────────────────────────────────────────────
    # Seeding
    # ─────────────────────────────────────────────────────────────────────

    def _ensure_seeds(self) -> None:
        """
        Insert seed rows for the five Nairobi reference areas if they don't
        already exist in area_metrics.  Seeded rows have data_points = 0.
        """
        for seed in _NAIROBI_SEED:
            exists = (
                self.db.query(AreaMetrics)
                .filter(AreaMetrics.area_name == seed["area_name"])
                .first()
            )
            if exists:
                continue
            trend_json = json.dumps(seed.get("vacancy_trend", []))
            row = AreaMetrics(
                area_name=seed["area_name"],
                city=seed.get("city"),
                avg_rent_studio=seed.get("avg_rent_studio"),
                avg_rent_1br=seed.get("avg_rent_1br"),
                avg_rent_2br=seed.get("avg_rent_2br"),
                avg_rent_3br=seed.get("avg_rent_3br"),
                avg_rent_4br_plus=seed.get("avg_rent_4br_plus"),
                total_units=seed.get("total_units", 0),
                vacant_units=seed.get("vacant_units", 0),
                vacancy_rate=seed.get("vacancy_rate", 0.0),
                avg_tenancy_months=seed.get("avg_tenancy_months"),
                maintenance_rate=seed.get("maintenance_rate"),
                area_health_score=seed.get("area_health_score"),
                data_points=0,
                vacancy_trend=trend_json,
                last_computed_at=None,
            )
            self.db.add(row)
        try:
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.warning(
                f"[MarketService] Seed insert failed (may already exist): {e}"
            )

    # ─────────────────────────────────────────────────────────────────────
    # Aggregation
    # ─────────────────────────────────────────────────────────────────────

    def _refresh_stale_areas(self) -> None:
        """Re-compute metrics for any area that has real data and is stale."""
        stale_cutoff = datetime.utcnow() - timedelta(hours=self.STALE_HOURS)
        stale_rows = (
            self.db.query(AreaMetrics)
            .filter(
                AreaMetrics.data_points > 0,
                or_(
                    AreaMetrics.last_computed_at == None,  # noqa: E711
                    AreaMetrics.last_computed_at < stale_cutoff,
                ),
            )
            .all()
        )
        for row in stale_rows:
            self._aggregate_and_upsert(row.area_name)

        # Also discover new areas from properties that have no area_metrics row yet
        self._discover_new_areas()

    def _discover_new_areas(self) -> None:
        """
        Find properties whose area/city does not yet have an area_metrics row
        and run aggregation for those new areas.
        """
        properties = self.db.query(Property).all()
        known_areas = {
            r[0].lower()
            for r in self.db.query(AreaMetrics.area_name).all()
        }
        new_areas: set = set()
        for prop in properties:
            label = (prop.area or prop.city or "").strip()
            if label and label.lower() not in known_areas:
                new_areas.add(label)
        for area_name in new_areas:
            self._aggregate_and_upsert(area_name)

    def _aggregate_and_upsert(self, area_name: str) -> None:
        """
        Compute all metrics for `area_name` from real property/unit/tenant data
        and upsert the result into area_metrics.  Skips if no properties found.
        """
        try:
            # Collect properties belonging to this area
            area_props = self.db.query(Property).filter(
                or_(
                    Property.area.ilike(area_name),
                    and_(
                        or_(
                            Property.area == None,  # noqa: E711
                            Property.area == "",
                        ),
                        Property.city.ilike(area_name),
                    ),
                )
            ).all()

            if not area_props:
                return  # Nothing to compute — leave seed data untouched

            property_ids = [p.id for p in area_props]
            now = datetime.utcnow()

            # ── Units ───────────────────────────────────────────────────
            units = (
                self.db.query(Unit)
                .filter(Unit.property_id.in_(property_ids))
                .all()
            )
            total_units = len(units)
            vacant_units = sum(
                1 for u in units
                if (u.status or "vacant").lower() in ("vacant", "maintenance")
            )
            vacancy_rate = (
                vacant_units / total_units if total_units > 0 else 0.0
            )

            # Rent grouped by bedroom count
            rents_by_br: Dict[int, List[float]] = {}
            for u in units:
                if u.monthly_rent and u.monthly_rent > 0:
                    br = u.bedrooms or 1
                    rents_by_br.setdefault(br, []).append(u.monthly_rent)

            avg_rent_studio = _avg_rent_for_bedroom(rents_by_br, 0)
            avg_rent_1br = _avg_rent_for_bedroom(rents_by_br, 1)
            avg_rent_2br = _avg_rent_for_bedroom(rents_by_br, 2)
            avg_rent_3br = _avg_rent_for_bedroom(rents_by_br, 3)
            vals_4plus = [
                v for br, vals in rents_by_br.items() if br >= 4 for v in vals
            ]
            avg_rent_4br_plus = (
                round(sum(vals_4plus) / len(vals_4plus), 2) if vals_4plus else None
            )

            # ── Tenancy duration ────────────────────────────────────────
            tenants = (
                self.db.query(Tenant)
                .filter(Tenant.property_id.in_(property_ids))
                .all()
            )
            durations: List[float] = []
            for t in tenants:
                if not t.lease_start:
                    continue
                end = t.move_out_date or t.lease_end or now
                months = (end - t.lease_start).days / 30.44
                if months > 0:
                    durations.append(months)
            avg_tenancy_months = (
                round(sum(durations) / len(durations), 1) if durations else None
            )

            # ── Maintenance rate ────────────────────────────────────────
            ninety_days_ago = now - timedelta(days=90)
            maint_count = (
                self.db.query(MaintenanceRequest)
                .filter(
                    MaintenanceRequest.property_id.in_(property_ids),
                    MaintenanceRequest.created_at >= ninety_days_ago,
                )
                .count()
            )
            maintenance_rate = (
                round(maint_count / total_units, 3) if total_units > 0 else 0.0
            )

            # ── Vacancy trend (last 6 months) ───────────────────────────
            vacancy_trend = self._compute_vacancy_trend(property_ids, total_units)

            # ── Health score ────────────────────────────────────────────
            data_points = len(area_props)
            area_health_score = _compute_health_score(
                vacancy_rate, avg_tenancy_months, maintenance_rate, data_points
            )

            # ── Upsert ──────────────────────────────────────────────────
            city = area_props[0].city if area_props else None
            row = (
                self.db.query(AreaMetrics)
                .filter(AreaMetrics.area_name.ilike(area_name))
                .first()
            )
            if row:
                row.city = city
                row.avg_rent_studio = avg_rent_studio
                row.avg_rent_1br = avg_rent_1br
                row.avg_rent_2br = avg_rent_2br
                row.avg_rent_3br = avg_rent_3br
                row.avg_rent_4br_plus = avg_rent_4br_plus
                row.total_units = total_units
                row.vacant_units = vacant_units
                row.vacancy_rate = round(vacancy_rate, 4)
                row.avg_tenancy_months = avg_tenancy_months
                row.maintenance_rate = maintenance_rate
                row.area_health_score = area_health_score
                row.data_points = data_points
                row.vacancy_trend = json.dumps(vacancy_trend)
                row.last_computed_at = now
                row.updated_at = now
            else:
                row = AreaMetrics(
                    area_name=area_name,
                    city=city,
                    avg_rent_studio=avg_rent_studio,
                    avg_rent_1br=avg_rent_1br,
                    avg_rent_2br=avg_rent_2br,
                    avg_rent_3br=avg_rent_3br,
                    avg_rent_4br_plus=avg_rent_4br_plus,
                    total_units=total_units,
                    vacant_units=vacant_units,
                    vacancy_rate=round(vacancy_rate, 4),
                    avg_tenancy_months=avg_tenancy_months,
                    maintenance_rate=maintenance_rate,
                    area_health_score=area_health_score,
                    data_points=data_points,
                    vacancy_trend=json.dumps(vacancy_trend),
                    last_computed_at=now,
                )
                self.db.add(row)

            self.db.commit()
            logger.info(
                f"[MarketService] Aggregated '{area_name}': "
                f"{data_points} props, {total_units} units, "
                f"vacancy={vacancy_rate:.1%}, score={area_health_score}"
            )
        except Exception as e:
            self.db.rollback()
            logger.error(
                f"[MarketService] Aggregation failed for '{area_name}': {e}"
            )

    def _compute_vacancy_trend(
        self, property_ids: list, total_units: int
    ) -> List[Dict[str, Any]]:
        """
        Estimate vacancy rate for each of the past 6 calendar months by
        checking how many tenants had an active lease during that month.
        """
        trend = []
        now = datetime.utcnow()
        for months_ago in range(5, -1, -1):
            target = now - timedelta(days=30 * months_ago)
            month_start = target.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            if month_start.month == 12:
                month_end = month_start.replace(year=month_start.year + 1, month=1)
            else:
                month_end = month_start.replace(month=month_start.month + 1)

            occupied = (
                self.db.query(Tenant)
                .filter(
                    Tenant.property_id.in_(property_ids),
                    Tenant.lease_start <= month_end,
                    or_(
                        Tenant.lease_end == None,  # noqa: E711
                        Tenant.lease_end >= month_start,
                    ),
                )
                .count()
            )
            rate = (
                (total_units - min(occupied, total_units)) / total_units
                if total_units > 0
                else 0.0
            )
            trend.append(
                {"month": month_start.strftime("%Y-%m"), "rate": round(rate, 4)}
            )
        return trend

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────

    def _is_stale(self, row: AreaMetrics) -> bool:
        if row.last_computed_at is None:
            return True
        age = datetime.utcnow() - row.last_computed_at
        return age.total_seconds() > self.STALE_HOURS * 3600

    @staticmethod
    def _area_avg_for_bedrooms(
        row: Optional[AreaMetrics], bedrooms: int
    ) -> Optional[float]:
        """Return the area average rent for a given bedroom count."""
        if row is None:
            return None
        if bedrooms == 0:
            return row.avg_rent_studio
        if bedrooms == 1:
            return row.avg_rent_1br
        if bedrooms == 2:
            return row.avg_rent_2br
        if bedrooms == 3:
            return row.avg_rent_3br
        # 4+ bedrooms
        return row.avg_rent_4br_plus

    @staticmethod
    def _overall_avg_rent(row: AreaMetrics) -> Optional[float]:
        """Return a simple average across all bedroom types that have data."""
        vals = [
            v
            for v in [
                row.avg_rent_studio,
                row.avg_rent_1br,
                row.avg_rent_2br,
                row.avg_rent_3br,
                row.avg_rent_4br_plus,
            ]
            if v is not None
        ]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 2)

    def _row_to_summary(self, row: AreaMetrics) -> AreaSummary:
        return AreaSummary(
            area_name=row.area_name,
            city=row.city,
            avg_rent_overall=self._overall_avg_rent(row),
            vacancy_rate=row.vacancy_rate or 0.0,
            avg_tenancy_months=row.avg_tenancy_months,
            area_health_score=row.area_health_score,
            total_units=row.total_units or 0,
            data_points=row.data_points or 0,
            last_computed_at=row.last_computed_at,
        )

    def _row_to_detail(self, row: AreaMetrics) -> AreaDetail:
        trend: List[VacancyTrendPoint] = []
        if row.vacancy_trend:
            try:
                raw = json.loads(row.vacancy_trend)
                trend = [VacancyTrendPoint(**p) for p in raw]
            except (json.JSONDecodeError, TypeError):
                trend = []

        return AreaDetail(
            area_name=row.area_name,
            city=row.city,
            avg_rent_overall=self._overall_avg_rent(row),
            avg_rent_by_type=RentByBedrooms(
                studio=row.avg_rent_studio,
                one_br=row.avg_rent_1br,
                two_br=row.avg_rent_2br,
                three_br=row.avg_rent_3br,
                four_br_plus=row.avg_rent_4br_plus,
            ),
            vacancy_rate=row.vacancy_rate or 0.0,
            total_units=row.total_units or 0,
            vacant_units=row.vacant_units or 0,
            avg_tenancy_months=row.avg_tenancy_months,
            maintenance_rate=row.maintenance_rate,
            area_health_score=row.area_health_score,
            vacancy_trend=trend,
            data_points=row.data_points or 0,
            last_computed_at=row.last_computed_at,
        )
