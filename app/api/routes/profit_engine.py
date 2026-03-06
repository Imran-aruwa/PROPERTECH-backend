"""
Profit Optimization Engine Routes
Prefix: /api/profit
All endpoints require JWT auth + owner/admin role (premium gate).
generate_monthly_report runs as a BackgroundTask — returns {report_id, status} immediately.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserRole
from app.schemas.profit_engine import (
    ExpenseCreate,
    ExpenseResponse,
    ExpenseUpdate,
    GenerateReportRequest,
    PortfolioPnlResponse,
    PropertyRankingResponse,
    ReportDetailResponse,
    ReportListResponse,
    SnapshotResponse,
    TargetCreate,
    TargetResponse,
    TargetStatusResponse,
    TargetUpdate,
    UnitProfitabilityResponse,
    WhatIfRequest,
    WhatIfResponse,
)
from app.services.profit_engine import ProfitEngine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Profit Engine"])


# ── Auth gate ──────────────────────────────────────────────────────────────────

def require_owner(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in (UserRole.OWNER, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Access restricted to property owners.")
    return current_user


# ── Background report builder ──────────────────────────────────────────────────

def _build_report_bg(report_id: str, period_str: str, owner_id: str):
    """Background task: compute report and update the FinancialReport row."""
    from app.database import SessionLocal
    from app.models.profit_engine import FinancialReport
    from datetime import datetime
    import json

    db = SessionLocal()
    try:
        owner_uuid = uuid.UUID(owner_id)
        engine = ProfitEngine(db, owner_uuid)
        data = engine.generate_monthly_report(period_str)

        report = db.query(FinancialReport).filter(
            FinancialReport.id == uuid.UUID(report_id)
        ).first()
        if report:
            report.data = data
            report.status = "complete"
            report.generated_at = datetime.utcnow()
            db.commit()
            logger.info(f"[profit] Report {report_id} for {period_str} complete")
    except Exception as exc:
        logger.error(f"[profit] Report {report_id} generation failed: {exc}", exc_info=True)
        db = SessionLocal()
        try:
            report = db.query(FinancialReport).filter(
                FinancialReport.id == uuid.UUID(report_id)
            ).first()
            if report:
                report.status = "failed"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


# ── Snapshots ──────────────────────────────────────────────────────────────────

@router.get("/profit/snapshots", response_model=SnapshotResponse)
def get_snapshot(
    period: Optional[str] = Query(None, description="YYYY-MM, defaults to current month"),
    property_id: Optional[str] = Query(None),
    unit_id: Optional[str] = Query(None),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    if not period:
        today = date.today()
        period = f"{today.year:04d}-{today.month:02d}"
    engine = ProfitEngine(db, current_user.id)
    try:
        snap = engine.compute_snapshot(period, property_id=property_id, unit_id=unit_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return SnapshotResponse(
        id=str(snap.id),
        owner_id=str(snap.owner_id),
        property_id=str(snap.property_id) if snap.property_id else None,
        unit_id=str(snap.unit_id) if snap.unit_id else None,
        snapshot_period=snap.snapshot_period,
        revenue_gross=float(snap.revenue_gross or 0),
        revenue_expected=float(snap.revenue_expected or 0),
        vacancy_loss=float(snap.vacancy_loss or 0),
        maintenance_cost=float(snap.maintenance_cost or 0),
        other_expenses=float(snap.other_expenses or 0),
        late_fees_collected=float(snap.late_fees_collected or 0),
        net_operating_income=float(snap.net_operating_income or 0),
        occupancy_rate=float(snap.occupancy_rate or 0),
        collection_rate=float(snap.collection_rate or 0),
        computed_at=snap.computed_at,
        created_at=snap.created_at,
    )


# ── Portfolio P&L ──────────────────────────────────────────────────────────────

@router.get("/profit/portfolio-pnl")
def get_portfolio_pnl(
    months: int = Query(12, ge=1, le=24),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    engine = ProfitEngine(db, current_user.id)
    try:
        return engine.get_portfolio_pnl(months=months)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Property Rankings ──────────────────────────────────────────────────────────

@router.get("/profit/property-rankings")
def get_property_rankings(
    period: Optional[str] = Query(None),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    if not period:
        today = date.today()
        period = f"{today.year:04d}-{today.month:02d}"
    engine = ProfitEngine(db, current_user.id)
    try:
        return engine.get_property_rankings(period)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Unit Profitability ─────────────────────────────────────────────────────────

@router.get("/profit/unit-profitability")
def get_unit_profitability(
    property_id: str = Query(...),
    period: Optional[str] = Query(None),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    if not period:
        today = date.today()
        period = f"{today.year:04d}-{today.month:02d}"
    engine = ProfitEngine(db, current_user.id)
    try:
        return engine.get_unit_profitability(property_id, period)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── What-If ────────────────────────────────────────────────────────────────────

@router.post("/profit/whatif")
def run_whatif(
    body: WhatIfRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    engine = ProfitEngine(db, current_user.id)
    try:
        result = engine.run_whatif_scenario(body.scenario_type, body.params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"scenario_type": body.scenario_type, "result": result}


# ── Reports ────────────────────────────────────────────────────────────────────

@router.post("/profit/reports/generate", status_code=202)
def generate_report(
    body: GenerateReportRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """
    Accepts request immediately, computes in background.
    Poll GET /api/profit/reports/{id} until status == 'complete'.
    """
    from app.models.profit_engine import FinancialReport
    from datetime import datetime

    report = FinancialReport(
        id=uuid.uuid4(),
        owner_id=current_user.id,
        report_period=body.period_str,
        report_type=body.report_type,
        status="generating",
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    background_tasks.add_task(
        _build_report_bg,
        str(report.id),
        body.period_str,
        str(current_user.id),
    )

    return {"report_id": str(report.id), "status": "generating"}


@router.get("/profit/reports", response_model=List[ReportListResponse])
def list_reports(
    report_type: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    from app.models.profit_engine import FinancialReport

    q = db.query(FinancialReport).filter(
        FinancialReport.owner_id == current_user.id
    )
    if report_type:
        q = q.filter(FinancialReport.report_type == report_type)
    if year:
        q = q.filter(FinancialReport.report_period.like(f"{year}%"))

    reports = q.order_by(FinancialReport.created_at.desc()).all()
    return [
        ReportListResponse(
            id=str(r.id), owner_id=str(r.owner_id),
            report_period=r.report_period, report_type=r.report_type,
            status=r.status, generated_at=r.generated_at,
            pdf_url=r.pdf_url, created_at=r.created_at,
        )
        for r in reports
    ]


@router.get("/profit/reports/{report_id}", response_model=ReportDetailResponse)
def get_report(
    report_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    from app.models.profit_engine import FinancialReport

    try:
        rid = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid report ID")

    report = db.query(FinancialReport).filter(
        FinancialReport.id == rid,
        FinancialReport.owner_id == current_user.id,
    ).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return ReportDetailResponse(
        id=str(report.id), owner_id=str(report.owner_id),
        report_period=report.report_period, report_type=report.report_type,
        status=report.status, generated_at=report.generated_at,
        pdf_url=report.pdf_url, created_at=report.created_at,
        data=report.data,
    )


# ── Expenses ───────────────────────────────────────────────────────────────────

@router.get("/profit/expenses", response_model=List[ExpenseResponse])
def list_expenses(
    property_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    from app.models.profit_engine import ExpenseRecord
    from app.models.property import Property, Unit

    q = db.query(ExpenseRecord).filter(ExpenseRecord.owner_id == current_user.id)
    if property_id:
        q = q.filter(ExpenseRecord.property_id == uuid.UUID(property_id))
    if category:
        q = q.filter(ExpenseRecord.category == category)
    if date_from:
        from datetime import date as date_type
        q = q.filter(ExpenseRecord.expense_date >= date_type.fromisoformat(date_from))
    if date_to:
        from datetime import date as date_type
        q = q.filter(ExpenseRecord.expense_date <= date_type.fromisoformat(date_to))

    expenses = q.order_by(ExpenseRecord.expense_date.desc()).offset(skip).limit(limit).all()

    result = []
    for e in expenses:
        prop = db.query(Property).filter(Property.id == e.property_id).first() if e.property_id else None
        unit = db.query(Unit).filter(Unit.id == e.unit_id).first() if e.unit_id else None
        result.append(ExpenseResponse(
            id=str(e.id), owner_id=str(e.owner_id),
            property_id=str(e.property_id) if e.property_id else None,
            property_name=prop.name if prop else None,
            unit_id=str(e.unit_id) if e.unit_id else None,
            unit_number=unit.unit_number if unit else None,
            category=e.category, description=e.description,
            amount=float(e.amount), expense_date=e.expense_date,
            vendor_job_id=str(e.vendor_job_id) if e.vendor_job_id else None,
            receipt_url=e.receipt_url, notes=e.notes,
            created_at=e.created_at, updated_at=e.updated_at,
        ))
    return result


@router.post("/profit/expenses", response_model=ExpenseResponse, status_code=201)
def create_expense(
    body: ExpenseCreate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    from app.models.profit_engine import ExpenseRecord

    expense = ExpenseRecord(
        id=uuid.uuid4(),
        owner_id=current_user.id,
        property_id=uuid.UUID(body.property_id) if body.property_id else None,
        unit_id=uuid.UUID(body.unit_id) if body.unit_id else None,
        category=body.category,
        description=body.description,
        amount=body.amount,
        expense_date=body.expense_date,
        vendor_job_id=uuid.UUID(body.vendor_job_id) if body.vendor_job_id else None,
        receipt_url=body.receipt_url,
        notes=body.notes,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return ExpenseResponse(
        id=str(expense.id), owner_id=str(expense.owner_id),
        property_id=str(expense.property_id) if expense.property_id else None,
        unit_id=str(expense.unit_id) if expense.unit_id else None,
        category=expense.category, description=expense.description,
        amount=float(expense.amount), expense_date=expense.expense_date,
        vendor_job_id=str(expense.vendor_job_id) if expense.vendor_job_id else None,
        receipt_url=expense.receipt_url, notes=expense.notes,
        created_at=expense.created_at, updated_at=expense.updated_at,
    )


@router.put("/profit/expenses/{expense_id}", response_model=ExpenseResponse)
def update_expense(
    expense_id: str,
    body: ExpenseUpdate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    from app.models.profit_engine import ExpenseRecord

    expense = db.query(ExpenseRecord).filter(
        ExpenseRecord.id == uuid.UUID(expense_id),
        ExpenseRecord.owner_id == current_user.id,
    ).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    for field, val in body.model_dump(exclude_none=True).items():
        if field == "property_id":
            setattr(expense, field, uuid.UUID(val) if val else None)
        elif field == "unit_id":
            setattr(expense, field, uuid.UUID(val) if val else None)
        else:
            setattr(expense, field, val)

    db.commit()
    db.refresh(expense)
    return ExpenseResponse(
        id=str(expense.id), owner_id=str(expense.owner_id),
        property_id=str(expense.property_id) if expense.property_id else None,
        unit_id=str(expense.unit_id) if expense.unit_id else None,
        category=expense.category, description=expense.description,
        amount=float(expense.amount), expense_date=expense.expense_date,
        vendor_job_id=str(expense.vendor_job_id) if expense.vendor_job_id else None,
        receipt_url=expense.receipt_url, notes=expense.notes,
        created_at=expense.created_at, updated_at=expense.updated_at,
    )


@router.delete("/profit/expenses/{expense_id}", status_code=204)
def delete_expense(
    expense_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    from app.models.profit_engine import ExpenseRecord

    expense = db.query(ExpenseRecord).filter(
        ExpenseRecord.id == uuid.UUID(expense_id),
        ExpenseRecord.owner_id == current_user.id,
    ).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    db.delete(expense)
    db.commit()


# ── Targets ────────────────────────────────────────────────────────────────────

@router.get("/profit/targets", response_model=List[TargetResponse])
def list_targets(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    from app.models.profit_engine import ProfitTarget
    from app.models.property import Property

    targets = db.query(ProfitTarget).filter(
        ProfitTarget.owner_id == current_user.id
    ).all()

    result = []
    for t in targets:
        prop = db.query(Property).filter(Property.id == t.property_id).first() if t.property_id else None
        result.append(TargetResponse(
            id=str(t.id), owner_id=str(t.owner_id),
            property_id=str(t.property_id) if t.property_id else None,
            property_name=prop.name if prop else None,
            target_type=t.target_type, target_value=float(t.target_value),
            period=t.period, created_at=t.created_at, updated_at=t.updated_at,
        ))
    return result


@router.post("/profit/targets", response_model=TargetResponse, status_code=201)
def create_target(
    body: TargetCreate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    from app.models.profit_engine import ProfitTarget

    target = ProfitTarget(
        id=uuid.uuid4(),
        owner_id=current_user.id,
        property_id=uuid.UUID(body.property_id) if body.property_id else None,
        target_type=body.target_type,
        target_value=body.target_value,
        period=body.period,
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    return TargetResponse(
        id=str(target.id), owner_id=str(target.owner_id),
        property_id=str(target.property_id) if target.property_id else None,
        target_type=target.target_type, target_value=float(target.target_value),
        period=target.period, created_at=target.created_at, updated_at=target.updated_at,
    )


@router.put("/profit/targets/{target_id}", response_model=TargetResponse)
def update_target(
    target_id: str,
    body: TargetUpdate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    from app.models.profit_engine import ProfitTarget

    target = db.query(ProfitTarget).filter(
        ProfitTarget.id == uuid.UUID(target_id),
        ProfitTarget.owner_id == current_user.id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")

    for field, val in body.model_dump(exclude_none=True).items():
        setattr(target, field, val)

    db.commit()
    db.refresh(target)
    return TargetResponse(
        id=str(target.id), owner_id=str(target.owner_id),
        property_id=str(target.property_id) if target.property_id else None,
        target_type=target.target_type, target_value=float(target.target_value),
        period=target.period, created_at=target.created_at, updated_at=target.updated_at,
    )


@router.delete("/profit/targets/{target_id}", status_code=204)
def delete_target(
    target_id: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    from app.models.profit_engine import ProfitTarget

    target = db.query(ProfitTarget).filter(
        ProfitTarget.id == uuid.UUID(target_id),
        ProfitTarget.owner_id == current_user.id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    db.delete(target)
    db.commit()


@router.get("/profit/targets/status")
def get_targets_status(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    engine = ProfitEngine(db, current_user.id)
    try:
        return engine.get_targets_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
