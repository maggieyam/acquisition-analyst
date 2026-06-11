"""
Thin persistence layer for saved analysis cases.
To migrate to a database, swap this class only — callers are unchanged.
Public API: save / get / list_summaries / delete
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

CASES_DIR = Path(__file__).parent / "cases"


class CaseStore:
    def __init__(self, cases_dir: Path = CASES_DIR):
        self._dir = cases_dir
        self._dir.mkdir(exist_ok=True)

    def save(self, name: str, request_data: dict, findings_data: dict | None = None, gemini_model: str = "") -> str:
        """Persist a case and return the new case ID.
        Pass findings_data=None to create a draft (inputs only, no analysis yet).
        """
        case_id = str(uuid.uuid4())
        record = {
            "id":           case_id,
            "name":         name.strip() or "Untitled Case",
            "created_at":   datetime.now(timezone.utc).isoformat(),
            "gemini_model": gemini_model,
            "request":      request_data,
            "findings":     findings_data,
        }
        (self._dir / f"{case_id}.json").write_text(json.dumps(record, indent=2))
        return case_id

    def get(self, case_id: str) -> dict | None:
        path = self._dir / f"{case_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def list_summaries(self) -> list[dict]:
        """Return lightweight summary rows sorted newest-first."""
        rows = []
        for path in self._dir.glob("*.json"):
            try:
                d = json.loads(path.read_text())
                f   = d.get("findings") or {}   # None-safe: draft cases have findings=null
                rec = f.get("recommendation") or {}
                sc  = f.get("scorecard") or {}
                dc  = f.get("deal_context") or {}
                req = d.get("request") or {}    # fall back to request for draft display fields
                has_findings = bool(f)
                rows.append({
                    "id":           d["id"],
                    "name":         d["name"],
                    "created_at":   d["created_at"],
                    "status":       "complete" if has_findings else "draft",
                    "assessment":   rec.get("assessment", ""),
                    "arr":          dc.get("arr_usd_m") or req.get("arr"),
                    "composite":    sc.get("composite"),
                    "band":         sc.get("band", ""),
                    "stage":        dc.get("stage") or req.get("stage", ""),
                    "vertical":     dc.get("vertical") or req.get("vertical", ""),
                    "gemini_model": d.get("gemini_model", ""),
                })
            except Exception:
                continue
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return rows

    def update_dd_questions(self, case_id: str, questions: list[dict]) -> bool:
        """Persist generated DD questions back into a saved case's findings."""
        path = self._dir / f"{case_id}.json"
        if not path.exists():
            return False
        record = json.loads(path.read_text())
        if record.get("findings") is None:
            record["findings"] = {}
        record["findings"]["dd_questions"] = questions
        path.write_text(json.dumps(record, indent=2))
        return True

    def update_findings(self, case_id: str, findings_data: dict, gemini_model: str = "") -> bool:
        path = self._dir / f"{case_id}.json"
        if not path.exists():
            return False
        record = json.loads(path.read_text())
        record["findings"] = findings_data
        if gemini_model:
            record["gemini_model"] = gemini_model
        path.write_text(json.dumps(record, indent=2))
        return True

    def rename(self, case_id: str, new_name: str) -> bool:
        path = self._dir / f"{case_id}.json"
        if not path.exists():
            return False
        record = json.loads(path.read_text())
        record["name"] = new_name.strip() or "Untitled Case"
        path.write_text(json.dumps(record, indent=2))
        return True

    def delete(self, case_id: str) -> bool:
        path = self._dir / f"{case_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False
