"""
KRA Rental Income Tax Calculation Service
Implements Kenya's rental income tax rules as of Finance Act 2023.

IMPORTANT: When KRA updates tax bands or thresholds via a Finance Act,
update the constants in the "KRA TAX CONSTANTS" section below.
All computation functions read from these constants — no hardcoded numbers elsewhere.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════════════════════
# KRA TAX CONSTANTS  (update these when Finance Acts change)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Monthly Rental Income (MRI) Tax — Finance Act 2023 ──
# Flat rate for resident individuals whose ANNUAL gross rent ≤ threshold
MRI_RATE = 0.10                          # 10% flat on gross rent
MRI_ANNUAL_THRESHOLD = 15_000_000.0     # KES 15,000,000 per year
MRI_MONTHLY_THRESHOLD = MRI_ANNUAL_THRESHOLD / 12  # KES 1,250,000 per month

# ── Non-Resident Withholding Tax ──
NON_RESIDENT_RATE = 0.30                # 30% on gross rent

# ── Corporate Tax Rate ──
CORPORATE_RATE = 0.30                   # 30% on net income

# ── Individual Income Tax Bands (annual, for landlords above MRI threshold) ──
# Format: (upper_bound, marginal_rate)  — None = no upper bound
INDIVIDUAL_TAX_BANDS: List[Tuple[Optional[float], float]] = [
    (288_000.0, 0.10),       # 0 – 288,000: 10%
    (388_000.0, 0.25),       # 288,001 – 388,000: 25%
    (6_000_000.0, 0.30),     # 388,001 – 6,000,000: 30%
    (9_600_000.0, 0.325),    # 6,000,001 – 9,600,000: 32.5%
    (None, 0.35),            # Above 9,600,000: 35%
]

# ── Personal Relief (resident individuals only, annual) ──
PERSONAL_RELIEF_ANNUAL = 28_800.0       # KES 28,800 per year
PERSONAL_RELIEF_MONTHLY = PERSONAL_RELIEF_ANNUAL / 12

# ── Corporate Withholding on Rent from Corporate Tenants ──
# Corporate tenants are required by KRA to withhold tax before remitting rent.
CORPORATE_TENANT_WHT_RATE = 0.10       # 10% for resident corporate tenants
NON_RESIDENT_TENANT_WHT_RATE = 0.30    # 30% for non-resident corporate tenants

# ── KRA iTax Reference Labels ──
LANDLORD_TYPES = {
    "resident_individual": "Resident Individual",
    "non_resident": "Non-Resident",
    "corporate": "Corporate (Company/Trust)",
}


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _apply_individual_bands(taxable_income: float) -> float:
    """
    Compute tax on taxable income using Kenya's progressive individual
    income tax bands. Returns total tax before personal relief.
    """
    if taxable_income <= 0:
        return 0.0

    tax = 0.0
    remaining = taxable_income
    prev_upper = 0.0

    for upper, rate in INDIVIDUAL_TAX_BANDS:
        band_top = upper if upper is not None else float("inf")
        band_width = band_top - prev_upper
        taxable_in_band = min(remaining, band_width)
        tax += taxable_in_band * rate
        remaining -= taxable_in_band
        prev_upper = band_top
        if remaining <= 0:
            break

    return tax


def _allowable_deductions_categories() -> List[str]:
    """Return the list of expense categories that KRA treats as allowable deductions."""
    return [
        "mortgage_interest",
        "repairs_maintenance",
        "property_management_fees",
        "insurance",
        "land_rates",
        "ground_rent",
        "legal_fees",
        "advertising",
        "depreciation",
        "caretaker_salary",
        "utilities",
        "security",
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# CORE TAX COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════════

def compute_monthly_tax(
    gross_monthly_rent: float,
    landlord_type: str,
    total_allowable_deductions: float = 0.0,
    annualised_gross: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Compute KRA rental income tax for a single month.

    Parameters
    ----------
    gross_monthly_rent       : total gross rent received in the month (KES)
    landlord_type            : "resident_individual" | "non_resident" | "corporate"
    total_allowable_deductions: total KRA-allowable expenses for the month (KES)
    annualised_gross         : if provided, used to determine threshold status for
                               resident individuals; otherwise gross_monthly_rent × 12
    """
    if annualised_gross is None:
        annualised_gross = gross_monthly_rent * 12

    above_threshold = annualised_gross > MRI_ANNUAL_THRESHOLD

    result: Dict[str, Any] = {
        "period_type": "monthly",
        "gross_rental_income": round(gross_monthly_rent, 2),
        "landlord_type": landlord_type,
        "landlord_type_label": LANDLORD_TYPES.get(landlord_type, landlord_type),
        "annualised_gross": round(annualised_gross, 2),
        "above_mri_threshold": above_threshold,
        "mri_threshold": MRI_ANNUAL_THRESHOLD,
        "allowable_deductions": 0.0,
        "net_taxable_income": 0.0,
        "tax_rate_applied": 0.0,
        "tax_liability": 0.0,
        "calculation_method": "",
        "breakdown": {},
    }

    if landlord_type == "non_resident":
        # Always 30% on gross — no deductions, no threshold
        tax = gross_monthly_rent * NON_RESIDENT_RATE
        result.update({
            "tax_rate_applied": NON_RESIDENT_RATE,
            "net_taxable_income": gross_monthly_rent,
            "tax_liability": round(tax, 2),
            "calculation_method": "Non-Resident WHT: 30% on gross rent",
            "breakdown": {
                "gross_rent": gross_monthly_rent,
                "rate": f"{NON_RESIDENT_RATE * 100:.0f}%",
                "tax": round(tax, 2),
            },
        })

    elif landlord_type == "corporate":
        # 30% on net income (after deductions)
        deductions = min(total_allowable_deductions, gross_monthly_rent)
        net = max(gross_monthly_rent - deductions, 0)
        tax = net * CORPORATE_RATE
        result.update({
            "allowable_deductions": round(deductions, 2),
            "net_taxable_income": round(net, 2),
            "tax_rate_applied": CORPORATE_RATE,
            "tax_liability": round(tax, 2),
            "calculation_method": "Corporation Tax: 30% on net rental income",
            "breakdown": {
                "gross_rent": gross_monthly_rent,
                "deductions": round(deductions, 2),
                "net_income": round(net, 2),
                "rate": f"{CORPORATE_RATE * 100:.0f}%",
                "tax": round(tax, 2),
            },
        })

    else:
        # Resident Individual
        if not above_threshold:
            # MRI — flat 10% on gross, NO deductions
            tax = gross_monthly_rent * MRI_RATE
            result.update({
                "tax_rate_applied": MRI_RATE,
                "net_taxable_income": gross_monthly_rent,
                "tax_liability": round(tax, 2),
                "calculation_method": (
                    "MRI (Monthly Rental Income Tax): 10% flat rate on gross rent "
                    f"— annual gross KES {annualised_gross:,.0f} ≤ KES {MRI_ANNUAL_THRESHOLD:,.0f} threshold"
                ),
                "breakdown": {
                    "gross_rent": gross_monthly_rent,
                    "rate": "10% (MRI flat rate)",
                    "tax": round(tax, 2),
                    "note": "No deductions applicable below the KES 15M threshold",
                },
            })
        else:
            # Above threshold — use individual tax bands with deductions
            deductions = min(total_allowable_deductions, gross_monthly_rent)
            net = max(gross_monthly_rent - deductions, 0)
            tax_before_relief = _apply_individual_bands(net)
            tax = max(tax_before_relief - PERSONAL_RELIEF_MONTHLY, 0)
            effective_rate = (tax / gross_monthly_rent) if gross_monthly_rent > 0 else 0
            result.update({
                "allowable_deductions": round(deductions, 2),
                "net_taxable_income": round(net, 2),
                "tax_rate_applied": round(effective_rate, 4),
                "tax_liability": round(tax, 2),
                "calculation_method": (
                    "Individual Income Tax (progressive bands) "
                    f"— annual gross KES {annualised_gross:,.0f} exceeds KES {MRI_ANNUAL_THRESHOLD:,.0f} threshold"
                ),
                "breakdown": {
                    "gross_rent": gross_monthly_rent,
                    "deductions": round(deductions, 2),
                    "net_income": round(net, 2),
                    "tax_before_relief": round(tax_before_relief, 2),
                    "personal_relief": round(PERSONAL_RELIEF_MONTHLY, 2),
                    "tax": round(tax, 2),
                    "effective_rate": f"{effective_rate * 100:.2f}%",
                },
            })

    return result


