"""
Market Intelligence Schemas
Pydantic models for neighbourhood & market intelligence endpoints.
"""
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class RentByBedrooms(BaseModel):
    """Average rent broken down by unit bedroom count."""
    studio: Optional[float] = None       # 0-bedroom / bedsitter
    one_br: Optional[float] = None       # 1 bedroom
    two_br: Optional[float] = None       # 2 bedrooms
    three_br: Optional[float] = None     # 3 bedrooms
    four_br_plus: Optional[float] = None # 4+ bedrooms


class VacancyTrendPoint(BaseModel):
    """A single data point in the monthly vacancy trend series."""
    month: str    # "YYYY-MM" format, e.g. "2024-01"
    rate: float   # vacancy rate 0.0–1.0


class AreaSummary(BaseModel):
    """Lightweight summary of an area — used in the overview list."""
    area_name: str
    city: Optional[str] = None
    avg_rent_overall: Optional[float] = None   # Simple average of all rents
    vacancy_rate: float
    avg_tenancy_months: Optional[float] = None
    area_health_score: Optional[float] = None
    total_units: int
    data_points: int                           # 0 = seeded reference data
    last_computed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AreaDetail(BaseModel):
    """Full breakdown for a single area — used in the detail view."""
    area_name: str
    city: Optional[str] = None
    avg_rent_overall: Optional[float] = None
    avg_rent_by_type: RentByBedrooms
    vacancy_rate: float
    total_units: int
    vacant_units: int
    avg_tenancy_months: Optional[float] = None
    maintenance_rate: Optional[float] = None   # Requests per unit per 90 days
    area_health_score: Optional[float] = None
    vacancy_trend: List[VacancyTrendPoint] = []
    data_points: int
    last_computed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UnitBenchmark(BaseModel):
    """Single unit compared against its area average."""
    unit_id: str
    unit_number: str
    bedrooms: int
    monthly_rent: float
    area_avg_rent: Optional[float] = None  # Area average for same bedroom count
    delta: Optional[float] = None          # monthly_rent - area_avg_rent
    delta_pct: Optional[float] = None      # (delta / area_avg_rent) * 100


class PropertyBenchmark(BaseModel):
    """A single property with its units benchmarked against the area."""
    property_id: str
    property_name: str
    area_name: str
    city: Optional[str] = None
    area_health_score: Optional[float] = None
    units: List[UnitBenchmark] = []


class BenchmarkSummary(BaseModel):
    """Aggregate summary of how the owner's portfolio stacks up."""
    total_properties: int
    total_units: int
    properties_above_market: int   # At least one unit above area average
    properties_below_market: int
    avg_delta_pct: Optional[float] = None  # Portfolio-wide average delta %


class MyPropertiesBenchmarkResponse(BaseModel):
    """Response for /my-properties-benchmark."""
    properties: List[PropertyBenchmark]
    summary: BenchmarkSummary


class AreaOverviewResponse(BaseModel):
    """Response for /area-overview."""
    areas: List[AreaSummary]
    total: int
