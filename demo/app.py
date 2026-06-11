"""Demo web app for the acquisition_analyst SDK — one form, saved cases.

This app is a reference consumer of the SDK; the product is the SDK itself.
Run with:  uvicorn demo.app:app --reload
"""

import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from acquisition_analyst import (
    DEFAULT_MODEL,
    SUPPORTED_MODELS,
    AnalysisRequest,
    Analyst,
    ConfigError,
)

from .case_store import CaseStore

case_store = CaseStore()

app = FastAPI(title="M&A DD Metric Analyzer (demo)", version="0.1.0")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _make_analyst(model: str | None) -> Analyst:
    selected = model if model in SUPPORTED_MODELS else DEFAULT_MODEL
    return Analyst.from_env(model=selected)


# ── Sample target (vertical SaaS, growth_equity, ~$25M ARR) ──────────────────
SAMPLE_TARGET = {
    # Deal context
    "buyer_segment": "growth_equity",
    "thesis_tags": ["vertical-saas", "smb-focus", "land-and-expand"],
    "price": None,
    "return_target": 25.0,
    "hold_years": 5,
    "stage": "growth",
    "vertical": "vertical_saas",
    "size_band": "25-50M",
    # Headline metrics
    "arr": 25.2,
    "arr_growth": 52.0,
    "nrr": 118.0,
    "grr": 94.0,
    "cac_payback_months": 16.0,
    "ltv_cac": 3.8,
    "magic_number": 1.1,
    "burn_multiple": 0.7,
    "gross_margin": 76.0,
    "ebitda_margin": -15.0,
    # Optional DD depth
    "customer_concentration_top10_pct": 32.0,
    "series": {
        "arr_growth":         [38.0, 45.0, 52.0],
        "nrr":                [115.0, 116.0, 118.0],
        "grr":                [91.0, 93.0, 94.0],
        "cac_payback_months": [20.0, 18.0, 16.0],
        "ltv_cac":            [3.2, 3.5, 3.8],
        "magic_number":       [0.9, 1.0, 1.1],
        "burn_multiple":      [1.2, 0.9, 0.7],
        "gross_margin":       [73.0, 75.0, 76.0],
        "ebitda_margin":      [-22.0, -18.0, -15.0],
    },
}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"sample": json.dumps(SAMPLE_TARGET, indent=2)},
    )


@app.post("/analyze", response_class=HTMLResponse)
async def analyze_form(request: Request):
    """Handle HTML form submission."""
    form_data = await request.form()
    raw_json = form_data.get("payload", "")
    gemini_model = str(form_data.get("gemini_model", "")).strip() or None
    try:
        data = json.loads(raw_json)
        req = AnalysisRequest(**data)
    except Exception as e:
        return HTMLResponse(content=f"<h2>Input Error</h2><pre>{e}</pre>", status_code=400)

    analyst = _make_analyst(gemini_model)
    try:
        findings = analyst.analyze(req)
    except Exception as e:
        return HTMLResponse(content=f"<h2>Analysis Error</h2><pre>{e}</pre>", status_code=500)

    active_model = analyst.model if analyst.has_llm else ""

    # Auto-save every analysis run
    case_name = _auto_case_name(req)
    case_id   = case_store.save(case_name, json.loads(req.model_dump_json()),
                                json.loads(findings.model_dump_json()), active_model or "")

    return templates.TemplateResponse(
        request, "result.html",
        _result_context(findings, active_model or "", request_json=req.model_dump_json(),
                        case_id=case_id, case_name=case_name),
    )


# ── Cases ─────────────────────────────────────────────────────────────────────

@app.get("/cases", response_class=HTMLResponse)
async def cases_list(request: Request):
    return templates.TemplateResponse(request, "cases.html", {"cases": case_store.list_summaries()})


@app.get("/cases/{case_id}", response_class=HTMLResponse)
async def case_view(request: Request, case_id: str):
    record = case_store.get(case_id)
    if not record:
        return HTMLResponse(content="<h2>Case not found</h2>", status_code=404)

    findings_data = record["findings"]
    report_html   = _md_to_html(findings_data.get("report_md") or "")

    ctx = _result_context_from_dict(
        findings_data,
        report_html,
        gemini_model=record.get("gemini_model", ""),
        request_json=json.dumps(record.get("request", {})),
        case_id=case_id,
        case_name=record["name"],
    )
    return templates.TemplateResponse(request, "result.html", ctx)


@app.post("/cases/save")
async def case_save(request: Request):
    """Save a completed analysis (has findings)."""
    body = await request.json()
    name          = str(body.get("name", "")).strip() or "Untitled Case"
    request_data  = json.loads(body.get("request_json", "{}"))
    findings_data = json.loads(body.get("findings_json", "{}"))
    gemini_model  = str(body.get("gemini_model", ""))
    case_id = case_store.save(name, request_data, findings_data, gemini_model)
    return JSONResponse({"id": case_id})


@app.post("/cases/save-draft")
async def case_save_draft(request: Request):
    """Save inputs only (no analysis yet) as a draft case."""
    body         = await request.json()
    name         = str(body.get("name", "")).strip() or "Untitled Case"
    request_data = json.loads(body.get("request_json", "{}"))
    case_id = case_store.save(name, request_data, findings_data=None)
    return JSONResponse({"id": case_id})


@app.get("/cases/{case_id}/data")
async def case_data(case_id: str):
    """Return the saved request inputs for a case (used to load into the form)."""
    record = case_store.get(case_id)
    if not record:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"request": record.get("request", {}), "gemini_model": record.get("gemini_model", "")})


