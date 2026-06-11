import pytest

from acquisition_analyst import Analyst, ConfigError, template_memo


@pytest.fixture
def offline_analyst() -> Analyst:
    return Analyst()  # no API keys — deterministic engine only


def test_offline_analyze(offline_analyst, sample_request):
    findings = offline_analyst.analyze(sample_request)
    assert findings.validation.valid
    assert findings.scorecard is not None
    assert findings.recommendation is not None
    assert findings.report_md is None  # memo only written on re-run
    assert findings.dd_questions is None  # needs LLM


def test_invalid_request_returns_early(offline_analyst, sample_request):
    req = sample_request.model_copy(update={"vertical": "biotech"})
    findings = offline_analyst.analyze(req)
    assert not findings.validation.valid
    assert findings.scorecard is None
    assert findings.graded_metrics == {}


def test_offline_rerun_uses_template_memo(offline_analyst, sample_request):
    existing = [{"id": "q1", "question": "Why?", "category": "Growth",
                 "priority": "high", "evidence": "x", "status": "resolved"}]
    findings = offline_analyst.analyze(sample_request, existing_dd_questions=existing)
    assert findings.report_md is not None
    assert "Due Diligence Analysis Report" in findings.report_md
    assert len(findings.dd_questions) == 1  # carried forward


def test_llm_features_raise_config_error_without_keys(offline_analyst, sample_request):
    findings = offline_analyst.analyze(sample_request)
    with pytest.raises(ConfigError):
        offline_analyst.write_memo(findings)
    with pytest.raises(ConfigError):
        offline_analyst.generate_dd_questions(findings)


def test_unsupported_model_rejected():
    with pytest.raises(ConfigError):
        Analyst(api_keys=["fake"], model="gpt-4")


def test_template_memo_renders(offline_analyst, sample_request):
    findings = offline_analyst.analyze(sample_request)
    md = template_memo(findings)
    assert "Executive Assessment" in md
    assert "Scorecard Summary" in md


def test_analyze_is_reproducible(offline_analyst, sample_request):
    f1 = offline_analyst.analyze(sample_request)
    f2 = offline_analyst.analyze(sample_request)
    assert f1.scorecard.composite == f2.scorecard.composite
    assert f1.recommendation.assessment == f2.recommendation.assessment
    assert f1.graded_metrics.keys() == f2.graded_metrics.keys()
