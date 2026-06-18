from acquisition_analyst.models import MetricSeries
from acquisition_analyst.scoring import BenchmarkSet, grade
from acquisition_analyst.scoring.grading import _compute_trend, _grade_value


_TEST_WEIGHTS = {
    "arr_growth": 0.20, "nrr": 0.15, "rule_of_40": 0.10, "magic_number": 0.10,
    "burn_multiple": 0.10, "gross_margin": 0.10, "ltv_cac": 0.10,
    "grr": 0.05, "cac_payback_months": 0.05, "ebitda_margin": 0.05,
}

def _grade(req):
    bs = BenchmarkSet.default()
    cohort, data = bs.lookup(req.stage, req.vertical, req.size_band)
    multiples = bs.valuation_multiples(req.stage, req.vertical, req.size_band)
    return grade(req, cohort, data, multiples, _TEST_WEIGHTS, "Test Buyer")


# ── Band assignment ───────────────────────────────────────────────────────────

def test_grade_value_higher_better():
    bm = {"q1": 10, "median": 20, "q3": 30, "direction": "higher_better"}
    assert _grade_value(35, bm) == ("Strong", 4)
    assert _grade_value(25, bm) == ("Above", 3)
    assert _grade_value(15, bm) == ("Below", 2)
    assert _grade_value(5, bm) == ("Weak", 1)


def test_grade_value_lower_better():
    bm = {"q1": 10, "median": 20, "q3": 30, "direction": "lower_better"}
    assert _grade_value(5, bm) == ("Strong", 4)
    assert _grade_value(15, bm) == ("Above", 3)
    assert _grade_value(25, bm) == ("Below", 2)
    assert _grade_value(35, bm) == ("Weak", 1)


# ── Trend ─────────────────────────────────────────────────────────────────────

def test_trend_improving():
    assert _compute_trend([10, 12, 15]) == "improving"


def test_trend_lower_better_inverts():
    assert _compute_trend([20, 18, 16], direction="lower_better") == "improving"


def test_trend_requires_two_points():
    assert _compute_trend([10]) is None
    assert _compute_trend(None) is None


# ── Full grading pipeline ─────────────────────────────────────────────────────

def test_grading_is_deterministic(sample_request):
    r1 = _grade(sample_request)
    r2 = _grade(sample_request)
    assert r1.scorecard.composite == r2.scorecard.composite
    assert r1.recommendation.assessment == r2.recommendation.assessment


def test_rule_of_40_derived(sample_request):
    result = _grade(sample_request)
    assert result.rule_of_40.value == sample_request.arr_growth + sample_request.ebitda_margin


def test_all_headline_metrics_graded(sample_request):
    result = _grade(sample_request)
    assert len(result.graded_metrics) == 10  # 9 headline + rule_of_40


def test_solve_for_price_when_no_price(sample_request):
    result = _grade(sample_request)
    sfp = result.recommendation.solve_for_price
    assert sfp is not None
    assert sfp["low"] <= sfp["mid"] <= sfp["high"]


def test_no_solve_for_price_when_price_given(sample_request):
    req = sample_request.model_copy(update={"price": 200.0})
    result = _grade(req)
    assert result.recommendation.solve_for_price is None


def test_weak_metrics_trigger_risk_flags(sample_request):
    req = sample_request.model_copy(update={"nrr": 92.0, "grr": 75.0, "ltv_cac": 1.5})
    result = _grade(req)
    assert any("NRR below 100%" in f for f in result.risk_flags)
    assert any("GRR" in f for f in result.risk_flags)
    assert any("LTV:CAC" in f for f in result.risk_flags)


def test_severe_risks_downgrade_assessment(sample_request):
    strong = _grade(sample_request).recommendation.assessment
    weak_req = sample_request.model_copy(update={"nrr": 92.0, "grr": 75.0, "ltv_cac": 1.5, "burn_multiple": 4.0})
    weak = _grade(weak_req).recommendation.assessment
    order = ["pass", "hold", "conditional_buy", "buy"]
    assert order.index(weak) < order.index(strong)


def test_series_trend_in_graded_metrics(sample_request):
    req = sample_request.model_copy(update={
        "series": MetricSeries(nrr=[110.0, 114.0, 118.0]),
    })
    result = _grade(req)
    assert result.graded_metrics["nrr"].trend == "improving"
