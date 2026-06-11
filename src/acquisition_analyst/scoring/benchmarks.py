"""Benchmark cohort data with three-step widening lookup. Deterministic.

The packaged dataset (data/benchmarks.json) is the default; customers can
construct a BenchmarkSet from their own cohort data.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from ..models import BenchmarkCohort

_DEFAULT_MULTIPLES = {"arr_multiple_q1": 4, "arr_multiple_median": 7, "arr_multiple_q3": 10}


class BenchmarkSet:
    """Cohort benchmark data keyed by '{stage}|{vertical}|{size_band}'.

    Expected shape per cohort: metric_name → {median, q1, q3, direction}.
    Reserved keys: '_widened|{vertical}' and '_widened|default' for fallback
    cohorts, '_valuation_multiples' for solve-for-price multiples.
    """

    def __init__(self, data: dict):
        if "_widened|default" not in data:
            raise ValueError("BenchmarkSet data must include a '_widened|default' fallback cohort")
        self._data = data

    @classmethod
    @lru_cache(maxsize=1)
    def default(cls) -> "BenchmarkSet":
        raw = files("acquisition_analyst").joinpath("data/benchmarks.json").read_text()
        return cls(json.loads(raw))

    @classmethod
    def from_file(cls, path: str | Path) -> "BenchmarkSet":
        return cls(json.loads(Path(path).read_text()))

    def lookup(self, stage: str, vertical: str, size_band: str) -> tuple[BenchmarkCohort, dict]:
        """Returns (cohort metadata, benchmark dict).

        Widening: exact '{stage}|{vertical}|{size_band}' → '_widened|{vertical}'
        → '_widened|default'. Confidence: high → medium → low.
        """
        exact_key = f"{stage}|{vertical}|{size_band}"
        data = self._data.get(exact_key)
        if data:
            return (
                BenchmarkCohort(cohort_key=exact_key, confidence="high", fallback_applied=False),
                data,
            )

        wide_key = f"_widened|{vertical}"
        data = self._data.get(wide_key)
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

        return (
            BenchmarkCohort(
                cohort_key="_widened|default",
                confidence="low",
                fallback_applied=True,
                fallback_reason=f"No cohort data for '{exact_key}' or vertical '{vertical}'; using cross-cohort default.",
            ),
            self._data["_widened|default"],
        )

    def valuation_multiples(self, stage: str, vertical: str, size_band: str) -> dict:
        """ARR multiple breakpoints for solve-for-price."""
        mv = self._data.get("_valuation_multiples", {})
        key = f"{stage}|{vertical}|{size_band}"
        return mv.get(key) or mv.get("_default") or _DEFAULT_MULTIPLES
