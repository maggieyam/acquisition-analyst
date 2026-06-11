"""
LLM-generated IC deck using PptxGenJS (same approach as Claude's built-in pptx skill).
The LLM writes JavaScript code using the PptxGenJS API; Python executes it via Node.js.
"""

import io, json, os, re, subprocess, tempfile
from pathlib import Path

# Node.js binary — nvm-managed v24
_NODE = os.environ.get(
    "NODE_BIN",
    str(Path.home() / ".nvm/versions/node/v24.16.0/bin/node"),
)
_PPTXGENJS = str(Path(__file__).parent / "node_modules/pptxgenjs")

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM = """\
You are an expert PowerPoint designer specialising in PE/M&A Investment Committee decks.
You write JavaScript using PptxGenJS to generate professional .pptx files.

═══════════════════════════════════════════════════════════════
PPTXGENJS API REFERENCE
═══════════════════════════════════════════════════════════════

Setup (always include exactly this):
  const PptxGenJS = require(PPTXGENJS_PATH);
  let pres = new PptxGenJS();
  pres.layout = "LAYOUT_WIDE"; // 13.33" × 7.5"

Add a slide:
  let slide = pres.addSlide();

SHAPES (all positions in inches):
  slide.addShape(pres.ShapeType.rect, {
    x, y, w, h,
    fill: { color: "1e3a5f" },      // hex without #
    line: { type: "none" }           // or { color: "e2e8f0", width: 1 }
  });

TEXT:
  slide.addText("Hello", {
    x, y, w, h,
    fontSize: 24,           // points
    bold: true,
    color: "FFFFFF",        // hex without #
    fontFace: "Calibri",
    align: "left",          // "left" | "center" | "right"
    valign: "middle",       // "top" | "middle" | "bottom"
    wrap: true,
  });

  // Multi-run text (mixed bold/color in one box):
  slide.addText([
    { text: "Label: ", options: { bold: true, color: "1f2937" } },
    { text: "Value",  options: { bold: false, color: "374151" } },
  ], { x, y, w, h, fontSize: 11, fontFace: "Calibri" });

TABLE:
  let rows = [
    [ // header row
      { text: "METRIC", options: { bold: true, color: "6b7280", fontSize: 9, fill: { color: "f8fafc" } } },
      { text: "VALUE",  options: { bold: true, color: "6b7280", fontSize: 9, fill: { color: "f8fafc" } } },
    ],
    [ // data row
      { text: "ARR Growth", options: { bold: true,  color: "1f2937", fontSize: 10 } },
      { text: "52%",        options: { bold: false, color: "1f2937", fontSize: 10 } },
    ],
  ];
  slide.addTable(rows, {
    x, y, w,
    colW: [2.8, 1.2, 1.4, ...],   // column widths in inches (must sum to w)
    rowH: 0.45,                    // row height in inches
    border: { type: "solid", color: "e5e7eb", pt: 0.5 },
    fontFace: "Calibri",
  });

Save (always end the file with exactly this line, using OUTPUT_PATH):
  pres.writeFile({ fileName: OUTPUT_PATH }).then(() => process.exit(0)).catch(e => { console.error(e); process.exit(1); });

═══════════════════════════════════════════════════════════════
LAYOUT GUIDE  (slide = 13.33" × 7.5")
═══════════════════════════════════════════════════════════════
  Margin:        0.5" each side
  Content width: 12.33"
  Header band:   y=0, h=1.05"
  Content start: y=1.2"
  Footer zone:   y=7.0"

  KPI ROW — 4 cards across (w=2.63" each, gap=0.54"):
    x positions: 0.5 | 3.67 | 6.84 | 10.01

  TWO-COLUMN (60/40):  Left x=0.5 w=7.0  |  Right x=7.8 w=4.93
  TWO-COLUMN (50/50):  Left x=0.5 w=5.9  |  Right x=6.8 w=5.93

═══════════════════════════════════════════════════════════════
DESIGN STANDARD  (Goldman Sachs / KKR IC aesthetic)
═══════════════════════════════════════════════════════════════
  Backgrounds:  Cover = full navy (1e3a5f). Interior slides = white.
  Header band:  navy (1e3a5f), full width, h=1.05", white title text.
  Typeface:     Calibri throughout.
  KPI numbers:  sz 32–40pt bold. Labels: 8pt ALL-CAPS gray (6b7280).
  Verdict pill: colored rect + white bold text, same x/y/w/h.
  Tables:       header row gray ALL-CAPS 9pt; data rows 10–11pt; alternating f9fafb/ffffff.
  No borders on bg shapes. Generous white space. Elements must not overlap.

  COLOUR PALETTE:
    Navy bg:       1e3a5f    Deep navy card:  142d4a    Divider:   e2e8f0
    Light blue:    93c5fd    Subtitle:        cbd5e1    Body text: 1f2937
    Gray label:    6b7280    Card light bg:   f8fafc    Alt row:   f9fafb

  BAND COLOURS:   Strong=15803d | Above=1d4ed8 | Below=b45309 | Weak=991b1b
  VERDICT COLOURS: buy=15803d | conditional_buy=b45309 | hold=b45309 | pass=991b1b

═══════════════════════════════════════════════════════════════
FEW-SHOT EXAMPLE — Cover slide (adapt values from data)
═══════════════════════════════════════════════════════════════

const PptxGenJS = require(PPTXGENJS_PATH);
let pres = new PptxGenJS();
pres.layout = "LAYOUT_WIDE";

// ── SLIDE 1: COVER ──────────────────────────────────────────
let s1 = pres.addSlide();

// Full navy background
s1.addShape(pres.ShapeType.rect, { x:0, y:0, w:"100%", h:"100%", fill:{color:"1e3a5f"}, line:{type:"none"} });

// Verdict pill (bg rect + text at same position)
s1.addShape(pres.ShapeType.rect, { x:0.5, y:0.6, w:2.0, h:0.47, fill:{color:"15803d"}, line:{type:"none"} });
s1.addText("● BUY", { x:0.5, y:0.6, w:2.0, h:0.47, fontSize:12, bold:true, color:"FFFFFF", fontFace:"Calibri", align:"center", valign:"middle" });

// Company name
s1.addText("TargetCo Inc.", { x:0.5, y:1.3, w:11.0, h:1.2, fontSize:48, bold:true, color:"FFFFFF", fontFace:"Calibri", align:"left", valign:"top" });

// Stage · Vertical subtitle
s1.addText("Growth  ·  Vertical SaaS", { x:0.5, y:2.6, w:9.0, h:0.4, fontSize:12, bold:false, color:"93c5fd", fontFace:"Calibri" });
s1.addText("INVESTMENT COMMITTEE PRESENTATION", { x:0.5, y:3.05, w:9.0, h:0.35, fontSize:10, bold:false, color:"cbd5e1", fontFace:"Calibri" });

// Divider line
s1.addShape(pres.ShapeType.rect, { x:0.5, y:3.55, w:12.33, h:0.01, fill:{color:"264e78"}, line:{type:"none"} });

// KPI cards (dark bg, light blue label, white value)
const kpis = [
  { label:"ARR",      value:"$25.2M" },
  { label:"SCORE",    value:"72/100" },
  { label:"STAGE",    value:"GROWTH" },
  { label:"VERTICAL", value:"VERT. SAAS" },
];
const kpiX = [0.5, 3.67, 6.84, 10.01];
kpis.forEach((k, i) => {
  s1.addShape(pres.ShapeType.rect, { x:kpiX[i], y:3.75, w:2.63, h:0.9, fill:{color:"142d4a"}, line:{type:"none"} });
  s1.addText(k.label, { x:kpiX[i], y:3.78, w:2.63, h:0.3,  fontSize:8,  bold:true,  color:"93c5fd", fontFace:"Calibri", align:"center" });
  s1.addText(k.value, { x:kpiX[i], y:4.08, w:2.63, h:0.5,  fontSize:26, bold:true,  color:"FFFFFF",  fontFace:"Calibri", align:"center" });
});

// Footer
s1.addText("CONFIDENTIAL  ·  June 2025", { x:0.5, y:7.1, w:12.33, h:0.3, fontSize:8, color:"6b7280", fontFace:"Calibri" });

// ... (add remaining slides then save)
pres.writeFile({ fileName: OUTPUT_PATH }).then(() => process.exit(0)).catch(e => { console.error(e); process.exit(1); });

Output ONLY valid JavaScript. No markdown fences, no explanation.
"""

