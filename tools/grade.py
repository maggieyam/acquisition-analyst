"""Tool 3 — Grade, scorecard, and recommendation. Fully deterministic."""

from models import (
    AnalysisRequest, BenchmarkCohort, BenchmarkBand,
    GradedMetric, FamilyScore, Scorecard, RecommendationResult,
)
from tools.benchmark import get_valuation_multiples


# ── Weight profiles by buyer_segment ─────────────────────────────────────────

WEIGHT_PROFILES: dict[str, dict[str, float]] = {
    "growth_equity": {
        "arr_growth":         0.20,
        "nrr":                0.15,
        "rule_of_40":         0.10,
        "magic_number":       0.10,
        "burn_multiple":      0.10,
        "gross_margin":       0.10,
        "ltv_cac":            0.10,
        "grr":                0.05,
        "cac_payback_months": 0.05,
        "ebitda_margin":      0.05,
    },
    "lmm": {
        "ebitda_margin":      0.20,
        "gross_margin":       0.15,
        "burn_multiple":      0.15,
        "nrr":                0.15,
        "arr_growth":         0.10,
        "grr":                0.10,
        "ltv_cac":            0.05,
        "cac_payback_months": 0.05,
        "magic_number":       0.03,
        "rule_of_40":         0.02,
    },
    "strategic": {
        "nrr":                0.20,
        "grr":                0.15,
        "arr_growth":         0.15,
        "gross_margin":       0.15,
        "ltv_cac":            0.10,
        "burn_multiple":      0.05,
        "ebitda_margin":      0.05,
        "cac_payback_months": 0.05,
        "magic_number":       0.05,
        "rule_of_40":         0.05,
    },
}


# Metric families for per-family scorecard display
METRIC_FAMILIES: dict[str, list[str]] = {
    "growth":        ["arr_growth", "rule_of_40"],
    "retention":     ["nrr", "grr"],
    "efficiency":    ["burn_multiple", "ebitda_margin", "gross_margin"],
    "unit_economics": ["ltv_cac", "cac_payback_months", "magic_number"],
}

COMPOSITE_BANDS = [
    (3.5, "Strong"),
    (2.75, "Above Average"),
    (2.0, "Below Average"),
    (0.0, "Weak"),
]

ASSESSMENT_THRESHOLDS = [
    (3.4, "buy"),
    (2.8, "conditional_buy"),
    (2.2, "hold"),
    (0.0, "pass"),
]


# ── Grading helpers ───────────────────────────────────────────────────────────

def _grade_value(value: float, bm: dict) -> tuple[str, int]:
    """
    Returns (band_label, points).
    direction: higher_better → Q3+ = Strong; lower_better → Q1- = Strong.
    """
    q1, median, q3 = bm["q1"], bm["median"], bm["q3"]
    direction = bm["direction"]

    if direction == "higher_better":
        if value >= q3:
            return "Strong", 4
        elif value >= median:
            return "Above", 3
        elif value >= q1:
            return "Below", 2
        else:
            return "Weak", 1
    else:  # lower_better
        if value <= q1:
            return "Strong", 4
        elif value <= median:
            return "Above", 3
        elif value <= q3:
            return "Below", 2
        else:
            return "Weak", 1


def _compute_trend(series: list[float] | None, direction: str = "higher_better") -> str | None:
    """
    Trend labels are always from the buyer's perspective (improving = good).
    For lower_better metrics a falling series is 'improving'.
    """
    if not series or len(series) < 2:
        return None
    delta = series[-1] - series[0]
    pct_change = delta / abs(series[0]) if series[0] != 0 else float("inf")
    if direction == "lower_better":
        pct_change = -pct_change  # invert: falling is good
    if pct_change > 0.05:
        return "improving"
    elif pct_change < -0.05:
        return "declining"
    return "flat"


def _build_graded_metric(
    field: str,
    value: float,
    bm: dict,
    cohort_key: str,
    cohort_confidence: str,
    series: list[float] | None = None,
) -> GradedMetric:
    band, points = _grade_value(value, bm)
    trend = _compute_trend(series, bm.get("direction", "higher_better"))
    return GradedMetric(
        value=value,
        benchmark=BenchmarkBand(
            median=bm["median"],
            q1=bm["q1"],
            q3=bm["q3"],
            direction=bm["direction"],
        ),
        band=band,
        points=points,
        trend=trend,
        series=series,
        cohort_key=cohort_key,
        cohort_confidence=cohort_confidence,
    )


# ── Risk flag detection ───────────────────────────────────────────────────────

