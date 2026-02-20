"""
Market Intelligence Routes
Neighbourhood & Market Intelligence Dashboard — premium feature.

Endpoints:
  GET /api/market/area-overview            → all area summaries
  GET /api/market/area/{area_name}         → detailed breakdown for one area
  GET /api/market/my-properties-benchmark  → owner's units vs area averages
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserRole
from app.models.payment import Subscription, SubscriptionStatus
from app.schemas.market import (
    AreaOverviewResponse,
    AreaDetail,
    MyPropertiesBenchmarkResponse,
)
from app.services.market_service import MarketService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Market Intelligence"])


# ── Premium gate dependency ────────────────────────────────────────────────

def require_premium(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Allow all authenticated owners and admins (subscription gate removed)."""
    if current_user.role in (UserRole.ADMIN, UserRole.OWNER):
        return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access restricted to property owners.",
    )


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/area-overview", response_model=AreaOverviewResponse)
def get_area_overview(
    city: Optional[str] = Query(None, description="Filter areas by city name"),
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """
    Return a paginated list of all tracked neighbourhoods with their
    headline KPIs: avg rent, vacancy rate, avg tenancy, area health score.

    Data is refreshed automatically if stale (> 24 hours old).
    """
    try:
        service = MarketService(db)
        areas = service.get_or_refresh_all_areas(city_filter=city)
        return AreaOverviewResponse(areas=areas, total=len(areas))
    except Exception as e:
        logger.error(f"[market] area-overview failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve area overview. Please try again.",
        )


@router.get("/area/{area_name}", response_model=AreaDetail)
def get_area_detail(
    area_name: str,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """
    Return full market breakdown for a specific neighbourhood including:
    - Rent benchmarks by bedroom count
    - Vacancy rate and 6-month trend
    - Average tenancy duration
    - Maintenance request rate
    - Area health score (0–100)
    """
    try:
        service = MarketService(db)
        detail = service.get_area_detail(area_name)
        if not detail:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No market data found for area '{area_name}'.",
            )
        return detail
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[market] area detail '{area_name}' failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve area detail. Please try again.",
        )


@router.get("/my-properties-benchmark", response_model=MyPropertiesBenchmarkResponse)
def get_my_properties_benchmark(
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """
    Compare the authenticated owner's properties against area market averages.

    Returns each property with unit-level rent deltas (above / below market)
    and a portfolio-wide summary.
    """
    if current_user.role not in [UserRole.OWNER, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only property owners can access the benchmark view.",
        )
    try:
        service = MarketService(db)
        return service.get_my_properties_benchmark(current_user.id)
    except Exception as e:
        logger.error(f"[market] benchmark failed for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compute benchmark. Please try again.",
        )