# ── Per-slide briefs ──────────────────────────────────────────────────────────

_BRIEFS = {
    "Cover": """\
Follow the few-shot Cover example exactly. Substitute real data:
  • Verdict pill color = verdict colour for this deal's assessment.
    Pill text = "● [ASSESSMENT UPPERCASE]"
  • Company name: extract from company_description, or use stage + " · " + vertical.
  • KPI cards: ARR, composite score, stage, vertical (actual values).
  • Footer: "CONFIDENTIAL  ·  [current month year]"
""",

    "Transaction Overview": """\
White slide. Navy header band (y=0 h=1.05") with white title "Transaction Overview".

LEFT COLUMN (x=0.5 w=5.9 y=1.2): deal parameters as multi-run text rows (bold label + plain value),
  spaced 0.5" apart. Include: Buyer Type, Stage, Vertical, Size Band, ARR,
  Deal Price (or "Solve-for-price"), Return Target, Hold Period.

RIGHT COLUMN (x=6.8 w=5.93 y=1.2):
  • Huge composite score number (fontSize 72 navy bold, centered).
  • Band label below it (fontSize 13, colored per band).
  • Score-family mini-table below (cols: FAMILY | PTS | BAND) using addTable.
  • Risk flags in red (fontSize 9) near bottom of column.

BOTTOM KPI ROW (y=6.2 h=0.9): 4 light-bg cards (fill f8fafc, border e2e8f0 0.5pt).
  x positions: 0.5 | 3.67 | 6.84 | 10.01  w=2.63
  Labels (6b7280 8pt): ARR | NRR | CAC PAYBACK | GROSS MARGIN
  Values (1e3a5f bold 26pt): actual values from graded_metrics.
""",

    "Financial Scorecard": """\
White slide. Navy header + title "Financial Scorecard".
Full-width table (x=0.5 y=1.2 w=12.33) with ALL metrics from graded_metrics.
Column widths (must sum to 12.33"): METRIC=2.8 | VALUE=1.2 | BAND=1.4 | TREND=1.0 | PTS=0.63 | P25=1.0 | MED=1.0 | P75=1.0 | CONTEXT=2.3
Header row: gray ALL-CAPS labels, 9pt, fill f8fafc.
Data rows 10pt, alternating fill f9fafb / ffffff.
BAND cell text colored: Strong=15803d | Above=1d4ed8 | Below=b45309 | Weak=991b1b
Include every metric from graded_metrics.
""",

    "DD Findings": """\
White slide. Navy header + title "DD Findings".
If no dd_questions: centered italic gray text "No due diligence questions recorded."

Otherwise two equal columns (50/50):
LEFT (x=0.5 w=5.9 y=1.2):
  Green header bar (fill 15803d, h=0.6"): white bold 12pt "✓ Allayed (N)" centered.
  Below: each allayed question — bold 10pt question text, then italic 9pt gray answer.

RIGHT (x=6.8 w=5.93 y=1.2):
  Amber/red header (fill b45309 or 991b1b for deal_breaker, h=0.6"): white bold 12pt "⚠ Risk Confirmed (N)".
  Below: each risk_confirmed/deal_breaker question — bold 10pt + italic 9pt answer.
Space rows 0.6" apart. If a column has no items, show italic gray "None."
""",

    "IC Recommendation": """\
White slide. Navy header + title "IC Recommendation".

VERDICT PILL (x=0.5 y=1.3 w=3.5 h=0.6"):
  Colored bg rect + white bold text overlay (same x/y/w/h).
  Text: "● [ASSESSMENT UPPERCASE]" fontSize 18.

RATIONALE (x=0.5 y=2.1 w=12.33 h=0.8): paragraph fontSize 11 color 374151.

DIVIDER LINE (x=0.5 y=3.05 w=12.33 h=0.01 fill e2e8f0).

LEFT 60% (x=0.5 w=7.0 y=3.2):
  "CONDITIONS" label (8pt gray ALL-CAPS). Numbered conditions list (10pt 1f2937).
  If none: italic gray "No conditions."

RIGHT 40% (x=7.8 w=4.93 y=3.2): bordered box (fill f8fafc, border e2e8f0):
  "ENTRY PRICE" label (8pt 6b7280). Price value (30pt navy bold). Implied multiple (9pt gray).
  Or "Solve-for-price" if no price.

RISK STRIP (y=6.9): open risk flags fontSize 9 red. Omit if none.
""",
}