def _compute_risk_flags(
    req: AnalysisRequest,
    graded: dict[str, GradedMetric],
) -> list[str]:
    flags: list[str] = []

    # Decelerating growth: series declining
    ag = graded.get("arr_growth")
    if ag and ag.trend == "declining":
        flags.append("Growth deceleration: ARR growth rate is declining across periods.")

    # Declining NRR
    nrr = graded.get("nrr")
    if nrr and nrr.trend == "declining":
        flags.append("NRR erosion: net revenue retention is declining — monitor churn and expansion dynamics.")

    # Worsening burn multiple (series increasing = worse)
    bm = graded.get("burn_multiple")
    if bm and bm.series and len(bm.series) >= 2:
        if bm.series[-1] > bm.series[0] * 1.1:
            flags.append("Burn deterioration: burn multiple is rising — capital efficiency is declining.")

    # Absolute burn threshold
    if bm and bm.value > 2.5:
        flags.append(f"High burn multiple ({bm.value:.1f}x) — company is spending significantly to acquire each dollar of new ARR.")

    # Customer concentration
    if req.customer_concentration_top10_pct is not None and req.customer_concentration_top10_pct > 40:
        flags.append(
            f"Customer concentration: top-10 accounts represent {req.customer_concentration_top10_pct:.0f}% of ARR — "
            "single-customer churn could materially impact revenue."
        )

    # Weak NRR absolute threshold
    if req.nrr < 100:
        flags.append(f"NRR below 100% ({req.nrr:.1f}%) — business is contracting on the existing customer base.")

    # GRR below danger threshold
    if req.grr < 80:
        flags.append(f"GRR of {req.grr:.1f}% indicates elevated gross churn.")

    # LTV:CAC below 2x
    if req.ltv_cac < 2.0:
        flags.append(f"LTV:CAC of {req.ltv_cac:.1f}x is below the 2× minimum threshold for sustainable unit economics.")

    return flags


# ── Scorecard ─────────────────────────────────────────────────────────────────

def _band_for_composite(composite: float) -> str:
    for threshold, label in COMPOSITE_BANDS:
        if composite >= threshold:
            return label
    return "Weak"


def _build_scorecard(
    graded: dict[str, GradedMetric],
    buyer_segment: str,
) -> Scorecard:
    weights = WEIGHT_PROFILES.get(buyer_segment, WEIGHT_PROFILES["growth_equity"])

    weighted_sum = 0.0
    weight_total = 0.0
    for metric, weight in weights.items():
        gm = graded.get(metric)
        if gm:
            weighted_sum += gm.points * weight
            weight_total += weight

    composite = weighted_sum / weight_total if weight_total else 0.0

    per_family: dict[str, FamilyScore] = {}
    for family, metrics in METRIC_FAMILIES.items():
        family_points = []
        for m in metrics:
            gm = graded.get(m)
            if gm:
                family_points.append(gm.points)
        if family_points:
            fam_composite = sum(family_points) / len(family_points)
            per_family[family] = FamilyScore(
                metrics=metrics,
                composite=round(fam_composite, 2),
                band=_band_for_composite(fam_composite),
            )

    return Scorecard(
        weights_profile=buyer_segment,
        per_family=per_family,
        composite=round(composite, 3),
        band=_band_for_composite(composite),
    )


# ── Recommendation ────────────────────────────────────────────────────────────

