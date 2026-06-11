# M&A DD Metric Analyzer

A buy-side due diligence tool that takes a target's SaaS metrics, benchmarks them against cohort data, grades every metric deterministically, and produces a structured DD report.

## Architecture

```
orchestrator (plain code, fixed order)
  → tool 1: validate completeness        (deterministic)
  → tool 2: benchmark lookup             (deterministic)
  → tool 3: grade + scorecard + recommendation  (deterministic)
  → report agent (LLM): synthesize findings into the report
```

All numbers (grades, bands, scorecard, recommendation) are computed by code and are fully reproducible. The LLM only writes the prose report, grounded in the findings object — it cannot invent figures.

## Quickstart

```bash
pip install -r requirements.txt
uvicorn app:app --reload
```

Then open [http://localhost:8000](http://localhost:8000). A sample target (vertical SaaS, ~$25M ARR, growth_equity) is pre-filled.

## LLM report (optional)

Set `ANTHROPIC_API_KEY` to enable the LLM-written report. Without it, a structured template report is generated from the findings object — all figures remain deterministic either way.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn app:app --reload
```

## JSON API

```bash
# Run analysis via API
curl -X POST http://localhost:8000/analyze/json \
  -H "Content-Type: application/json" \
  -d @sample.json

# Get the pre-filled sample payload
curl http://localhost:8000/sample
```

## Inputs

### Deal context (required)
| Field | Values |
|-------|--------|
| `buyer_segment` | `growth_equity` \| `lmm` \| `strategic` |
| `thesis_tags` | `[]` (free-form strings) |
| `price` | USD millions, or `null` → solve-for-price |
| `return_target` | Target IRR, e.g. `25.0` |
| `hold_years` | Integer, 1–15 |
| `stage` | `early` \| `growth` \| `late` |
| `vertical` | `vertical_saas` \| `horizontal_saas` \| `fintech` \| `healthtech` \| `other` |
| `size_band` | `0-5M` \| `5-10M` \| `10-25M` \| `25-50M` \| `50-100M` \| `100M+` |

### Headline metrics (required)
`arr`, `arr_growth`, `nrr`, `grr`, `cac_payback_months`, `ltv_cac`, `magic_number`, `burn_multiple`, `gross_margin`, `ebitda_margin`

`rule_of_40` is derived (`arr_growth + ebitda_margin`).

### DD-depth (optional)
- `customer_concentration_top10_pct` — triggers concentration risk flag above 40%
- `series` — multi-period arrays (oldest → most recent) for trend analysis:
  `arr_growth`, `nrr`, `grr`, `cac_payback_months`, `ltv_cac`, `magic_number`, `burn_multiple`, `gross_margin`, `ebitda_margin`

## Grading logic

Each metric is graded against cohort benchmarks (Q1/median/Q3) with direction (`higher_better` or `lower_better`):

| Band | Points | higher_better | lower_better |
|------|--------|---------------|--------------|
| Strong | 4 | ≥ Q3 | ≤ Q1 |
| Above  | 3 | median–Q3 | Q1–median |
| Below  | 2 | Q1–median | median–Q3 |
| Weak   | 1 | < Q1 | > Q3 |

Composite = Σ(points × weight) / Σ(weights), using buyer-segment weight profiles.

## Cohort lookup & widening

Lookup key: `{stage}|{vertical}|{size_band}` (e.g. `growth|vertical_saas|25-50M`).

If no exact match: widens to `_widened|{vertical}` (drops stage/size), then to `_widened|default`. Confidence: `high → medium → low`.

## Benchmark data

Seed cohorts in `data/benchmarks.json`. Add cohorts by adding a new key with per-metric `{median, q1, q3, direction}`. Valuation multiples for solve-for-price live in `_valuation_multiples`.

## Output

The `/analyze/json` endpoint returns a `FindingsObject` with:
- `validation` — completeness + sanity warnings
- `benchmark_cohort` — cohort used + confidence
- `graded_metrics` — per metric: value, benchmark breakpoints, band, points, trend, series
- `rule_of_40` — derived metric, same structure
- `risk_flags` — rule-based list
- `scorecard` — composite score, per-family breakdown, band
- `recommendation` — assessment, rationale, conditions, solve-for-price (if price=null)
- `report_md` — the full DD report in Markdown

Re-running with the same input produces identical `graded_metrics`, `scorecard`, and `recommendation` every time.
