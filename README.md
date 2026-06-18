# acquisition-analyst

A buy-side M&A due diligence SDK for SaaS targets. Takes a target's metrics, benchmarks them against cohort data, grades every metric deterministically, and produces a structured findings object — optionally enriched with an LLM-written IC memo and due diligence questions.

**The product is the SDK** (`src/acquisition_analyst/`). The web app in `demo/` is a reference consumer.

## Design principles

- **All numbers are computed by code.** Grades, bands, scorecard, and recommendation are deterministic and reproducible. The LLM only writes prose and questions, grounded in the findings object — it cannot invent figures.
- **No silent degradation.** LLM failures raise typed exceptions (`RateLimited`, `LLMUnavailable`). Absence of API keys is an explicit, documented offline mode.
- **Bring your own benchmarks.** The packaged cohort dataset is the default; supply a `BenchmarkSet` to use your own.
- **Provider-agnostic.** Gemini, Anthropic, and OpenAI are supported out of the box; plug in any provider via the `LLMGateway` protocol.

## Install

```bash
pip install -e .                          # SDK core only (no LLM deps)
pip install -e ".[gemini]"               # + Gemini support
pip install -e ".[anthropic]"            # + Anthropic (Claude) support
pip install -e ".[openai]"               # + OpenAI (GPT) support
pip install -e ".[all-providers]"        # all three providers
pip install -e ".[demo]"                 # + demo web app
pip install -e ".[dev]"                  # + pytest
```

## SDK usage

```python
from acquisition_analyst import Analyst, AnalysisRequest, EngagementContext

# EngagementContext defines the buyer's identity and metric weight profile
engagement = EngagementContext(
    buyer_label="Acme Growth Fund",
    weights={
        "arr_growth": 0.20, "nrr": 0.15, "grr": 0.10,
        "cac_payback_months": 0.10, "ltv_cac": 0.10,
        "magic_number": 0.10, "burn_multiple": 0.10,
        "gross_margin": 0.10, "ebitda_margin": 0.05,
    },
)

analyst = Analyst()           # reads GOOGLE_API_KEY from env (Gemini, default)
findings = analyst.analyze(AnalysisRequest(**payload), engagement)

findings.scorecard.composite        # e.g. 3.42
findings.recommendation.assessment  # buy | conditional_buy | hold | pass
findings.risk_flags                 # rule-based risk list
findings.dd_questions               # LLM-generated (None in offline mode)
```

### Provider selection

The provider is auto-detected from the model name. Install the matching extra and set the right env var:

```python
from acquisition_analyst import Analyst, CLAUDE_SONNET, GPT_4O, GEMINI_FLASH

# Anthropic — reads ANTHROPIC_API_KEY
analyst = Analyst(model=CLAUDE_SONNET)

# OpenAI — reads OPENAI_API_KEY
analyst = Analyst(model=GPT_4O)

# Gemini (default) — reads GOOGLE_API_KEY, GOOGLE_API_KEY_2, … (rotated on 429)
analyst = Analyst(model=GEMINI_FLASH)

# Explicit keys override env vars
analyst = Analyst(api_keys=["sk-..."], model=CLAUDE_SONNET)

# Custom provider — pass any object implementing LLMGateway
analyst = Analyst(gateway=my_gateway)

# No keys → offline mode: deterministic engine only; LLM features raise ConfigError
analyst = Analyst()
```

Available model constants:

| Constant | Model ID |
|----------|----------|
| `GEMINI_FLASH` | `gemini-3.5-flash` |
| `GEMINI_PRO` | `gemini-3.1-pro` |
| `CLAUDE_SONNET` | `claude-sonnet-4-6` |
| `CLAUDE_HAIKU` | `claude-haiku-4-5-20251001` |
| `CLAUDE_OPUS` | `claude-opus-4-8` |
| `GPT_4O` | `gpt-4o` |
| `GPT_4O_MINI` | `gpt-4o-mini` |

### Additional capabilities

```python
memo      = analyst.write_memo(findings)                       # LLM IC memo (markdown)
questions = analyst.generate_dd_questions(findings)            # prioritized DD question list
resolved  = analyst.review_dd_questions(open_questions, findings)

# Re-run with answered DD questions carried forward (also writes the IC memo):
findings = analyst.analyze(request, engagement, existing_dd_questions=questions)

# Deterministic memo, no LLM required:
from acquisition_analyst import template_memo
md = template_memo(findings)
```

Custom benchmark data:

```python
from acquisition_analyst import Analyst, BenchmarkSet

bs = BenchmarkSet.from_file("my_benchmarks.json")  # must include "_widened|default"
engagement = EngagementContext(buyer_label="...", weights={...}, benchmarks=bs)
analyst = Analyst(model=CLAUDE_SONNET)
```

### Error handling

```python
from acquisition_analyst import ConfigError, RateLimited, LLMUnavailable

try:
    findings = analyst.analyze(request, engagement)
except RateLimited:      # all keys hit 429
    ...
except LLMUnavailable:   # model overloaded (503/529) — retry later
    ...
except ConfigError:      # LLM feature used with no keys or missing provider package
    ...
```

Gemini rotates across `GOOGLE_API_KEY`, `GOOGLE_API_KEY_2`, … automatically on 429/503.

## Architecture

```
src/acquisition_analyst/
├── client.py        # Analyst facade and EngagementContext — full pipeline in analyze()
├── models.py        # AnalysisRequest, Findings, and friends (Pydantic)
├── scoring/         # deterministic core: validation → benchmark lookup → grading
├── llm/             # gateway (multi-provider/rotation/errors), IC memo, DD questions
└── data/            # packaged benchmark cohorts
```

Pipeline: **validate → benchmark lookup (with cohort widening) → grade + scorecard + recommendation → LLM enrichment** (DD questions; IC memo on re-runs).

## Demo web app

```bash
pip install -e ".[demo]"
uvicorn demo.app:app --reload
```

Open [http://localhost:8000](http://localhost:8000). A sample target (vertical SaaS, ~$25M ARR, growth_equity) is pre-filled. Set `GOOGLE_API_KEY` (or `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) in `.env` to enable LLM features; without it the deterministic engine and template memo still work.

## Inputs

### Deal context (required)
| Field | Values |
|-------|--------|
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
- `company_description` — free-text context used by the memo writer
- `customer_concentration_top10_pct` — triggers concentration risk flag above 40%
- `series` — multi-period arrays (oldest → most recent) for trend analysis

## Grading logic

Each metric is graded against cohort benchmarks (Q1/median/Q3) with direction (`higher_better` or `lower_better`):

| Band | Points | higher_better | lower_better |
|------|--------|---------------|--------------|
| Strong | 4 | ≥ Q3 | ≤ Q1 |
| Above  | 3 | median–Q3 | Q1–median |
| Below  | 2 | Q1–median | median–Q3 |
| Weak   | 1 | < Q1 | > Q3 |

Composite = Σ(points × weight) / Σ(weights), using the weight profile from `EngagementContext`.

**Cohort lookup:** key `{stage}|{vertical}|{size_band}`. If no exact match, widens to `_widened|{vertical}`, then `_widened|default`. Confidence: `high → medium → low`.

## Testing

```bash
pip install -e ".[dev]"
pytest
```

The deterministic core (validation, benchmarks, grading, offline pipeline) is fully covered; re-running with the same input always produces identical grades, scorecard, and recommendation.
