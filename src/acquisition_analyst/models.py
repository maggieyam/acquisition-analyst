"""Public request/response types."""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


# ── Input models ──────────────────────────────────────────────────────────────

class MetricSeries(BaseModel):
    """Optional multi-period series; values ordered oldest → most-recent."""
    arr_growth: Optional[list[float]] = None
    nrr: Optional[list[float]] = None
    grr: Optional[list[float]] = None
    cac_payback_months: Optional[list[float]] = None
    ltv_cac: Optional[list[float]] = None
    magic_number: Optional[list[float]] = None
    burn_multiple: Optional[list[float]] = None
    gross_margin: Optional[list[float]] = None
    ebitda_margin: Optional[list[float]] = None


class AnalysisRequest(BaseModel):
    # Deal context
    thesis_tags: list[str] = Field(default_factory=list)
    price: Optional[float] = Field(None, description="Total deal price (USD M). Null → solve-for-price.")
    return_target: float = Field(..., description="Target IRR, e.g. 25.0 for 25%")
    hold_years: int = Field(..., ge=1, le=15)
    stage: str = Field(..., description="early | growth | late")
    vertical: str = Field(..., description="vertical_saas | horizontal_saas | fintech | healthtech | other")
    size_band: str = Field(..., description="0-5M | 5-10M | 10-25M | 25-50M | 50-100M | 100M+")

    # Headline required metrics
    arr: float = Field(..., description="ARR in USD millions")
    arr_growth: float = Field(..., description="YoY ARR growth %")
    nrr: float = Field(..., description="Net Revenue Retention %")
    grr: float = Field(..., description="Gross Revenue Retention %")
    cac_payback_months: float = Field(..., description="CAC payback in months")
    ltv_cac: float = Field(..., description="LTV:CAC ratio")
    magic_number: float = Field(..., description="Sales efficiency (ARR added / S&M spend)")
    burn_multiple: float = Field(..., description="Net burn / net new ARR")
    gross_margin: float = Field(..., description="Gross margin %")
    ebitda_margin: float = Field(..., description="EBITDA margin %")

    # Optional DD-depth fields
    company_description: Optional[str] = Field(None, description="Free-text description of what the company does, its market, and competitive positioning.")
    customer_concentration_top10_pct: Optional[float] = None
    series: Optional[MetricSeries] = None


# ── Findings (structured output of the deterministic engine) ──────────────────

class BenchmarkBand(BaseModel):
    median: float
    q1: float
    q3: float
    direction: str  # higher_better | lower_better


class GradedMetric(BaseModel):
    value: float
    benchmark: BenchmarkBand
    band: str          # Strong | Above | Below | Weak
    points: int        # 4 | 3 | 2 | 1
    trend: Optional[str] = None   # improving | flat | declining | None
    series: Optional[list[float]] = None
    cohort_key: str
    cohort_confidence: str  # high | medium | low


class FamilyScore(BaseModel):
    metrics: list[str]
    composite: float
    band: str


class Scorecard(BaseModel):
    buyer_label: str
    per_family: dict[str, FamilyScore]
    composite: float
    band: str


class RecommendationResult(BaseModel):
    assessment: str        # buy | conditional_buy | hold | pass
    rationale: str
    conditions: list[str]
    solve_for_price: Optional[dict] = None  # {"low": X, "high": Y, "basis": str}


class ValidationResult(BaseModel):
    valid: bool
    missing: list[str]
    warnings: list[str]


class BenchmarkCohort(BaseModel):
    cohort_key: str
    confidence: str       # high | medium | low
    fallback_applied: bool
    fallback_reason: Optional[str] = None


class DDQuestion(BaseModel):
    category: str   # Retention | Growth | Unit Economics | Efficiency | Competitive | People & Operations | Legal & Risk | Data Integrity
    priority: str   # critical | high | medium
    question: str
    evidence: str
    materials: list[str] = []
    id: Optional[str] = None
    status: Optional[str] = None   # open | resolved
    outcome: Optional[str] = None  # allayed | risk_confirmed | deal_breaker
    answer: Optional[str] = None


class Findings(BaseModel):
    deal_context: dict
    validation: ValidationResult
    benchmark_cohort: Optional[BenchmarkCohort] = None
    graded_metrics: dict[str, GradedMetric] = {}
    rule_of_40: Optional[GradedMetric] = None
    risk_flags: list[str] = []
    scorecard: Optional[Scorecard] = None
    recommendation: Optional[RecommendationResult] = None
    report_md: Optional[str] = None
    dd_questions: Optional[list[DDQuestion]] = None