@app.post("/dd-questions")
async def dd_questions_endpoint(request: Request):
    """Generate DD questions from findings JSON. Optionally saves to a case."""
    body          = await request.json()
    findings_dict = json.loads(body.get("findings_json", "{}"))
    gemini_model  = str(body.get("gemini_model", "")).strip() or None
    case_id       = body.get("case_id")

    analyst = _make_analyst(gemini_model)
    try:
        questions = analyst.generate_dd_questions(findings_dict)
    except ConfigError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": "Question generation failed — please try again.", "detail": str(e)}, status_code=500)

    if case_id and questions:
        case_store.update_dd_questions(case_id, questions)

    return JSONResponse({"questions": questions})


@app.post("/dd-questions/review")
async def dd_questions_review(request: Request):
    """Identify which open questions are resolved by new findings, with reasons."""
    body           = await request.json()
    open_questions = body.get("open_questions", [])
    findings_dict  = json.loads(body.get("findings_json", "{}"))
    gemini_model   = str(body.get("gemini_model", "")).strip() or None

    analyst = _make_analyst(gemini_model)
    try:
        resolved = analyst.review_dd_questions(open_questions, findings_dict)
    except ConfigError:
        resolved = []
    return JSONResponse({"resolved": resolved})


@app.post("/dd-questions/save")
async def dd_questions_save(request: Request):
    """Persist the full enriched question state (with answers/status) to a case."""
    body      = await request.json()
    case_id   = body.get("case_id")
    questions = body.get("questions", [])
    if not case_id:
        return JSONResponse({"error": "case_id required"}, status_code=400)
    case_store.update_dd_questions(case_id, questions)
    return JSONResponse({"ok": True})


@app.post("/cases/{case_id}/rename")
async def case_rename(case_id: str, request: Request):
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    case_store.rename(case_id, name)
    return JSONResponse({"ok": True})


@app.post("/cases/{case_id}/rerun")
async def case_rerun(case_id: str, request: Request):
    """Re-run analysis for an existing case, carrying forward all answered DD questions."""
    record = case_store.get(case_id)
    if not record:
        return JSONResponse({"error": "Case not found"}, status_code=404)

    try:
        req = AnalysisRequest(**record["request"])
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    existing_dd_questions = None
    if record.get("findings"):
        existing_dd_questions = record["findings"].get("dd_questions") or None

    analyst = _make_analyst(record.get("gemini_model") or None)
    try:
        findings = analyst.analyze(req, existing_dd_questions=existing_dd_questions)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    findings_data = json.loads(findings.model_dump_json())
    case_store.update_findings(case_id, findings_data, analyst.model or "")

    return JSONResponse({"ok": True})


@app.post("/cases/{case_id}/delete")
async def case_delete(case_id: str):
    case_store.delete(case_id)
    return RedirectResponse(url="/cases", status_code=303)


@app.post("/analyze/json")
async def analyze_json(req: AnalysisRequest):
    """JSON API endpoint — returns findings object + report_md."""
    try:
        findings = Analyst.from_env().analyze(req)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse(content=json.loads(findings.model_dump_json()))


@app.get("/sample")
async def get_sample():
    """Return the sample target payload."""
    return JSONResponse(content=SAMPLE_TARGET)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _auto_case_name(req) -> str:
    from datetime import date
    today = date.today().strftime("%b %d")
    desc  = (req.company_description or "").strip()
    if desc:
        label = desc[:35].rstrip() + ("…" if len(desc) > 35 else "")
    else:
        parts = [p for p in [req.stage, req.vertical] if p]
        label = " · ".join(parts) if parts else req.buyer_segment
        if req.arr:
            label += f" · ${req.arr}M ARR"
    return f"{label} — {today}"


# ── Template context helpers ──────────────────────────────────────────────────

def _bar_positions(findings_dict: dict) -> dict:
    positions = {}
    for key, gm in (findings_dict.get("graded_metrics") or {}).items():
        bm = gm.get("benchmark", {})
        q1, q3 = bm.get("q1", 0), bm.get("q3", 1)
        span = q3 - q1 if q3 != q1 else 1
        pct = max(0.0, min(100.0, (gm.get("value", 0) - q1) / span * 100))
        positions[key] = round(pct, 1)
    return positions


def _result_context(findings, active_model: str, request_json: str, case_id=None, case_name=None) -> dict:
    findings_dict = json.loads(findings.model_dump_json())
    report_html   = _md_to_html(findings.report_md or "")
    return _result_context_from_dict(
        findings_dict, report_html,
        gemini_model=active_model,
        request_json=request_json,
        case_id=case_id,
        case_name=case_name,
    )


def _result_context_from_dict(findings_dict: dict, report_html: str, *,
                               gemini_model: str, request_json: str,
                               case_id=None, case_name=None) -> dict:
    rec = findings_dict.get("recommendation") or {}
    sc  = findings_dict.get("scorecard") or {}
    report_md = findings_dict.get("report_md") or ""
    return {
        "findings":          findings_dict,
        "findings_json":     json.dumps(findings_dict, indent=2),
        "request_json":      request_json,
        "report_md_escaped": report_md.replace("`", "\\`"),
        "report_html":       report_html,
        "bar_positions":     _bar_positions(findings_dict),
        "assessment":        rec.get("assessment", "unknown"),
        "composite":         sc.get("composite", 0),
        "band":              sc.get("band", ""),
        "llm_model":         gemini_model,
        "case_id":           case_id,
        "case_name":         case_name,
    }


def _md_to_html(md: str) -> str:
    from markdown_it import MarkdownIt
    return MarkdownIt().render(md)
