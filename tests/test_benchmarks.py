import pytest

from acquisition_analyst.scoring import BenchmarkSet


def test_default_set_loads():
    bs = BenchmarkSet.default()
    cohort, data = bs.lookup("growth", "vertical_saas", "25-50M")
    assert cohort.confidence == "high"
    assert not cohort.fallback_applied
    assert "arr_growth" in data


def test_widening_to_vertical():
    bs = BenchmarkSet.default()
    cohort, data = bs.lookup("late", "fintech", "0-5M")  # no exact cohort
    assert cohort.fallback_applied
    assert cohort.confidence in ("medium", "low")
    assert "arr_growth" in data


def test_widening_to_default():
    bs = BenchmarkSet.default()
    cohort, data = bs.lookup("late", "nonexistent_vertical", "0-5M")
    assert cohort.cohort_key == "_widened|default"
    assert cohort.confidence == "low"


def test_custom_data_requires_default_cohort():
    with pytest.raises(ValueError):
        BenchmarkSet({"growth|saas|10M": {}})


def test_custom_data_lookup():
    bs = BenchmarkSet({
        "growth|vertical_saas|25-50M": {"nrr": {"median": 105, "q1": 98, "q3": 112, "direction": "higher_better"}},
        "_widened|default": {"nrr": {"median": 100, "q1": 95, "q3": 108, "direction": "higher_better"}},
    })
    cohort, data = bs.lookup("growth", "vertical_saas", "25-50M")
    assert cohort.confidence == "high"
    assert data["nrr"]["median"] == 105


def test_valuation_multiples_fallback():
    bs = BenchmarkSet.default()
    m = bs.valuation_multiples("late", "nonexistent", "0-5M")
    assert m["arr_multiple_q1"] <= m["arr_multiple_median"] <= m["arr_multiple_q3"]
