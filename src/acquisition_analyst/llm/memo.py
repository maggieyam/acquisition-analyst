"""IC memo generation: LLM-written via the gateway, plus a deterministic
template renderer (`template_memo`) that needs no LLM at all."""

from __future__ import annotations

from ..models import Findings
from .gateway import LLMGateway

ASSESSMENT_LABELS = {
    "buy": "BUY",
    "conditional_buy": "CONDITIONAL BUY",
    "hold": "HOLD",
    "pass": "PASS",
}

_SYSTEM_PROMPT = """\
You are a senior partner at a PE firm writing an Investment Committee note. Use ONLY the figures in the findings JSON and resolved DD Q&A — never invent numbers. Write in the terse, bullet-heavy style of a real IC memo: every claim has a number, every number has benchmark context, no filler. Start the memo immediately.
"""

_REPORT_TEMPLATE = """\
Write a concise Investment Committee note. Buyer: {buyer_label}. Thesis: {thesis_tags}.

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


def write_memo(gateway: LLMGateway, findings: Findings,
               dd_questions: list[dict] | None = None) -> str:
    """LLM-written IC memo. Raises typed LLM errors on failure."""
    dc = findings.deal_context
    findings_json = findings.model_dump_json(indent=2, exclude={"report_md"})

    resolved = [q for q in (dd_questions or []) if q.get("status") == "resolved"]
    if resolved:
        lines = ["\n## Resolved Due Diligence Q&A (incorporate into your analysis)\n"]
        for q in resolved:
            outcome = (q.get("outcome") or "").replace("_", " ").title()
            lines.append(f"**[{outcome}] {q.get('question', '')}**")
            if q.get("answer"):
                lines.append(f"> {q['answer']}")
            lines.append("")
        dd_context = "\n".join(lines)
    else:
        dd_context = ""

    user_msg = _REPORT_TEMPLATE.format(
        buyer_label=dc["buyer_label"],
        thesis_tags=", ".join(dc.get("thesis_tags") or ["(none)"]),
        findings_json=findings_json,
        dd_context=dd_context,
    )
    desc = dc.get("company_description") or ""
    if desc:
        user_msg = f"## Company Description (provided by buyer)\n\n{desc}\n\n" + user_msg

    return gateway.generate(user_msg, system=_SYSTEM_PROMPT, max_output_tokens=8192)


# ── Deterministic template memo (no LLM) ──────────────────────────────────────

def template_memo(findings: Findings, note: str | None = None) -> str:
    """Render a structured memo directly from findings — no LLM required."""
    dc = findings.deal_context
    sc = findings.scorecard
    rec = findings.recommendation
    gm = findings.graded_metrics
    val = findings.validation

    lines: list[str] = []
    lines.append("# Due Diligence Analysis Report")
    if note:
        lines.append(f"\n> *{note}*\n")

    if not val.valid:
        lines.append("## ⚠ Validation Failed")
        lines.append("\nThe following required fields are missing or invalid:\n")
        for m in val.missing:
            lines.append(f"- {m}")
        return "\n".join(lines)

    assert sc is not None and rec is not None

    # ── 1. Executive Assessment ──────────────────────────────────────────────
    lines.append("## 1. Executive Assessment")
    assessment_label = ASSESSMENT_LABELS.get(rec.assessment, rec.assessment.upper())
    lines.append(f"\n**Verdict: {assessment_label}**\n")
    lines.append(rec.rationale)
    lines.append(
        f"\nComposite scorecard: **{sc.composite:.2f} / 4.00** ({sc.band}) "
        f"under the `{sc.buyer_label}` weight profile."
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
        lines.append(f"**{m.value:.1f}{unit}** — Band: **{m.band}** ({m.points}/4 pts){trend_str}")
        lines.append(
            f"*Cohort `{m.cohort_key}` ({m.cohort_confidence} confidence): "
            f"P25 {bm.q1} / Median {bm.median} / P75 {bm.q3} ({bm.direction})*"
        )
        if m.series:
            lines.append("Series: " + " → ".join(f"{v:.1f}" for v in m.series))

    # ── 3. Scorecard Summary ──────────────────────────────────────────────────
    lines.append("\n## 3. Scorecard Summary")
    lines.append("\n| Family | Metrics | Composite | Band |")
    lines.append("|--------|---------|-----------|------|")
    for family, fs in sc.per_family.items():
        lines.append(f"| {family.title()} | {', '.join(fs.metrics)} | {fs.composite:.2f} | {fs.band} |")
    lines.append(f"\n**Overall Composite: {sc.composite:.3f} ({sc.band})** — Weight profile: `{sc.buyer_label}`")

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
