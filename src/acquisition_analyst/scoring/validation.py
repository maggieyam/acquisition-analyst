"""Completeness validation + sanity flags. Deterministic."""

from ..models import AnalysisRequest, ValidationResult

REQUIRED_METRICS = [
    "arr", "arr_growth", "nrr", "grr",
    "cac_payback_months", "ltv_cac", "magic_number",
    "burn_multiple", "gross_margin", "ebitda_margin",
]

VALID_STAGES = {"early", "growth", "late"}
VALID_VERTICALS = {"vertical_saas", "horizontal_saas", "fintech", "healthtech", "other"}
VALID_SIZE_BANDS = {"0-5M", "5-10M", "10-25M", "25-50M", "50-100M", "100M+"}

# Sanity bounds: (min_warn, max_warn) — values outside trigger a warning, not a block
SANITY_BOUNDS: dict[str, tuple[float, float]] = {
    "arr_growth":         (-50, 400),
    "nrr":                (50,  200),
    "grr":                (50,  100),
    "cac_payback_months": (1,   120),
    "ltv_cac":            (0.1, 30),
    "magic_number":       (0,   5),
    "burn_multiple":      (0,   20),
    "gross_margin":       (-50, 100),
    "ebitda_margin":      (-200, 100),
}


def validate(req: AnalysisRequest) -> ValidationResult:
    missing: list[str] = []
    warnings: list[str] = []

    if req.stage not in VALID_STAGES:
        missing.append(f"stage must be one of {sorted(VALID_STAGES)}, got '{req.stage}'")
    if req.vertical not in VALID_VERTICALS:
        missing.append(f"vertical must be one of {sorted(VALID_VERTICALS)}, got '{req.vertical}'")
    if req.size_band not in VALID_SIZE_BANDS:
        missing.append(f"size_band must be one of {sorted(VALID_SIZE_BANDS)}, got '{req.size_band}'")

    for field in REQUIRED_METRICS:
        if getattr(req, field, None) is None:
            missing.append(field)

    # Sanity range checks (warnings only)
    for field, (lo, hi) in SANITY_BOUNDS.items():
        val = getattr(req, field, None)
        if val is not None and not (lo <= val <= hi):
            warnings.append(
                f"{field} = {val} is outside the expected sanity range [{lo}, {hi}]. "
                "Verify the figure before proceeding."
            )

    # NRR ≥ GRR (by definition)
    if req.nrr < req.grr:
        warnings.append(
            f"NRR ({req.nrr}%) < GRR ({req.grr}%) — NRR must be ≥ GRR by definition. "
            "Verify both figures."
        )

    if req.customer_concentration_top10_pct is not None:
        if req.customer_concentration_top10_pct > 50:
            warnings.append(
                f"Top-10 customer concentration of {req.customer_concentration_top10_pct}% "
                "is high; churn risk is elevated."
            )

    if req.series:
        for metric_field in type(req.series).model_fields:
            series_val = getattr(req.series, metric_field)
            if series_val is not None and len(series_val) < 2:
                warnings.append(
                    f"series.{metric_field} has only {len(series_val)} data point(s); "
                    "trend analysis requires at least 2."
                )

    return ValidationResult(
        valid=len(missing) == 0,
        missing=missing,
        warnings=warnings,
    )