_SLIDE_PROMPT = """\
Generate JavaScript using PptxGenJS for ONE slide: the "{slide_name}" slide of a PE IC deck.

Buyer type: {buyer_segment}
Thesis: {thesis_tags}

Findings:
{findings_json}

Design brief:
{slide_brief}

IMPORTANT:
- Start with: const PptxGenJS = require(PPTXGENJS_PATH);
- Use variable name: let pres = new PptxGenJS(); pres.layout = "LAYOUT_WIDE";
- Name the slide variable: let slide = pres.addSlide();
- End with: pres.writeFile({{ fileName: OUTPUT_PATH }}).then(() => process.exit(0)).catch(e => {{ console.error(e); process.exit(1); }});
- Output ONLY valid JavaScript. No markdown fences, no explanation.
"""


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_ic_deck_llm(findings_dict: dict, model: str) -> bytes:
    from google import genai
    from google.genai import types
    from report_agent import _call_with_rotation

    dc   = findings_dict.get("deal_context") or {}
    slim = {k: v for k, v in findings_dict.items() if k not in ("report_md",)}
    if slim.get("dd_questions"):
        slim["dd_questions"] = [
            {f: q.get(f) for f in ("category", "priority", "question", "outcome", "answer", "status")}
            for q in slim["dd_questions"]
        ]

    common = dict(
        buyer_segment=dc.get("buyer_segment", "growth_equity"),
        thesis_tags=", ".join(dc.get("thesis_tags") or ["(none)"]),
        findings_json=json.dumps(slim, indent=2),
    )

    # Generate JS for each slide, collect all slides into one presentation
    all_slide_js = []
    for slide_name, brief in _BRIEFS.items():
        prompt = _SLIDE_PROMPT.format(
            slide_name=slide_name,
            slide_brief=brief,
            **common,
        )

        def _call(api_key, p=prompt):
            client   = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model,
                contents=p,
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    max_output_tokens=8000,
                ),
            )
            return response.text

        raw = _call_with_rotation(_call)
        slide_js = _extract_slide_js(raw)
        all_slide_js.append((slide_name, slide_js))

    return _run_pptxgenjs(all_slide_js)


