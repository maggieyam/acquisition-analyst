"""
Report agent — one LLM pass that synthesizes the deterministic findings into a
DD analysis report. Falls back to a structured template if no API key is set.
Uses Google Gemini (GOOGLE_API_KEY env var).
"""

import os
import json
from models import FindingsObject

_ASSESSMENT_LABELS = {
    "buy": "BUY",
    "conditional_buy": "CONDITIONAL BUY",
    "hold": "HOLD",
    "pass": "PASS",
}

_MODEL_FLASH   = "gemini-3.5-flash"
_MODEL_PRO     = "gemini-3.1-pro"
_MODEL_DEFAULT = _MODEL_FLASH

_SYSTEM_PROMPT = """\
You are a senior partner at a PE firm writing an Investment Committee note. Use ONLY the figures in the findings JSON and resolved DD Q&A — never invent numbers. Write in the terse, bullet-heavy style of a real IC memo: every claim has a number, every number has benchmark context, no filler. Start the memo immediately.
"""

_DD_Q_SYSTEM = """\
You are a senior buy-side M&A analyst and forensic due diligence expert. Generate a due diligence question list grounded strictly in the provided findings. Output ONLY valid JSON — no markdown fences, no preamble, no trailing text.
"""

_DD_Q_PROMPT = """\
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

_REPORT_TEMPLATE = """\
Write a concise Investment Committee note. Buyer type: {buyer_segment}. Thesis: {thesis_tags}.

Style: bullet-heavy, professional PE style. Every claim cites a specific number with benchmark context (e.g. "NRR of 118% vs. 104% median for growth-stage vertical SaaS"). No prose padding. No section introductions. Start each section with bullets immediately.

---

## SECTION 1 — INVESTMENT THESIS

4–6 bullets. Each bullet is one strong, specific claim backed by a metric and its benchmark band. Lead with the most compelling reasons to invest. Close with the single biggest structural concern.

Format each bullet as: **[Metric or theme]** — finding with number and benchmark context.

---

## SECTION 2 — DUE DILIGENCE SUMMARY

Two sub-sections. Only include if resolved DD questions are provided; otherwise omit this section entirely.

**Allayed**
- One bullet per allayed item: what was asked, what was found, why concern is resolved.

**Risk Confirmed**
- One bullet per confirmed risk: what was found, deal-structure implication (escrow / earnout / rep & warranty / price adjustment).

---

## SECTION 3 — IC RECOMMENDATION

- **Verdict:** BUY / CONDITIONAL BUY / HOLD / PASS — one-sentence rationale
- **Conditions** (if Conditional Buy): numbered list, each tied to a specific metric or DD finding
- **Deal structure:** any escrow, earnout, or rep & warranty notes implied by DD findings
- **Valuation:** if price provided — implied ARR multiple and whether justified given scorecard; if no price — solve-for range with floor/ceiling basis

---

## Findings (use only these numbers)

