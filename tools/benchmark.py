"""Tool 2 — Benchmark lookup with cohort widening. Deterministic."""

import json
from pathlib import Path
from models import AnalysisRequest, BenchmarkCohort

_DATA_PATH = Path(__file__).parent.parent / "data" / "benchmarks.json"
_BENCHMARKS: dict = json.loads(_DATA_PATH.read_text())


def _cohort_data(key: str) -> dict | None:
    return _BENCHMARKS.get(key)


def lookup(req: AnalysisRequest) -> tuple[BenchmarkCohort, dict]:
    """
    Returns (BenchmarkCohort metadata, benchmark_dict).
    benchmark_dict maps metric_name → {median, q1, q3, direction}.
    Applies three-step widening: exact → drop vertical → default fallback.
    """
    stage = req.stage
    vertical = req.vertical
    size_band = req.size_band

    exact_key = f"{stage}|{vertical}|{size_band}"
    data = _cohort_data(exact_key)
    if data:
        return (
            BenchmarkCohort(
                cohort_key=exact_key,
                confidence="high",
                fallback_applied=False,
            ),
            data,
        )

    # Step 1 widening: drop size_band, keep stage+vertical
    wide_key = f"_widened|{vertical}"
    data = _cohort_data(wide_key)
    if data:
        return (
            BenchmarkCohort(
                cohort_key=wide_key,
                confidence="medium",
                fallback_applied=True,
                fallback_reason=f"No exact cohort for '{exact_key}'; widened to stage-agnostic vertical '{vertical}'.",
            ),
            data,
        )

    # Step 2 widening: universal default
    data = _benchmarks_default()
    return (
        BenchmarkCohort(
            cohort_key="_widened|default",
            confidence="low",
            fallback_applied=True,
            fallback_reason=f"No cohort data for '{exact_key}' or vertical '{vertical}'; using cross-cohort default.",
        ),
        data,
    )


def _benchmarks_default() -> dict:
    return _BENCHMARKS["_widened|default"]


def get_valuation_multiples(req: AnalysisRequest) -> dict:
    """Return ARR multiple breakpoints for solve-for-price."""
    mv = _BENCHMARKS.get("_valuation_multiples", {})
    key = f"{req.stage}|{req.vertical}|{req.size_band}"
    return mv.get(key) or mv.get("_default") or {"arr_multiple_q1": 4, "arr_multiple_median": 7, "arr_multiple_q3": 10}