# ── JS extraction ─────────────────────────────────────────────────────────────

def _extract_slide_js(raw: str) -> str:
    """Strip markdown fences; return clean JS."""
    text = raw.strip()
    text = re.sub(r'^```[a-zA-Z]*\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$', '', text, flags=re.MULTILINE)
    return text.strip()


# ── Node.js execution ─────────────────────────────────────────────────────────

def _run_pptxgenjs(slides: list[tuple[str, str]]) -> bytes:
    """Merge per-slide JS into one presentation and execute via Node.js."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "deck.pptx")
        js       = _merge_slides_js(slides, out_path)
        js_path  = os.path.join(tmpdir, "gen.js")

        with open(js_path, "w") as f:
            f.write(js)

        result = subprocess.run(
            [_NODE, js_path],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"PptxGenJS error:\n{result.stderr[:800]}")

        with open(out_path, "rb") as f:
            return f.read()


def _merge_slides_js(slides: list[tuple[str, str]], out_path: str) -> str:
    """
    Combine per-slide JS snippets into one coherent script.
    Each snippet has its own pres.addSlide() call; we strip the boilerplate
    from all but the first, then add a single writeFile at the end.
    """
    pptxgenjs_require = f'const PptxGenJS = require("{_PPTXGENJS}");'

    # Replace placeholder tokens used in LLM output
    def normalise(js: str, slide_idx: int) -> str:
        js = js.replace("PPTXGENJS_PATH", f'"{_PPTXGENJS}"')
        js = js.replace("OUTPUT_PATH", f'"{out_path}"')
        # Rename pres variable to avoid redeclaration across snippets
        if slide_idx > 0:
            js = re.sub(r'\bconst PptxGenJS\b.*\n', '', js)
            js = re.sub(r'\blet pres\s*=.*\n', '', js)
            js = re.sub(r'\bpres\.layout\b.*\n', '', js)
            js = re.sub(r'\bpres\.writeFile\b.*', '', js, flags=re.DOTALL)
        return js.strip()

    parts = []
    parts.append(pptxgenjs_require)
    parts.append('let pres = new PptxGenJS();')
    parts.append('pres.layout = "LAYOUT_WIDE";')
    parts.append('')

    for i, (name, js) in enumerate(slides):
        parts.append(f'// ── {name} ──')
        normalised = normalise(js, i)
        # Strip any stray writeFile lines from non-first slides
        normalised = re.sub(r'pres\.writeFile\(.*', '', normalised, flags=re.DOTALL).strip()
        parts.append(normalised)
        parts.append('')

    parts.append(f'pres.writeFile({{ fileName: "{out_path}" }})')
    parts.append('  .then(() => process.exit(0))')
    parts.append('  .catch(e => { console.error(String(e)); process.exit(1); });')

    return "\n".join(parts)
