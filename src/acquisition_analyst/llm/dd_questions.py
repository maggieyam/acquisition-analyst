"""Due diligence question generation and review."""

from __future__ import annotations

import json

from ..exceptions import LLMError
from .gateway import LLMGateway

_GENERATE_SYSTEM = """\
You are a senior buy-side M&A analyst and forensic due diligence expert. Generate a due diligence question list grounded strictly in the provided findings. Output ONLY valid JSON — no markdown fences, no preamble, no trailing text.
"""

_GENERATE_PROMPT = """\
Generate a prioritized due diligence question list for this acquisition target, including data integrity checks.

Return ONLY a raw JSON array — no markdown, no fences, no explanation before or after.
Each element has exactly these keys:
- "category": one of "Retention", "Growth", "Unit Economics", "Efficiency", "Competitive", "People & Operations", "Legal & Risk", "Data Integrity"
- "priority": one of "critical", "high", "medium"
- "question": one concise sentence naming the exact metric or inconsistency
- "evidence": the specific value or pattern from the findings that triggered this question
- "materials": array of 1-2 specific documents to request

Rules:
- 8–12 questions total (keep output compact)
- Every "critical" question must map to a risk flag, a Weak-band metric, or a detected inconsistency
- No generic questions — each must reference a specific number from the findings
- Order: critical first, then high, then medium
- Do NOT generate questions that are substantially similar to any already-answered question listed below

Data Integrity — actively look for these red flags and raise a question for each one found:
- Metric contradictions: e.g. NRR significantly higher than GRR implies large expansion revenue — is magic number consistent with that?
- Impossible combinations: GRR can never exceed NRR; burn multiple improving while magic number worsens is contradictory
- Suspiciously perfect trends: every metric improving every period simultaneously is statistically rare
- Round-number clustering: metrics reported as exact round numbers across multiple periods suggest smoothing
- Missing context: very high NRR with no customer concentration data withheld; strong growth with no cohort breakdown
- Definition gaming: ask how key metrics are defined (e.g. is ARR recognized or contracted? does NRR include reactivations?)

Findings:
{findings_json}
{existing_context}"""

_REVIEW_SYSTEM = """\
You are a senior buy-side M&A analyst reviewing whether open due-diligence questions have been addressed by updated financial findings. Output ONLY valid JSON — no markdown, no preamble.
"""

_REVIEW_PROMPT = """\
Review these open due diligence questions against the updated findings below.

A question is RESOLVED if the specific metric or concern that triggered it has materially improved — for example, the metric moved from Weak/Below to Strong/Above band, or a risk flag is no longer present.

Output ONLY a JSON array of questions that are now resolved. Each element:
{{"id": "<question id>", "reason": "<one sentence citing the specific new value and band, e.g. NRR improved to 109% (Strong band) from prior 101% (Below)>"}}

If none are resolved, output: []

Open questions:
{questions_json}

Updated findings:
{findings_json}
"""


def _slim_findings_json(findings_dict: dict) -> str:
    return json.dumps(
        {k: v for k, v in findings_dict.items() if k not in ("report_md", "dd_questions")},
        indent=2,
    )


def _parse_json_array(text: str) -> list:
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise LLMError(f"No JSON array in model response (first 200 chars): {text[:200]}")
    return json.loads(text[start:end + 1])


def generate_questions(gateway: LLMGateway, findings_dict: dict,
                       existing_questions: list[dict] | None = None) -> list[dict]:
    """Generate structured DD questions from a findings dict."""
    answered = [q for q in (existing_questions or []) if q.get("status") == "resolved"]
    if answered:
        lines = ["\nAlready-answered questions (do NOT regenerate these):\n"]
        for q in answered:
            outcome = (q.get("outcome") or "").replace("_", " ").title()
            lines.append(f'- [{outcome}] {q.get("question", "")}')
        existing_context = "\n".join(lines)
    else:
        existing_context = ""

    text = gateway.generate(
        _GENERATE_PROMPT.format(
            findings_json=_slim_findings_json(findings_dict),
            existing_context=existing_context,
        ),
        system=_GENERATE_SYSTEM,
        max_output_tokens=4096,
    )
    return _parse_json_array(text.strip())


def review_questions(gateway: LLMGateway, open_questions: list[dict],
                     findings_dict: dict) -> list[dict]:
    """Return [{id, reason}] for open questions now resolved by the new findings."""
    if not open_questions:
        return []

    questions_json = json.dumps(
        [{"id": q["id"], "question": q["question"], "evidence": q["evidence"]} for q in open_questions],
        indent=2,
    )
    text = gateway.generate(
        _REVIEW_PROMPT.format(
            questions_json=questions_json,
            findings_json=_slim_findings_json(findings_dict),
        ),
        system=_REVIEW_SYSTEM,
        max_output_tokens=1024,
    )
    try:
        return _parse_json_array(text.strip())
    except (LLMError, json.JSONDecodeError):
        return []
