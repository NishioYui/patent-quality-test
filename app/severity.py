# app/severity.py
from __future__ import annotations

from typing import Dict, List, Tuple

# MVPの暫定マップ（J案ベース）
BASE_SEVERITY: Dict[str, str] = {
    "DEPENDENCY_BROKEN": "BLOCK",
    "JSON_SCHEMA_INVALID": "BLOCK",
    "TERM_INCONSISTENCY": "BLOCK",  # MVPは一律BLOCK（最短・安全）
    "UNIT_OR_RANGE_CONFLICT": "REVIEW",
    "DRAWING_ASSUMED": "REVIEW",
    "DRAWING_INFO_LACKING": "REVIEW",
    "DRAWING_UNCLEAR": "WARN",
    "SUPPORT_LACKING": "REVIEW",  # A/B/Cはmessageで上書き
}

def severity_for_warning(code: str, message: str) -> str:
    c = (code or "").strip()
    m = (message or "")
    if c == "SUPPORT_LACKING":
        # messageに(A)(B)(C)が入る前提
        if "(A)" in m:
            return "BLOCK"
        if "(C)" in m:
            return "BLOCK"
        if "(B)" in m:
            return "REVIEW"
        return "REVIEW"
    return BASE_SEVERITY.get(c, "WARN")

def attach_severity(warnings: List[dict]) -> Tuple[List[dict], bool]:
    out: List[dict] = []
    blocked = False
    for w in warnings or []:
        code = str(w.get("code", "") or "")
        msg = str(w.get("message", "") or "")
        sev = severity_for_warning(code, msg)
        if sev == "BLOCK":
            blocked = True
        out.append({"code": code, "severity": sev, "message": msg})
    return out, blocked
