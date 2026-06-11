"""
Orchestrator — runs tools in fixed order, guarantees coverage and reproducibility.
Only the report stage calls an LLM (report + DD questions run in parallel).
"""

import json
from concurrent.futures import ThreadPoolExecutor

from models import AnalysisRequest, FindingsObject, DDQuestion
from tools import validate, benchmark, grade
from report_agent import write_report, generate_dd_questions


def run(req: AnalysisRequest, model: str | None = None, existing_dd_questions: list[dict] | None = None) -> FindingsObject:
    # ── Tool 1: Validate ──────────────────────────────────────────────────────
    validation = validate.run(req)
    if not validation.valid:
        return FindingsObject(
            deal_context=_deal_context(req),
            validation=validation,
            benchmark_cohort=None,  # type: ignore[arg-type]
            graded_metrics={},
            rule_of_40=None,        # type: ignore[arg-type]
            risk_flags=[],
            scorecard=None,         # type: ignore[arg-type]
            recommendation=None,    # type: ignore[arg-type]
            report_md=None,
        )

    # ── Tool 2: Benchmark lookup ──────────────────────────────────────────────
    cohort, bm_data = benchmark.lookup(req)

    # ── Tool 3: Grade + scorecard + recommendation ────────────────────────────
    graded_metrics, rule_of_40, risk_flags, scorecard, recommendation = grade.run(
        req, cohort, bm_data
    )

    findings = FindingsObject(
        deal_context=_deal_context(req),
        validation=validation,
        benchmark_cohort=cohort,
        graded_metrics=graded_metrics,
        rule_of_40=rule_of_40,
        risk_flags=risk_flags,
        scorecard=scorecard,
        recommendation=recommendation,
        report_md=None,
    )

    # ── LLM: DD questions + optional IC memo ─────────────────────────────────
    # Carry forward any existing answered questions before LLM calls
    if existing_dd_questions:
        findings.dd_questions = [
            DDQuestion(**{k: v for k, v in q.items() if k in DDQuestion.model_fields})
            for q in existing_dd_questions
        ]

    findings_dict = json.loads(findings.model_dump_json())

    existing_open = [q for q in (existing_dd_questions or []) if q.get("status") != "resolved"]
    skip_ddq      = bool(existing_dd_questions) and not existing_open
    # IC memo is only written on re-run (when DD answers exist)
    write_ic_memo = bool(existing_dd_questions)

    with ThreadPoolExecutor(max_workers=2) as pool:
        report_f = pool.submit(write_report, findings, model, existing_dd_questions) if write_ic_memo else None
        ddq_f    = None if skip_ddq else pool.submit(
            generate_dd_questions, findings_dict, model, existing_dd_questions
        )

    if report_f is not None:
        findings.report_md = report_f.result()

    if ddq_f is not None:
        try:
            raw_qs = ddq_f.result()
            if raw_qs:
                new_qs = [DDQuestion(**{k: v for k, v in q.items() if k in DDQuestion.model_fields})
                          for q in raw_qs]
                findings.dd_questions = (findings.dd_questions or []) + new_qs
        except Exception:
            import traceback; traceback.print_exc()

    return findings


def _deal_context(req: AnalysisRequest) -> dict:
    return {
        "buyer_segment": req.buyer_segment,
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
