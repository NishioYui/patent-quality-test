# scripts/make_claims_notepad.py
import os
import json
import glob
import subprocess
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]

def latest_claims_json() -> str | None:
    files = glob.glob(str(ROOT / "runs" / "claims_*.json"))
    if not files:
        return None
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return files[0]

def wrap_jp(text: str, width: int = 60) -> str:
    """Very simple Japanese-friendly wrap (character count)."""
    text = text.strip()
    if not text:
        return ""
    out = []
    line = ""
    for ch in text:
        line += ch
        # Prefer breaking after Japanese punctuation
        if ch in "。、．，,;；:：":
            out.append(line)
            line = ""
        elif len(line) >= width:
            out.append(line)
            line = ""
    if line:
        out.append(line)
    return "\n".join(out)

def extract_claims(data: dict):
    # Supports current structure: {"claims": {"independent": {...}, "dependent": [...]}}
    claims = data.get("claims", data)

    independent = claims.get("independent") or {}
    dep_list = claims.get("dependent") or []

    indep_text = independent.get("text", "")
    indep_id = independent.get("id", "I1")

    deps = []
    for d in dep_list:
        deps.append({
            "id": d.get("id", ""),
            "depends_on": d.get("depends_on", ""),
            "text": d.get("text", "")
        })
    return indep_id, indep_text, deps

def main():
    claims_path = os.getenv("CLAIMS_JSON_PATH", "").strip()
    if not claims_path:
        p = latest_claims_json()
        if not p:
            raise SystemExit("CLAIMS_JSON_PATH が未設定で、runs/claims_*.json も見つかりません。")
        claims_path = str(Path(p).relative_to(ROOT))

    abs_path = ROOT / claims_path
    if not abs_path.exists():
        raise SystemExit(f"CLAIMS_JSON_PATH が見つかりません: {abs_path}")

    with open(abs_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("metadata", {})
    indep_id, indep_text, deps = extract_claims(data)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = abs_path.name.replace(".json", "")
    out_txt = ROOT / "runs" / f"{base}_formatted_{ts}.txt"

    lines = []
    lines.append("【請求項（整形出力）】")
    if meta:
        lines.append("")
        lines.append("【metadata】")
        for k in ["model", "temperature", "prompt_version", "run_id", "language"]:
            if k in meta:
                lines.append(f"- {k}: {meta[k]}")
    lines.append("")
    lines.append(f"【請求項１】 ({indep_id})")
    lines.append(wrap_jp(indep_text))
    lines.append("")

    # number dependents sequentially (2..)
    for i, d in enumerate(deps, start=2):
        dep_id = d.get("id", "")
        dep_on = d.get("depends_on", "")
        dep_text = d.get("text", "")
        lines.append(f"【請求項{i}】 ({dep_id} depends_on={dep_on})")
        lines.append(wrap_jp(dep_text))
        lines.append("")

    # optional warnings summary
    warnings = data.get("warnings") or []
    if warnings:
        lines.append("【warnings】")
        for w in warnings:
            code = w.get("code", "")
            msg = w.get("message", "")
            lines.append(f"- {code}: {msg}")
        lines.append("")

    os.makedirs(ROOT / "runs", exist_ok=True)
    with open(out_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(str(out_txt.relative_to(ROOT)))

    # open notepad unless disabled
    if os.getenv("OPEN_NOTEPAD", "1").strip() != "0":
        subprocess.Popen(["notepad", str(out_txt)])

if __name__ == "__main__":
    main()
