import os

import pytest

from acquisition_analyst import Analyst, ConfigError, template_memo


@pytest.fixture
def offline_analyst(monkeypatch) -> Analyst:
    for var in [k for k in os.environ if k.startswith("GOOGLE_API_KEY")]:
        monkeypatch.delenv(var)
    return Analyst()  # no API keys — deterministic engine only


def test_offline_analyze(offline_analyst, sample_request, sample_engagement):
    findings = offline_analyst.analyze(sample_request, sample_engagement)
    assert findings.validation.valid
    assert findings.scorecard is not None
    assert findings.recommendation is not None
    assert findings.report_md is None  # memo only written on re-run
    assert findings.dd_questions is None  # needs LLM


def test_invalid_request_returns_early(offline_analyst, sample_request, sample_engagement):
    req = sample_request.model_copy(update={"vertical": "biotech"})
    findings = offline_analyst.analyze(req, sample_engagement)
    assert not findings.validation.valid
    assert findings.scorecard is None
    assert findings.graded_metrics == {}


def test_offline_rerun_uses_template_memo(offline_analyst, sample_request, sample_engagement):
    existing = [{"id": "q1", "question": "Why?", "category": "Growth",
                 "priority": "high", "evidence": "x", "status": "resolved"}]
    findings = offline_analyst.analyze(sample_request, sample_engagement, existing_dd_questions=existing)
    assert findings.report_md is not None
    assert "Due Diligence Analysis Report" in findings.report_md
    assert len(findings.dd_questions) == 1  # carried forward


def test_llm_features_raise_config_error_without_keys(offline_analyst, sample_request, sample_engagement):
    findings = offline_analyst.analyze(sample_request, sample_engagement)
    with pytest.raises(ConfigError):
        offline_analyst.write_memo(findings)
    with pytest.raises(ConfigError):
        offline_analyst.generate_dd_questions(findings)


def test_unsupported_model_rejected():
    with pytest.raises(ConfigError):
        Analyst(api_keys=["fake"], model="gpt-4")


def test_custom_gateway_injection():
    class FakeGateway:
        model = "my-provider/my-model"

        def generate(self, contents, *, system, max_output_tokens, model=None):
            return "stub response"

    analyst = Analyst(gateway=FakeGateway())
    assert analyst.has_llm
    assert analyst.model == "my-provider/my-model"


def test_template_memo_renders(offline_analyst, sample_request, sample_engagement):
    findings = offline_analyst.analyze(sample_request, sample_engagement)
    md = template_memo(findings)
    assert "Executive Assessment" in md
    assert "Scorecard Summary" in md


def test_analyze_is_reproducible(offline_analyst, sample_request, sample_engagement):
    f1 = offline_analyst.analyze(sample_request, sample_engagement)
    f2 = offline_analyst.analyze(sample_request, sample_engagement)
    assert f1.scorecard.composite == f2.scorecard.composite
    assert f1.recommendation.assessment == f2.recommendation.assessment
    assert f1.graded_metrics.keys() == f2.graded_metrics.keys()