```json
{findings_json}
```
{dd_context}"""


def _api_keys() -> list[str]:
    """Return all configured API keys (GOOGLE_API_KEY, GOOGLE_API_KEY_2, …)."""
    keys = []
    for var in sorted(k for k in os.environ if k.startswith("GOOGLE_API_KEY")):
        val = os.environ[var].strip()
        if val:
            keys.append(val)
    return keys


def _call_with_rotation(fn):
    """Call fn(api_key) trying each key in turn; rotates on 429 or 503."""
    keys = _api_keys()
    if not keys:
        raise RuntimeError("No GOOGLE_API_KEY configured.")
    last_err = None
    for key in keys:
        try:
            return fn(key)
        except Exception as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "503" in msg or "UNAVAILABLE" in msg:
                last_err = e
                continue
            raise
    raise last_err


def write_report(findings: FindingsObject, model: str | None = None, dd_questions: list[dict] | None = None) -> str:
    selected = model if model in (_MODEL_FLASH, _MODEL_PRO) else _MODEL_DEFAULT
    if not _api_keys():
        return _template_report(findings, reason="no_key")
    try:
        return _call_with_rotation(lambda key: _llm_report(findings, key, selected, dd_questions))
    except Exception as e:
        import traceback; traceback.print_exc()
        return _template_report(findings, reason=f"llm_error: {e}")


# ── LLM path ─────────────────────────────────────────────────────────────────

def _llm_report(findings: FindingsObject, api_key: str, model: str, dd_questions: list[dict] | None = None) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return _template_report(findings)

    dc = findings.deal_context
    findings_json = findings.model_dump_json(indent=2, exclude={"report_md"})

    resolved = [q for q in (dd_questions or []) if q.get("status") == "resolved"]
    if resolved:
        lines = ["\n## Resolved Due Diligence Q&A (incorporate into your analysis)\n"]
        for q in resolved:
            outcome = q.get("outcome", "").replace("_", " ").title()
            lines.append(f"**[{outcome}] {q.get('question', '')}**")
            if q.get("answer"):
                lines.append(f"> {q['answer']}")
            lines.append("")
        dd_context = "\n".join(lines)
    else:
        dd_context = ""

    desc = dc.get("company_description") or ""
    user_msg = _REPORT_TEMPLATE.format(
        buyer_segment=dc["buyer_segment"],
        thesis_tags=", ".join(dc.get("thesis_tags") or ["(none)"]),
        findings_json=findings_json,
        dd_context=dd_context,
    )
    if desc:
        user_msg = f"## Company Description (provided by buyer)\n\n{desc}\n\n" + user_msg

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=user_msg,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            max_output_tokens=8192,
        ),
    )
    return response.text


# ── DD Question generation ────────────────────────────────────────────────────

def generate_dd_questions(findings_dict: dict, model: str | None = None, existing_questions: list[dict] | None = None) -> list[dict]:
    """Generate structured DD questions from a findings dict. Returns [] if no API key."""
    if not _api_keys():
        return []
    selected = model if model in (_MODEL_FLASH, _MODEL_PRO) else _MODEL_DEFAULT
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return []

    findings_json = json.dumps(
        {k: v for k, v in findings_dict.items() if k not in ("report_md", "dd_questions")},
        indent=2,
    )

    answered = [q for q in (existing_questions or []) if q.get("status") == "resolved"]
    if answered:
        lines = ["\nAlready-answered questions (do NOT regenerate these):\n"]
        for q in answered:
            outcome = q.get("outcome", "").replace("_", " ").title()
            lines.append(f'- [{outcome}] {q.get("question", "")}')
        existing_context = "\n".join(lines)
    else:
        existing_context = ""

    def _call(api_key):
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=selected,
            contents=_DD_Q_PROMPT.format(findings_json=findings_json, existing_context=existing_context),
            config=types.GenerateContentConfig(
                system_instruction=_DD_Q_SYSTEM,
                max_output_tokens=4096,
            ),
        )
        text  = response.text.strip()
        start = text.find("[")
        end   = text.rfind("]")
        if start == -1 or end == -1 or end < start:
            raise RuntimeError(f"No JSON array in response (first 200 chars): {text[:200]}")
        return json.loads(text[start:end + 1])

    try:
        return _call_with_rotation(_call)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise RuntimeError(f"DD question generation failed: {e}") from e


_DDQ_REVIEW_SYSTEM = """\
You are a senior buy-side M&A analyst reviewing whether open due-diligence questions have been addressed by updated financial findings. Output ONLY valid JSON — no markdown, no preamble.
"""

_DDQ_REVIEW_PROMPT = """\
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


def review_dd_questions(open_questions: list[dict], findings_dict: dict, model: str | None = None) -> list[dict]:
    """Returns list of {{id, reason}} for questions now resolved by the new findings."""
    if not open_questions or not _api_keys():
        return []
    selected = model if model in (_MODEL_FLASH, _MODEL_PRO) else _MODEL_DEFAULT
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return []

    findings_json = json.dumps(
        {k: v for k, v in findings_dict.items() if k not in ("report_md", "dd_questions")},
        indent=2,
    )
    questions_json = json.dumps(
        [{"id": q["id"], "question": q["question"], "evidence": q["evidence"]} for q in open_questions],
        indent=2,
    )

    def _call(api_key):
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=selected,
            contents=_DDQ_REVIEW_PROMPT.format(questions_json=questions_json, findings_json=findings_json),
            config=types.GenerateContentConfig(
                system_instruction=_DDQ_REVIEW_SYSTEM,
                max_output_tokens=1024,
            ),
        )
        text  = response.text.strip()
        start = text.find("[")
        end   = text.rfind("]")
        if start == -1 or end == -1:
            return []
        return json.loads(text[start:end + 1])

    try:
        return _call_with_rotation(_call)
    except Exception:
        return []


# ── Template fallback ─────────────────────────────────────────────────────────

