"""The Analyst facade — the SDK's single entry point.

The full analysis pipeline reads top-to-bottom in `analyze()`:
validate → benchmark lookup → grade → LLM enrichment (DD questions, IC memo).
All numbers are computed deterministically; the LLM only writes prose and
questions grounded in the findings.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field, model_validator

from .exceptions import ConfigError
from .llm import dd_questions as ddq
from .llm import memo as memo_mod
from .llm.gateway import DEFAULT_MODEL, LLMGateway, _gateway_for
from .models import AnalysisRequest, DDQuestion, Findings
from .scoring import BenchmarkSet, grade, validate


class EngagementContext(BaseModel):
    """Buyer-specific config passed to each analysis call.

    buyer_label: freeform identifier echoed in output (e.g. "Blackstone Growth")
    weights: full metric weight profile — must sum to 1.0
    benchmarks: cohort benchmark data; defaults to the packaged SaaS dataset
    """
    model_config = {"arbitrary_types_allowed": True}

    buyer_label: str
    weights: dict[str, float]
    benchmarks: BenchmarkSet = Field(default_factory=BenchmarkSet.default)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "EngagementContext":
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"weights must sum to 1.0 (got {total:.4f})")
        return self

logger = logging.getLogger("acquisition_analyst")


class Analyst:
    """M&A due-diligence analyst.

    By default uses Gemini: pass api_keys explicitly, or omit to read
    GOOGLE_API_KEY / GOOGLE_API_KEY_2 / … from the environment automatically.
    To use a different provider, pass any `gateway` implementing LLMGateway.
    With neither, the deterministic engine still works (`analyze` runs
    offline); LLM features raise ConfigError.
    """

    def __init__(
        self,
        api_keys: list[str] | None = None,
        model: str = DEFAULT_MODEL,
        gateway: LLMGateway | None = None,
    ):
        if gateway is not None:
            self._gateway = gateway
        else:
            self._gateway = _gateway_for(model, api_keys)

    @property
    def has_llm(self) -> bool:
        return self._gateway is not None

    @property
    def model(self) -> str | None:
        return self._gateway.model if self._gateway else None

    # ── Core pipeline ─────────────────────────────────────────────────────────

    def analyze(self, request: AnalysisRequest, engagement: EngagementContext, *,
                existing_dd_questions: list[dict] | None = None) -> Findings:
        """Run the full analysis pipeline.

        Deterministic stages always run. LLM stages run only when API keys are
        configured: DD questions are generated unless every existing question
        is already resolved; the IC memo is written only on re-runs (when
        `existing_dd_questions` is provided), using the deterministic template
        when no LLM is configured.
        """
        # 1. Validate
        validation = validate(request)
        if not validation.valid:
            return Findings(deal_context=_deal_context(request, engagement.buyer_label), validation=validation)

        # 2. Benchmark lookup (with cohort widening)
        cohort, bm_data = engagement.benchmarks.lookup(request.stage, request.vertical, request.size_band)

        # 3. Grade → scorecard → recommendation
        multiples = engagement.benchmarks.valuation_multiples(request.stage, request.vertical, request.size_band)
        result = grade(request, cohort, bm_data, multiples, engagement.weights, engagement.buyer_label)

        findings = Findings(
            deal_context=_deal_context(request, engagement.buyer_label),
            validation=validation,
            benchmark_cohort=cohort,
            graded_metrics=result.graded_metrics,
            rule_of_40=result.rule_of_40,
            risk_flags=result.risk_flags,
            scorecard=result.scorecard,
            recommendation=result.recommendation,
        )

        # 4. Carry forward existing DD questions
        if existing_dd_questions:
            findings.dd_questions = [
                DDQuestion(**{k: v for k, v in q.items() if k in DDQuestion.model_fields})
                for q in existing_dd_questions
            ]

        # 5. LLM enrichment — memo on re-run; new DD questions unless all resolved
        open_existing = [q for q in (existing_dd_questions or []) if q.get("status") != "resolved"]
        want_memo = bool(existing_dd_questions)
        want_ddq = not (existing_dd_questions and not open_existing)

        if not self.has_llm:
            if want_memo:
                findings.report_md = memo_mod.template_memo(
                    findings, note="Report generated without LLM — no API key configured.",
                )
            if want_ddq:
                logger.info("Skipping DD question generation: no API key configured.")
            return findings

        findings_dict = json.loads(findings.model_dump_json())
        with ThreadPoolExecutor(max_workers=2) as pool:
            memo_f = pool.submit(self.write_memo, findings, existing_dd_questions) if want_memo else None
            ddq_f = pool.submit(
                ddq.generate_questions, self._gateway, findings_dict, existing_dd_questions,
            ) if want_ddq else None

        if memo_f is not None:
            findings.report_md = memo_f.result()
        if ddq_f is not None:
            new_qs = [
                DDQuestion(**{k: v for k, v in q.items() if k in DDQuestion.model_fields})
                for q in ddq_f.result()
            ]
            findings.dd_questions = (findings.dd_questions or []) + new_qs

        return findings

    # ── LLM features ──────────────────────────────────────────────────────────

    def write_memo(self, findings: Findings, dd_questions: list[dict] | None = None) -> str:
        """LLM-written IC memo. Use `template_memo()` for the no-LLM version."""
        return memo_mod.write_memo(self._require_gateway(), findings, dd_questions)

    def generate_dd_questions(self, findings: Findings | dict,
                              existing_questions: list[dict] | None = None) -> list[dict]:
        return ddq.generate_questions(
            self._require_gateway(), _as_dict(findings), existing_questions,
        )

    def review_dd_questions(self, open_questions: list[dict],
                            findings: Findings | dict) -> list[dict]:
        return ddq.review_questions(self._require_gateway(), open_questions, _as_dict(findings))

    def _require_gateway(self) -> LLMGateway:
        if self._gateway is None:
            raise ConfigError(
                "This feature requires an LLM. Pass api_keys or a gateway to Analyst(), or set GOOGLE_API_KEY in the environment.",
            )
        return self._gateway


def _as_dict(findings: Findings | dict) -> dict:
    if isinstance(findings, Findings):
        return json.loads(findings.model_dump_json())
    return findings


def _deal_context(req: AnalysisRequest, buyer_label: str) -> dict:
    return {
        "buyer_label": buyer_label,
        "thesis_tags": req.thesis_tags,
        "price": req.price,
        "return_target": req.return_target,
        "hold_years": req.hold_years,
        "stage": req.stage,
        "vertical": req.vertical,
        "size_band": req.size_band,
        "arr_usd_m": req.arr,
        "company_description": req.company_description,
    }