def _compute_recommendation(
    req: AnalysisRequest,
    scorecard: Scorecard,
    graded: dict[str, GradedMetric],
    risk_flags: list[str],
) -> RecommendationResult:
    composite = scorecard.composite

    # Base assessment from composite
    assessment = "pass"
    for threshold, label in ASSESSMENT_THRESHOLDS:
        if composite >= threshold:
            assessment = label
            break

    # Downgrade for multiple severe risks
    severe_risks = [f for f in risk_flags if "below 100%" in f or "Burn deterioration" in f or "LTV:CAC" in f]
    if len(severe_risks) >= 2 and assessment == "buy":
        assessment = "conditional_buy"
    elif len(severe_risks) >= 2 and assessment == "conditional_buy":
        assessment = "hold"

    # Overall trend direction
    improving_count = sum(1 for gm in graded.values() if gm.trend == "improving")
    declining_count = sum(1 for gm in graded.values() if gm.trend == "declining")
    overall_trend = "improving" if improving_count > declining_count else (
        "declining" if declining_count > improving_count else "flat"
    )

    # Upgrade on strong positive trend + clean risk profile
    if assessment == "conditional_buy" and overall_trend == "improving" and len(risk_flags) == 0:
        assessment = "buy"
    elif assessment == "hold" and overall_trend == "improving" and len(risk_flags) <= 1:
        assessment = "conditional_buy"

    # Build conditions list
    conditions: list[str] = []
    if assessment in {"conditional_buy", "hold"}:
        if any("NRR erosion" in f for f in risk_flags):
            conditions.append("Require NRR stabilization plan and customer success roadmap before close.")
        if any("Burn deterioration" in f or "burn multiple" in f.lower() for f in risk_flags):
            conditions.append("Agree on cash runway milestones and burn reduction targets pre-sign.")
        if any("concentration" in f.lower() for f in risk_flags):
            conditions.append("Negotiate customer concentration rep/warranty; require top-3 customer renewal confirmation.")
        if any("LTV:CAC" in f for f in risk_flags):
            conditions.append("Stress-test unit economics model; require management presentation on CAC trend.")
        if not conditions:
            conditions.append("Confirm metrics trend remains stable through confirmatory diligence.")

    rationale_parts = [
        f"Composite scorecard of {composite:.2f} ({scorecard.band}) against the {req.buyer_segment} weight profile.",
        f"Overall metric trajectory is {overall_trend}.",
    ]
    if risk_flags:
        rationale_parts.append(f"{len(risk_flags)} risk flag(s) identified.")

    rationale = " ".join(rationale_parts)

    # Solve-for-price if no price supplied
    solve_for_price = None
    if req.price is None:
        multiples = get_valuation_multiples(req)
        arr = req.arr

        # Adjust multiples by scorecard band
        band_adj = {"Strong": 1.15, "Above Average": 1.0, "Below Average": 0.85, "Weak": 0.70}
        adj = band_adj.get(scorecard.band, 1.0)

        low = round(arr * multiples["arr_multiple_q1"] * adj, 1)
        mid = round(arr * multiples["arr_multiple_median"] * adj, 1)
        high = round(arr * multiples["arr_multiple_q3"] * adj, 1)

        solve_for_price = {
            "low":   low,
            "mid":   mid,
            "high":  high,
            "basis": (
                f"ARR ${arr}M × cohort multiple range "
                f"[{multiples['arr_multiple_q1']}x–{multiples['arr_multiple_q3']}x] "
                f"× band adjustment {adj:.2f}x ({scorecard.band})."
            ),
        }

    return RecommendationResult(
        assessment=assessment,
        rationale=rationale,
        conditions=conditions,
        solve_for_price=solve_for_price,
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def run(
    req: AnalysisRequest,
    cohort: BenchmarkCohort,
    benchmark_data: dict,
) -> tuple[dict[str, GradedMetric], GradedMetric, list[str], Scorecard, RecommendationResult]:
    """
    Returns (graded_metrics, rule_of_40_metric, risk_flags, scorecard, recommendation).
    """
    ck = cohort.cohort_key
    cc = cohort.confidence

    # Build per-metric series lookup
    series_map: dict[str, list[float] | None] = {}
    if req.series:
        for field in ["arr_growth", "nrr", "grr", "cac_payback_months", "ltv_cac",
                      "magic_number", "burn_multiple", "gross_margin", "ebitda_margin"]:
            series_map[field] = getattr(req.series, field, None)

    # Grade headline metrics
    graded: dict[str, GradedMetric] = {}
    headline_metrics = [
        ("arr_growth",         req.arr_growth),
        ("nrr",                req.nrr),
        ("grr",                req.grr),
        ("cac_payback_months", req.cac_payback_months),
        ("ltv_cac",            req.ltv_cac),
        ("magic_number",       req.magic_number),
        ("burn_multiple",      req.burn_multiple),
        ("gross_margin",       req.gross_margin),
        ("ebitda_margin",      req.ebitda_margin),
    ]

    for field, value in headline_metrics:
        bm = benchmark_data.get(field)
        if bm:
            graded[field] = _build_graded_metric(
                field, value, bm, ck, cc, series_map.get(field)
            )

    # Rule of 40
    rule_of_40_val = req.arr_growth + req.ebitda_margin
    rule_of_40_series = None
    if req.series and req.series.arr_growth and req.series.ebitda_margin:
        if len(req.series.arr_growth) == len(req.series.ebitda_margin):
            rule_of_40_series = [
                g + e for g, e in zip(req.series.arr_growth, req.series.ebitda_margin)
            ]

    r40_bm = benchmark_data.get("rule_of_40") or {
        "median": 28, "q1": 15, "q3": 45, "direction": "higher_better"
    }
    rule_of_40_metric = _build_graded_metric(
        "rule_of_40", rule_of_40_val, r40_bm, ck, cc, rule_of_40_series
    )
    graded["rule_of_40"] = rule_of_40_metric

    risk_flags = _compute_risk_flags(req, graded)
    scorecard = _build_scorecard(graded, req.buyer_segment)
    recommendation = _compute_recommendation(req, scorecard, graded, risk_flags)

    return graded, rule_of_40_metric, risk_flags, scorecard, recommendation
