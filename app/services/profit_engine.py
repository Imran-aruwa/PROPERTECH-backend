"""
Profit Optimization Engine Service
Computes financial snapshots, portfolio P&L, property rankings,
unit profitability, what-if scenarios, and monthly reports.

Uses Decimal for all monetary arithmetic to avoid float rounding errors.
"""
from __future__ import annotations

import calendar
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


def _d(val) -> Decimal:
    """Safely coerce any numeric value to Decimal."""
    if val is None:
        return _ZERO
    return Decimal(str(val))


def _f(val: Decimal) -> float:
    """Decimal → float for JSON serialisation."""
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class ProfitEngine:
    def __init__(self, db: Session, owner_id: uuid.UUID):
        self.db = db
        self.owner_id = owner_id

    # ── Period helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _period_range(period_str: str):
        """Return (first_day, last_day) as date objects for 'YYYY-MM'."""
        year, month = int(period_str[:4]), int(period_str[5:7])
        first = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        last = date(year, month, last_day)
        return first, last

    # ── Core compute ──────────────────────────────────────────────────────────

    def compute_snapshot(
        self,
        period_str: str,
        property_id: Optional[str] = None,
        unit_id: Optional[str] = None,
    ):
        """
        Compute a FinancialSnapshot for (owner, period, property?, unit?).
        UPSERT: always overwrites existing row for the same key combination.
        """
        from app.models.profit_engine import FinancialSnapshot

        first, last = self._period_range(period_str)

        # ── Revenue gross: matched/partial Mpesa transactions ─────────────────
        mpesa_q = text("""
            SELECT COALESCE(SUM(amount), 0)
            FROM mpesa_transactions
            WHERE owner_id = :owner_id
              AND transaction_date >= :start
              AND transaction_date < :end_excl
              AND reconciliation_status NOT IN ('duplicate', 'disputed')
              :prop_filter
        """)
        prop_clause = ""
        params: Dict[str, Any] = {
            "owner_id": str(self.owner_id),
            "start": datetime(first.year, first.month, 1),
            "end_excl": datetime(last.year, last.month, last.day) + timedelta(days=1),
        }
        if property_id:
            prop_clause = "AND property_id = :property_id"
            params["property_id"] = property_id
        if unit_id:
            prop_clause += " AND unit_id = :unit_id"
            params["unit_id"] = unit_id

        # Build query with proper clause substitution
        mpesa_sql = """
            SELECT COALESCE(SUM(amount), 0)
            FROM mpesa_transactions
            WHERE owner_id = :owner_id
              AND transaction_date >= :start
              AND transaction_date < :end_excl
              AND reconciliation_status NOT IN ('duplicate', 'disputed')
        """
        if property_id:
            mpesa_sql += " AND property_id = :property_id"
        if unit_id:
            mpesa_sql += " AND unit_id = :unit_id"

        revenue_gross = _d(self.db.execute(text(mpesa_sql), params).scalar())

        # ── Late fees: Mpesa transactions where account_reference contains LATE ─
        late_sql = mpesa_sql + " AND UPPER(account_reference) LIKE '%LATE%'"
        late_fees = _d(self.db.execute(text(late_sql), params).scalar())

        # ── Revenue expected: sum of active lease rents for this period ────────
        lease_sql = """
            SELECT COALESCE(SUM(l.rent_amount), 0)
            FROM leases l
            WHERE l.owner_id = :owner_id
              AND l.status = 'active'
              AND l.start_date <= :period_last
              AND l.end_date >= :period_first
        """
        lease_params: Dict[str, Any] = {
            "owner_id": str(self.owner_id),
            "period_first": first,
            "period_last": last,
        }
        if property_id:
            lease_sql += " AND l.property_id = :property_id"
            lease_params["property_id"] = property_id
        if unit_id:
            lease_sql += " AND l.unit_id = :unit_id"
            lease_params["unit_id"] = unit_id

        revenue_expected = _d(self.db.execute(text(lease_sql), lease_params).scalar())

        # ── Maintenance cost: paid vendor jobs completed in period ─────────────
        maint_sql = """
            SELECT COALESCE(SUM(final_amount), 0)
            FROM vendor_jobs
            WHERE owner_id = :owner_id
              AND paid = true
              AND completed_at >= :start
              AND completed_at < :end_excl
        """
        maint_params: Dict[str, Any] = {
            "owner_id": str(self.owner_id),
            "start": datetime(first.year, first.month, 1),
            "end_excl": datetime(last.year, last.month, last.day) + timedelta(days=1),
        }
        if property_id:
            maint_sql += " AND property_id = :property_id"
            maint_params["property_id"] = property_id
        if unit_id:
            maint_sql += " AND unit_id = :unit_id"
            maint_params["unit_id"] = unit_id

        maintenance_cost = _d(self.db.execute(text(maint_sql), maint_params).scalar())

        # ── Other expenses from expense_records (non-maintenance) ──────────────
        exp_sql = """
            SELECT COALESCE(SUM(amount), 0)
            FROM expense_records
            WHERE owner_id = :owner_id
              AND expense_date >= :period_first
              AND expense_date <= :period_last
              AND category != 'maintenance'
        """
        exp_params: Dict[str, Any] = {
            "owner_id": str(self.owner_id),
            "period_first": first,
            "period_last": last,
        }
        if property_id:
            exp_sql += " AND property_id = :property_id"
            exp_params["property_id"] = property_id
        if unit_id:
            exp_sql += " AND unit_id = :unit_id"
            exp_params["unit_id"] = unit_id

        other_expenses = _d(self.db.execute(text(exp_sql), exp_params).scalar())

        # ── Derived metrics ────────────────────────────────────────────────────
        vacancy_loss = max(_ZERO, revenue_expected - revenue_gross)
        noi = revenue_gross - maintenance_cost - other_expenses + late_fees

        if revenue_expected > _ZERO:
            collection_rate = (revenue_gross / revenue_expected * _HUNDRED).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            collection_rate = _ZERO

        occupancy_rate = self._occupancy_rate(property_id, unit_id, first, last)

        # ── UPSERT ─────────────────────────────────────────────────────────────
        owner_uuid = self.owner_id
        prop_uuid = uuid.UUID(property_id) if property_id else None
        unit_uuid = uuid.UUID(unit_id) if unit_id else None

        existing = (
            self.db.query(FinancialSnapshot)
            .filter(
                FinancialSnapshot.owner_id == owner_uuid,
                FinancialSnapshot.snapshot_period == period_str,
                FinancialSnapshot.property_id == prop_uuid,
                FinancialSnapshot.unit_id == unit_uuid,
            )
            .first()
        )

        if existing:
            snap = existing
        else:
            snap = FinancialSnapshot(
                id=uuid.uuid4(),
                owner_id=owner_uuid,
                property_id=prop_uuid,
                unit_id=unit_uuid,
                snapshot_period=period_str,
            )
            self.db.add(snap)

        snap.revenue_gross = _f(revenue_gross)
        snap.revenue_expected = _f(revenue_expected)
        snap.vacancy_loss = _f(vacancy_loss)
        snap.maintenance_cost = _f(maintenance_cost)
        snap.other_expenses = _f(other_expenses)
        snap.late_fees_collected = _f(late_fees)
        snap.net_operating_income = _f(noi)
        snap.occupancy_rate = _f(occupancy_rate)
        snap.collection_rate = _f(collection_rate)
        snap.computed_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(snap)
        return snap

    def _occupancy_rate(
        self,
        property_id: Optional[str],
        unit_id: Optional[str],
        period_first: date,
        period_last: date,
    ) -> Decimal:
        """Compute occupancy rate (occupied/total × 100) for the given scope."""
        try:
            if unit_id:
                # Single unit: check if there's an active lease in the period
                r = self.db.execute(text("""
                    SELECT COUNT(*) FROM leases
                    WHERE unit_id = :unit_id
                      AND owner_id = :owner_id
                      AND status = 'active'
                      AND start_date <= :period_last
                      AND end_date >= :period_first
                """), {
                    "unit_id": unit_id, "owner_id": str(self.owner_id),
                    "period_first": period_first, "period_last": period_last,
                }).scalar() or 0
                return _HUNDRED if r > 0 else _ZERO

            if property_id:
                total = self.db.execute(text(
                    "SELECT COUNT(*) FROM units WHERE property_id = :pid"
                ), {"pid": property_id}).scalar() or 0
                if not total:
                    return _ZERO
                occupied = self.db.execute(text("""
                    SELECT COUNT(DISTINCT l.unit_id) FROM leases l
                    JOIN units u ON u.id = l.unit_id
                    WHERE u.property_id = :pid
                      AND l.owner_id = :owner_id
                      AND l.status = 'active'
                      AND l.start_date <= :period_last
                      AND l.end_date >= :period_first
                """), {
                    "pid": property_id, "owner_id": str(self.owner_id),
                    "period_first": period_first, "period_last": period_last,
                }).scalar() or 0
            else:
                # Portfolio
                total = self.db.execute(text("""
                    SELECT COUNT(u.id) FROM units u
                    JOIN properties p ON p.id = u.property_id
                    WHERE p.user_id = :owner_id
                """), {"owner_id": str(self.owner_id)}).scalar() or 0
                if not total:
                    return _ZERO
                occupied = self.db.execute(text("""
                    SELECT COUNT(DISTINCT l.unit_id) FROM leases l
                    JOIN units u ON u.id = l.unit_id
                    JOIN properties p ON p.id = u.property_id
                    WHERE p.user_id = :owner_id
                      AND l.owner_id = :owner_id
                      AND l.status = 'active'
                      AND l.start_date <= :period_last
                      AND l.end_date >= :period_first
                """), {
                    "owner_id": str(self.owner_id),
                    "period_first": period_first, "period_last": period_last,
                }).scalar() or 0

            if total == 0:
                return _ZERO
            return (_d(occupied) / _d(total) * _HUNDRED).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except Exception as exc:
            logger.warning(f"[profit] _occupancy_rate failed: {exc}")
            return _ZERO

    # ── Portfolio P&L ─────────────────────────────────────────────────────────

    def get_portfolio_pnl(self, months: int = 12) -> Dict[str, Any]:
        """Return last N months of portfolio-level snapshots plus YTD totals."""
        today = date.today()
        period_list = []
        for i in range(months - 1, -1, -1):
            yr = today.year
            mo = today.month - i
            while mo <= 0:
                mo += 12
                yr -= 1
            period_list.append(f"{yr:04d}-{mo:02d}")

        monthly_data = []
        total_rev = _ZERO
        total_exp = _ZERO
        total_noi = _ZERO
        total_occ = _ZERO
        total_col = _ZERO
        best_noi, worst_noi = None, None
        best_month, worst_month = None, None

        for p in period_list:
            try:
                snap = self.compute_snapshot(p)
            except Exception as exc:
                logger.warning(f"[profit] pnl compute_snapshot({p}) failed: {exc}")
                continue

            noi_d = _d(snap.net_operating_income)
            rev_d = _d(snap.revenue_gross)
            exp_d = _d(snap.maintenance_cost) + _d(snap.other_expenses)

            total_rev += rev_d
            total_exp += exp_d
            total_noi += noi_d
            total_occ += _d(snap.occupancy_rate)
            total_col += _d(snap.collection_rate)

            if best_noi is None or noi_d > best_noi:
                best_noi = noi_d
                best_month = p
            if worst_noi is None or noi_d < worst_noi:
                worst_noi = noi_d
                worst_month = p

            monthly_data.append({
                "period": p,
                "revenue_gross": _f(rev_d),
                "total_expenses": _f(exp_d),
                "net_operating_income": _f(noi_d),
                "occupancy_rate": _f(_d(snap.occupancy_rate)),
                "collection_rate": _f(_d(snap.collection_rate)),
                "vacancy_loss": _f(_d(snap.vacancy_loss)),
            })

        n = max(len(monthly_data), 1)
        return {
            "months": monthly_data,
            "total_revenue_ytd": _f(total_rev),
            "total_expenses_ytd": _f(total_exp),
            "total_noi_ytd": _f(total_noi),
            "avg_occupancy_ytd": _f(total_occ / n),
            "avg_collection_rate_ytd": _f(total_col / n),
            "best_month": best_month,
            "worst_month": worst_month,
        }

    # ── Property Rankings ─────────────────────────────────────────────────────

    def get_property_rankings(self, period_str: str) -> List[Dict[str, Any]]:
        """Rank all owner properties by NOI for the given period."""
        from app.models.property import Property

        year = int(period_str[:4])
        month = int(period_str[5:7])
        mo_prev = month - 1 if month > 1 else 12
        yr_prev = year if month > 1 else year - 1
        prev_period = f"{yr_prev:04d}-{mo_prev:02d}"

        properties = (
            self.db.query(Property)
            .filter(Property.user_id == self.owner_id)
            .all()
        )

        rankings = []
        for prop in properties:
            pid = str(prop.id)
            try:
                snap = self.compute_snapshot(period_str, property_id=pid)
            except Exception:
                continue

            # Count units
            unit_count = self.db.execute(text(
                "SELECT COUNT(*) FROM units WHERE property_id = :pid"
            ), {"pid": pid}).scalar() or 0

            # Annual rent potential for yield
            annual_rent = self.db.execute(text("""
                SELECT COALESCE(SUM(monthly_rent), 0) * 12
                FROM units WHERE property_id = :pid
            """), {"pid": pid}).scalar() or 0

            annual_rent_d = _d(annual_rent)
            noi_d = _d(snap.net_operating_income)

            # Annualised yield
            yield_pct = _ZERO
            if annual_rent_d > _ZERO:
                yield_pct = (noi_d * 12 / annual_rent_d * _HUNDRED).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

            # vs last month NOI change
            vs_change = _ZERO
            try:
                prev_snap = self.compute_snapshot(prev_period, property_id=pid)
                prev_noi = _d(prev_snap.net_operating_income)
                if prev_noi != _ZERO:
                    vs_change = ((noi_d - prev_noi) / abs(prev_noi) * _HUNDRED).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
            except Exception:
                pass

            rankings.append({
                "property_id": pid,
                "property_name": prop.name or "",
                "unit_count": unit_count,
                "revenue_gross": _f(_d(snap.revenue_gross)),
                "maintenance_cost": _f(_d(snap.maintenance_cost)),
                "noi": _f(noi_d),
                "yield_pct": _f(yield_pct),
                "occupancy_rate": _f(_d(snap.occupancy_rate)),
                "collection_rate": _f(_d(snap.collection_rate)),
                "rank": 0,  # assigned below
                "vs_last_month_noi_change_pct": _f(vs_change),
            })

        # Sort by NOI desc and assign rank
        rankings.sort(key=lambda x: x["noi"], reverse=True)
        for i, r in enumerate(rankings, 1):
            r["rank"] = i

        return rankings

    # ── Unit Profitability ────────────────────────────────────────────────────

    def get_unit_profitability(
        self, property_id: str, period_str: str
    ) -> List[Dict[str, Any]]:
        """Per-unit P&L for a given property and period."""
        from app.models.property import Unit

        units = (
            self.db.query(Unit)
            .filter(Unit.property_id == uuid.UUID(property_id))
            .all()
        )

        results = []
        first, last = self._period_range(period_str)
        days_in_month = (last - first).days + 1

        for unit in units:
            uid = str(unit.id)
            try:
                snap = self.compute_snapshot(period_str, property_id=property_id, unit_id=uid)
            except Exception:
                continue

            noi_d = _d(snap.net_operating_income)
            rev_d = _d(snap.revenue_gross)
            maint_d = _d(snap.maintenance_cost)
            monthly_rent = _d(unit.monthly_rent or 0)

            # Occupancy days: occupied if active lease exists
            occ_days = 0
            try:
                has_lease = self.db.execute(text("""
                    SELECT COUNT(*) FROM leases
                    WHERE unit_id = :uid AND owner_id = :oid
                      AND status = 'active'
                      AND start_date <= :last
                      AND end_date >= :first
                """), {
                    "uid": uid, "oid": str(self.owner_id),
                    "first": first, "last": last,
                }).scalar() or 0
                occ_days = days_in_month if has_lease else 0
            except Exception:
                pass

            # Recommendation logic
            rev_ratio = (maint_d / monthly_rent * _HUNDRED) if monthly_rent > _ZERO else _ZERO
            if occ_days == 0:
                recommendation = "vacancy dragging returns — review pricing"
            elif rev_ratio > 40:
                recommendation = "high maintenance costs — review vendor spend"
            elif noi_d > _ZERO and noi_d < monthly_rent * Decimal("0.3"):
                recommendation = "underperforming — consider rent increase"
            else:
                recommendation = "performing well"

            results.append({
                "unit_id": uid,
                "unit_number": unit.unit_number or "",
                "monthly_rent": _f(monthly_rent),
                "revenue_collected": _f(rev_d),
                "maintenance_cost": _f(maint_d),
                "noi": _f(noi_d),
                "occupancy_days": occ_days,
                "is_profitable": noi_d > _ZERO,
                "recommendation": recommendation,
            })

        return results

    # ── What-If Scenarios ─────────────────────────────────────────────────────

    def run_whatif_scenario(
        self, scenario_type: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Pure computation — no DB writes. Returns results in <500ms."""
        if scenario_type == "rent_increase":
            return self._whatif_rent_increase(params)
        elif scenario_type == "fill_vacancy":
            return self._whatif_fill_vacancy(params)
        elif scenario_type == "reduce_maintenance":
            return self._whatif_reduce_maintenance(params)
        elif scenario_type == "expense_category_shift":
            return self._whatif_expense_shift(params)
        else:
            raise ValueError(f"Unknown scenario_type: {scenario_type}")

    def _whatif_rent_increase(self, params: Dict[str, Any]) -> Dict[str, Any]:
        property_id = params.get("property_id")
        increase_pct = _d(params.get("increase_pct", 10))

        if property_id:
            rows = self.db.execute(text(
                "SELECT COALESCE(SUM(monthly_rent), 0) FROM units WHERE property_id = :pid"
            ), {"pid": property_id}).scalar() or 0
        else:
            rows = self.db.execute(text("""
                SELECT COALESCE(SUM(u.monthly_rent), 0)
                FROM units u
                JOIN properties p ON p.id = u.property_id
                WHERE p.user_id = :oid
            """), {"oid": str(self.owner_id)}).scalar() or 0

        current_monthly = _d(rows)
        current_annual = current_monthly * 12
        new_monthly = current_monthly * (1 + increase_pct / _HUNDRED)
        new_annual = new_monthly * 12
        delta = new_annual - current_annual

        vacancy_risk_pct = _ZERO
        if increase_pct > 10:
            vacancy_risk_pct = _d("5")  # 5% vacancy risk if increase > 10%

        # Net projected gain after vacancy risk
        net_gain = delta * (1 - vacancy_risk_pct / _HUNDRED)

        return {
            "current_annual_revenue": _f(current_annual),
            "projected_annual_revenue": _f(new_annual),
            "revenue_delta": _f(delta),
            "vacancy_risk_pct": _f(vacancy_risk_pct),
            "net_projected_gain": _f(net_gain),
        }

    def _whatif_fill_vacancy(self, params: Dict[str, Any]) -> Dict[str, Any]:
        unit_id = params.get("unit_id")
        estimated_rent = _d(params.get("estimated_rent", 0))
        fitout_cost = _d(params.get("fitout_cost", 0))

        monthly_gain = estimated_rent
        annual_gain = monthly_gain * 12
        months_breakeven = _ZERO
        if monthly_gain > _ZERO and fitout_cost > _ZERO:
            months_breakeven = (fitout_cost / monthly_gain).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            )

        return {
            "monthly_revenue_gain": _f(monthly_gain),
            "annual_revenue_gain": _f(annual_gain),
            "months_to_break_even_on_fitout": _f(months_breakeven),
        }

    def _whatif_reduce_maintenance(self, params: Dict[str, Any]) -> Dict[str, Any]:
        property_id = params.get("property_id")
        reduction_pct = _d(params.get("reduction_pct", 20))

        # Last 12 months maintenance spend
        today = date.today()
        start_12m = date(today.year - 1, today.month, 1)

        maint_sql = """
            SELECT COALESCE(SUM(final_amount), 0)
            FROM vendor_jobs
            WHERE owner_id = :oid
              AND paid = true
              AND completed_at >= :start
        """
        maint_params: Dict[str, Any] = {
            "oid": str(self.owner_id),
            "start": datetime(start_12m.year, start_12m.month, 1),
        }
        if property_id:
            maint_sql += " AND property_id = :pid"
            maint_params["pid"] = property_id

        current_annual = _d(self.db.execute(text(maint_sql), maint_params).scalar() or 0)
        projected = current_annual * (1 - reduction_pct / _HUNDRED)
        savings = current_annual - projected

        return {
            "current_annual_maintenance": _f(current_annual),
            "projected_annual_maintenance": _f(projected),
            "annual_savings": _f(savings),
        }

    def _whatif_expense_shift(self, params: Dict[str, Any]) -> Dict[str, Any]:
        property_id = params.get("property_id")
        category = params.get("category", "other")
        new_budget = _d(params.get("new_budget", 0))

        today = date.today()
        start_12m = date(today.year - 1, today.month, 1)

        exp_sql = """
            SELECT COALESCE(SUM(amount), 0)
            FROM expense_records
            WHERE owner_id = :oid
              AND category = :cat
              AND expense_date >= :start
        """
        exp_params: Dict[str, Any] = {
            "oid": str(self.owner_id),
            "cat": category,
            "start": start_12m,
        }
        if property_id:
            exp_sql += " AND property_id = :pid"
            exp_params["pid"] = property_id

        current_annual = _d(self.db.execute(text(exp_sql), exp_params).scalar() or 0)
        current_monthly = (current_annual / 12).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        new_annual = new_budget * 12
        noi_impact = current_annual - new_annual  # positive = savings

        return {
            "current_monthly_avg": _f(current_monthly),
            "current_annual": _f(current_annual),
            "new_monthly_budget": _f(new_budget),
            "new_annual": _f(new_annual),
            "noi_impact": _f(noi_impact),
        }

    # ── Monthly Report ────────────────────────────────────────────────────────

    def generate_monthly_report(self, period_str: str) -> Dict[str, Any]:
        """
        Compile a full structured report.
        Called from a BackgroundTask after the FinancialReport row is created.
        """
        from app.models.property import Property, Unit
        from app.models.user import User

        owner = self.db.query(User).filter(User.id == self.owner_id).first()
        owner_name = (
            f"{getattr(owner, 'first_name', '') or ''} "
            f"{getattr(owner, 'last_name', '') or ''}"
        ).strip() or getattr(owner, "email", "Owner")

        # Portfolio snapshot
        portfolio_snap = self.compute_snapshot(period_str)

        # Previous month
        year, month = int(period_str[:4]), int(period_str[5:7])
        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        prev_period = f"{prev_year:04d}-{prev_month:02d}"
        prev_snap = self.compute_snapshot(prev_period)

        def _pct_change(curr, prev_val):
            c, p = _d(curr), _d(prev_val)
            if p == _ZERO:
                return 0.0
            return _f((c - p) / abs(p) * _HUNDRED)

        # Property rankings
        rankings = self.get_property_rankings(period_str)

        # Unit profitability per property
        properties = (
            self.db.query(Property)
            .filter(Property.user_id == self.owner_id)
            .all()
        )
        unit_profitability: Dict[str, List] = {}
        for prop in properties:
            pid = str(prop.id)
            unit_profitability[prop.name or pid] = self.get_unit_profitability(pid, period_str)

        # Expense breakdown by category
        first, last = self._period_range(period_str)
        exp_by_cat = self.db.execute(text("""
            SELECT category, COALESCE(SUM(amount), 0)
            FROM expense_records
            WHERE owner_id = :oid
              AND expense_date >= :first
              AND expense_date <= :last
            GROUP BY category
        """), {"oid": str(self.owner_id), "first": first, "last": last}).fetchall()

        expense_breakdown = {row[0]: _f(_d(row[1])) for row in exp_by_cat}
        expense_breakdown["maintenance"] = _f(_d(portfolio_snap.maintenance_cost))

        # Income breakdown by property
        income_by_property = {}
        for r in rankings:
            income_by_property[r["property_name"]] = r["revenue_gross"]

        # Top vendors by spend
        top_vendors = self.db.execute(text("""
            SELECT v.name, COALESCE(SUM(vj.final_amount), 0) as spend
            FROM vendor_jobs vj
            JOIN vendors v ON v.id = vj.vendor_id
            WHERE vj.owner_id = :oid
              AND vj.paid = true
              AND vj.completed_at >= :start
              AND vj.completed_at < :end_excl
            GROUP BY v.name
            ORDER BY spend DESC
            LIMIT 5
        """), {
            "oid": str(self.owner_id),
            "start": datetime(first.year, first.month, 1),
            "end_excl": datetime(last.year, last.month, last.day) + timedelta(days=1),
        }).fetchall()

        top_vendors_list = [{"vendor": row[0], "spend": _f(_d(row[1]))} for row in top_vendors]

        # Top issues & recommendations
        issues = []
        recommendations = []

        for r in rankings:
            if r["collection_rate"] < 80:
                issues.append({
                    "severity": "high",
                    "message": (
                        f"Collection rate for {r['property_name']} is "
                        f"{r['collection_rate']:.0f}% — review overdue tenants."
                    ),
                    "link": "/owner/mpesa",
                })
                recommendations.append(
                    f"Collection rate for {r['property_name']} is {r['collection_rate']:.0f}% "
                    f"— review overdue tenants and consider enabling autopilot payment enforcement."
                )

            rev = r["revenue_gross"]
            maint = r["maintenance_cost"]
            if rev > 0 and maint / rev * 100 > 40:
                pct = round(maint / rev * 100, 1)
                issues.append({
                    "severity": "medium",
                    "message": (
                        f"Maintenance costs for {r['property_name']} are "
                        f"{pct}% of revenue."
                    ),
                    "link": "/owner/vendors",
                })
                recommendations.append(
                    f"Maintenance costs for {r['property_name']} are {pct}% of revenue "
                    f"— review vendor pricing and consider preferred vendor agreements."
                )

        # Vacant units > 14 days
        vacant_units = self.db.execute(text("""
            SELECT u.unit_number, u.monthly_rent, p.name,
                   EXTRACT(DAY FROM NOW() - u.updated_at) as days_vacant
            FROM units u
            JOIN properties p ON p.id = u.property_id
            WHERE p.user_id = :oid AND u.status = 'vacant'
              AND u.updated_at < NOW() - INTERVAL '14 days'
            LIMIT 5
        """), {"oid": str(self.owner_id)}).fetchall()

        for vu in vacant_units:
            days = int(vu[3] or 14)
            issues.append({
                "severity": "medium",
                "message": f"Unit {vu[0]} has been vacant {days} days.",
                "link": "/owner/vacancy",
            })
            recommendations.append(
                f"Unit {vu[0]} has been vacant {days} days — current asking rent of "
                f"KES {float(vu[1] or 0):,.0f} may be above market. Review the Rent Optimizer."
            )

        # Portfolio-wide occupancy
        occ = float(portfolio_snap.occupancy_rate)
        if occ < 85:
            issues.append({
                "severity": "medium",
                "message": f"Portfolio occupancy is {occ:.0f}%.",
                "link": "/owner/vacancy",
            })
            recommendations.append(
                f"Portfolio occupancy is {occ:.0f}% "
                f"— activate Vacancy Prevention campaigns for at-risk leases."
            )

        # NOI decline 2 months in a row
        two_months_ago_month = prev_month - 1 if prev_month > 1 else 12
        two_months_ago_year = prev_year if prev_month > 1 else prev_year - 1
        two_periods_ago = f"{two_months_ago_year:04d}-{two_months_ago_month:02d}"
        try:
            snap_2m = self.compute_snapshot(two_periods_ago)
            if (
                float(portfolio_snap.net_operating_income) < float(prev_snap.net_operating_income)
                and float(prev_snap.net_operating_income) < float(snap_2m.net_operating_income)
            ):
                recommendations.append(
                    "Net operating income has declined for 2 consecutive months "
                    "— run a what-if scenario to identify the highest-impact lever."
                )
        except Exception:
            pass

        # Targets vs actuals
        targets_status = self.get_targets_status()

        report = {
            "cover": {
                "owner_name": owner_name,
                "period": period_str,
                "generated_at": datetime.utcnow().isoformat(),
            },
            "executive_summary": {
                "gross_revenue": _f(_d(portfolio_snap.revenue_gross)),
                "total_expenses": _f(_d(portfolio_snap.maintenance_cost) + _d(portfolio_snap.other_expenses)),
                "net_operating_income": _f(_d(portfolio_snap.net_operating_income)),
                "occupancy_rate": _f(_d(portfolio_snap.occupancy_rate)),
                "collection_rate": _f(_d(portfolio_snap.collection_rate)),
                "vacancy_loss": _f(_d(portfolio_snap.vacancy_loss)),
                "vs_prev_revenue_pct": _pct_change(portfolio_snap.revenue_gross, prev_snap.revenue_gross),
                "vs_prev_noi_pct": _pct_change(portfolio_snap.net_operating_income, prev_snap.net_operating_income),
                "vs_prev_occupancy_pts": _f(_d(portfolio_snap.occupancy_rate) - _d(prev_snap.occupancy_rate)),
            },
            "property_rankings": rankings,
            "top_issues": issues[:5],
            "income_breakdown": {
                "by_property": income_by_property,
                "late_fees": _f(_d(portfolio_snap.late_fees_collected)),
                "total": _f(_d(portfolio_snap.revenue_gross)),
            },
            "expense_breakdown": {
                "by_category": expense_breakdown,
                "top_vendors": top_vendors_list,
                "total": _f(_d(portfolio_snap.maintenance_cost) + _d(portfolio_snap.other_expenses)),
            },
            "unit_profitability": unit_profitability,
            "targets_vs_actuals": targets_status,
            "recommendations": recommendations[:5],
        }
        return report

    # ── Targets Status ────────────────────────────────────────────────────────

    def get_targets_status(self) -> List[Dict[str, Any]]:
        """Compare each profit_target against the current period's actuals."""
        from app.models.profit_engine import ProfitTarget
        from app.models.property import Property

        today = date.today()
        period_str = f"{today.year:04d}-{today.month:02d}"

        targets = (
            self.db.query(ProfitTarget)
            .filter(ProfitTarget.owner_id == self.owner_id)
            .all()
        )

        results = []
        for t in targets:
            pid = str(t.property_id) if t.property_id else None
            try:
                snap = self.compute_snapshot(period_str, property_id=pid)
            except Exception:
                continue

            target_val = _d(t.target_value)

            if t.target_type == "noi":
                actual = _d(snap.net_operating_income)
                if t.period == "annual":
                    actual = actual * 12
            elif t.target_type == "occupancy":
                actual = _d(snap.occupancy_rate)
            elif t.target_type == "collection_rate":
                actual = _d(snap.collection_rate)
            elif t.target_type == "yield":
                # Annualised NOI / annual rent
                annual_rent = _ZERO
                if pid:
                    r = self.db.execute(text(
                        "SELECT COALESCE(SUM(monthly_rent), 0) * 12 FROM units WHERE property_id = :pid"
                    ), {"pid": pid}).scalar() or 0
                    annual_rent = _d(r)
                actual = (_d(snap.net_operating_income) * 12 / annual_rent * _HUNDRED
                          if annual_rent > _ZERO else _ZERO)
            else:
                actual = _ZERO

            gap = actual - target_val
            pct_achieved = (actual / target_val * _HUNDRED) if target_val > _ZERO else _ZERO

            if pct_achieved >= 95:
                status = "on_track"
            elif pct_achieved >= 70:
                status = "at_risk"
            else:
                status = "missed"

            # Property name
            prop_name = None
            if t.property_id:
                prop = self.db.query(Property).filter(Property.id == t.property_id).first()
                prop_name = prop.name if prop else None

            results.append({
                "id": str(t.id),
                "target_type": t.target_type,
                "target_value": _f(target_val),
                "period": t.period,
                "property_id": pid,
                "property_name": prop_name,
                "actual_value": _f(actual),
                "gap": _f(gap),
                "pct_achieved": _f(pct_achieved),
                "status": status,
            })

        return results