def compute_annual_tax(
    gross_annual_rent: float,
    landlord_type: str,
    total_allowable_deductions: float = 0.0,
) -> Dict[str, Any]:
    """
    Compute KRA rental income tax for a full year.
    """
    above_threshold = gross_annual_rent > MRI_ANNUAL_THRESHOLD

    result: Dict[str, Any] = {
        "period_type": "annual",
        "gross_rental_income": round(gross_annual_rent, 2),
        "landlord_type": landlord_type,
        "landlord_type_label": LANDLORD_TYPES.get(landlord_type, landlord_type),
        "above_mri_threshold": above_threshold,
        "mri_threshold": MRI_ANNUAL_THRESHOLD,
        "allowable_deductions": 0.0,
        "net_taxable_income": 0.0,
        "tax_rate_applied": 0.0,
        "tax_liability": 0.0,
        "calculation_method": "",
        "breakdown": {},
    }

    if landlord_type == "non_resident":
        tax = gross_annual_rent * NON_RESIDENT_RATE
        result.update({
            "tax_rate_applied": NON_RESIDENT_RATE,
            "net_taxable_income": gross_annual_rent,
            "tax_liability": round(tax, 2),
            "calculation_method": "Non-Resident WHT: 30% on gross rent (annual)",
            "breakdown": {
                "gross_rent": gross_annual_rent,
                "rate": f"{NON_RESIDENT_RATE * 100:.0f}%",
                "tax": round(tax, 2),
            },
        })

    elif landlord_type == "corporate":
        deductions = min(total_allowable_deductions, gross_annual_rent)
        net = max(gross_annual_rent - deductions, 0)
        tax = net * CORPORATE_RATE
        result.update({
            "allowable_deductions": round(deductions, 2),
            "net_taxable_income": round(net, 2),
            "tax_rate_applied": CORPORATE_RATE,
            "tax_liability": round(tax, 2),
            "calculation_method": "Corporation Tax: 30% on net rental income (annual)",
            "breakdown": {
                "gross_rent": gross_annual_rent,
                "deductions": round(deductions, 2),
                "net_income": round(net, 2),
                "rate": f"{CORPORATE_RATE * 100:.0f}%",
                "tax": round(tax, 2),
            },
        })

    else:
        # Resident Individual
        if not above_threshold:
            tax = gross_annual_rent * MRI_RATE
            result.update({
                "tax_rate_applied": MRI_RATE,
                "net_taxable_income": gross_annual_rent,
                "tax_liability": round(tax, 2),
                "calculation_method": (
                    "MRI (Monthly Rental Income Tax): 10% flat rate "
                    f"— annual gross KES {gross_annual_rent:,.0f} ≤ KES {MRI_ANNUAL_THRESHOLD:,.0f}"
                ),
                "breakdown": {
                    "gross_rent": gross_annual_rent,
                    "rate": "10% (MRI flat rate)",
                    "tax": round(tax, 2),
                    "note": "No deductions applicable below the KES 15M annual threshold",
                },
            })
        else:
            deductions = min(total_allowable_deductions, gross_annual_rent)
            net = max(gross_annual_rent - deductions, 0)
            tax_before_relief = _apply_individual_bands(net)
            tax = max(tax_before_relief - PERSONAL_RELIEF_ANNUAL, 0)
            effective_rate = (tax / gross_annual_rent) if gross_annual_rent > 0 else 0
            result.update({
                "allowable_deductions": round(deductions, 2),
                "net_taxable_income": round(net, 2),
                "tax_rate_applied": round(effective_rate, 4),
                "tax_liability": round(tax, 2),
                "calculation_method": (
                    "Individual Income Tax (progressive bands) "
                    f"— annual gross KES {gross_annual_rent:,.0f} exceeds KES {MRI_ANNUAL_THRESHOLD:,.0f}"
                ),
                "breakdown": {
                    "gross_rent": gross_annual_rent,
                    "deductions": round(deductions, 2),
                    "net_income": round(net, 2),
                    "tax_before_relief": round(tax_before_relief, 2),
                    "personal_relief": round(PERSONAL_RELIEF_ANNUAL, 2),
                    "tax": round(tax, 2),
                    "effective_rate": f"{effective_rate * 100:.2f}%",
                    "bands": [
                        {"band": "0 – 288,000", "rate": "10%"},
                        {"band": "288,001 – 388,000", "rate": "25%"},
                        {"band": "388,001 – 6,000,000", "rate": "30%"},
                        {"band": "6,000,001 – 9,600,000", "rate": "32.5%"},
                        {"band": "Above 9,600,000", "rate": "35%"},
                    ],
                },
            })

    return result