def _template_report(findings: FindingsObject, reason: str = "no_key") -> str:
    """Deterministic template report rendered from findings — no LLM required."""
    dc = findings.deal_context
    sc = findings.scorecard
    rec = findings.recommendation
    gm = findings.graded_metrics
    val = findings.validation

    lines: list[str] = []

    lines.append("# Due Diligence Analysis Report")
    if reason == "no_key":
        note = "Report generated without LLM — no GOOGLE_API_KEY configured."
    else:
        note = f"LLM report generation failed (`{reason}`). Showing structured template instead."
    lines.append(f"\n> *{note} All figures sourced from the deterministic findings engine.*\n")

    if not val.valid:
        lines.append("## ⚠ Validation Failed")
        lines.append("\nThe following required fields are missing or invalid:\n")
        for m in val.missing:
            lines.append(f"- {m}")
        return "\n".join(lines)

    # ── 1. Executive Assessment ──────────────────────────────────────────────
    lines.append("## 1. Executive Assessment")
    assessment_label = _ASSESSMENT_LABELS.get(rec.assessment, rec.assessment.upper())
    lines.append(f"\n**Verdict: {assessment_label}**\n")
    lines.append(rec.rationale)
    lines.append(
        f"\nComposite scorecard: **{sc.composite:.2f} / 4.00** ({sc.band}) "
        f"under the `{sc.weights_profile}` weight profile."
    )
    if findings.risk_flags:
        lines.append(f"\n{len(findings.risk_flags)} risk flag(s) require attention (see Risk Register).")
    if val.warnings:
        lines.append(f"\n{len(val.warnings)} sanity warning(s) were raised during validation.")

    # ── 2. Metric-by-Metric Analysis ─────────────────────────────────────────
    lines.append("\n## 2. Metric-by-Metric Analysis")

    metric_order = [
        ("arr_growth",         "ARR Growth",         "%"),
        ("nrr",                "Net Revenue Retention (NRR)", "%"),
        ("grr",                "Gross Revenue Retention (GRR)", "%"),
        ("rule_of_40",         "Rule of 40",         "pts"),
        ("gross_margin",       "Gross Margin",        "%"),
        ("ebitda_margin",      "EBITDA Margin",       "%"),
        ("burn_multiple",      "Burn Multiple",       "x"),
        ("magic_number",       "Magic Number",        "x"),
        ("ltv_cac",            "LTV:CAC",             "x"),
        ("cac_payback_months", "CAC Payback",         " months"),
    ]

    for field, display_name, unit in metric_order:
        m = gm.get(field)
        if not m:
            continue
        bm = m.benchmark
        trend_str = f" | Trend: **{m.trend}**" if m.trend else ""
        lines.append(f"\n### {display_name}")
        lines.append(
            f"**{m.value:.1f}{unit}** — Band: **{m.band}** ({m.points}/4 pts){trend_str}"
        )
        lines.append(
            f"*Cohort `{m.cohort_key}` ({m.cohort_confidence} confidence): "
            f"P25 {bm.q1} / Median {bm.median} / P75 {bm.q3} ({bm.direction})*"
        )
        if m.series:
            series_str = " → ".join(f"{v:.1f}" for v in m.series)
            lines.append(f"Series: {series_str}")

    # ── 3. Scorecard Summary ──────────────────────────────────────────────────
    lines.append("\n## 3. Scorecard Summary")
    lines.append(f"\n| Family | Metrics | Composite | Band |")
    lines.append("|--------|---------|-----------|------|")
    for family, fs in sc.per_family.items():
        metrics_str = ", ".join(fs.metrics)
        lines.append(f"| {family.title()} | {metrics_str} | {fs.composite:.2f} | {fs.band} |")
    lines.append(f"\n**Overall Composite: {sc.composite:.3f} ({sc.band})** — Weight profile: `{sc.weights_profile}`")

    # ── 4. Risk Register ──────────────────────────────────────────────────────
    lines.append("\n## 4. Risk Register")
    if not findings.risk_flags:
        lines.append("\nNo material risk flags identified.")
    else:
        for i, flag in enumerate(findings.risk_flags, 1):
            lines.append(f"\n**Risk {i}:** {flag}")

    if val.warnings:
        lines.append("\n### Data Sanity Warnings")
        for w in val.warnings:
            lines.append(f"- {w}")

    # ── 5. Recommendation & Conditions ───────────────────────────────────────
    lines.append("\n## 5. Recommendation")
    lines.append(f"\n**{assessment_label}**\n")
    lines.append(rec.rationale)

    if rec.conditions:
        lines.append("\n**Conditions:**")
        for c in rec.conditions:
            lines.append(f"- {c}")

    if rec.solve_for_price:
        sfp = rec.solve_for_price
        lines.append(
            f"\n**Solve-for-Price Range:** ${sfp['low']}M – ${sfp['high']}M "
            f"(midpoint ${sfp['mid']}M)\n\n*Basis: {sfp['basis']}*"
        )
    elif dc.get("price") is not None:
        arr = dc["arr_usd_m"]
        price = dc["price"]
        implied = round(price / arr, 1) if arr else None
        lines.append(f"\n**Deal Price:** ${price}M (implied {implied}x ARR)")

    lines.append(
        "\n---\n*This report was generated from a deterministic findings engine. "
        "All figures are derived from buyer-provided metrics benchmarked against cohort data. "
        "No figures have been invented or extrapolated by a language model.*"
    )

    return "\n".join(lines)