def get_allowable_categories() -> List[str]:
    """Return list of expense categories KRA recognises as allowable deductions."""
    return _allowable_deductions_categories()


def compute_withholding_tax(amount_paid: float, rate: float = 10.0) -> Dict[str, float]:
    """
    Given the net amount received after withholding, or gross before withholding,
    compute the withholding tax figures.
    """
    wht = round(amount_paid * rate / 100, 2)
    gross = round(amount_paid + wht, 2)
    return {
        "amount_before_withholding": gross,
        "withholding_rate": rate,
        "withholding_amount": wht,
        "net_received": amount_paid,
    }


def get_tax_constants() -> Dict[str, Any]:
    """Return all tax constants for frontend display and reference."""
    return {
        "mri_rate": MRI_RATE,
        "mri_annual_threshold": MRI_ANNUAL_THRESHOLD,
        "mri_monthly_threshold": MRI_MONTHLY_THRESHOLD,
        "non_resident_rate": NON_RESIDENT_RATE,
        "corporate_rate": CORPORATE_RATE,
        "personal_relief_annual": PERSONAL_RELIEF_ANNUAL,
        "personal_relief_monthly": PERSONAL_RELIEF_MONTHLY,
        "individual_tax_bands": [
            {"lower": 0, "upper": 288000, "rate": 0.10},
            {"lower": 288001, "upper": 388000, "rate": 0.25},
            {"lower": 388001, "upper": 6000000, "rate": 0.30},
            {"lower": 6000001, "upper": 9600000, "rate": 0.325},
            {"lower": 9600001, "upper": None, "rate": 0.35},
        ],
        "corporate_wht_rate": CORPORATE_TENANT_WHT_RATE,
        "non_resident_wht_rate": NON_RESIDENT_TENANT_WHT_RATE,
        "allowable_deductions": _allowable_deductions_categories(),
        "landlord_types": LANDLORD_TYPES,
        "finance_act_year": 2023,
        "currency": "KES",
    }
