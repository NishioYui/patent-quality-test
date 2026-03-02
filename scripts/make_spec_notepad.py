import os
import json
import glob
import subprocess
from datetime import datetime

def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def find_latest_spec_json() -> str:
    paths = glob.glob(os.path.join("runs", "spec_*.json"))
    if not paths:
        raise SystemExit("runs\\spec_*.json が見つかりません。先に python scripts\\run_spec.py を実行してください。")
    paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return paths[0]

def fmt_warnings(warnings: list) -> str:
    if not warnings:
        return "(none)"
    lines = []
    for w in warnings:
        code = w.get("code")
        sev = w.get("severity")
        msg = (w.get("message") or "").strip()
        lines.append(f"- {code} [{sev}] {msg}")
        evs = w.get("evidence") or []
        for ev in evs:
            q = (ev.get("quote") or "").strip()
            loc = (ev.get("location") or "").strip()
            if q or loc:
                lines.append(f"    evidence: {loc} | {q}")
    return "\n".join(lines)

def main():
    # どの spec json を読むか（指定がなければ最新）
    spec_path = os.getenv("SPEC_JSON_PATH") or find_latest_spec_json()
    data = load_json(spec_path)

    md = data.get("metadata", {})
    spec = data.get("specification", {})
    warnings = data.get("warnings", [])

    # 章立て済み明細書テキスト（無ければ空）
    formatted = (spec.get("formatted_text") or "").strip()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join("runs", f"spec_readable_{ts}.txt")

    lines = []
    lines.append("=== Specification (Readable) ===")
    lines.append(f"source_json={spec_path}")
    lines.append("")
    # 付記してほしい metadata（指定の形）
    lines.append('"metadata": {')
    lines.append(f'    "model": "{md.get("model","")}",')
    lines.append(f'    "temperature": {md.get("temperature","")},')
    lines.append(f'    "prompt_version": "{md.get("prompt_version","")}",')
    lines.append(f'    "run_id": "{md.get("run_id","")}",')
    lines.append(f'    "language": "{md.get("language","")}"')
    lines.append("}")
    lines.append("")
    lines.append("=== Warnings ===")
    lines.append(fmt_warnings(warnings))
    lines.append("")
    lines.append("=== 明細書（formatted_text） ===")
    lines.append("")
    lines.append(formatted if formatted else "(formatted_text が空です。specification.formatted_text を生成するようプロンプト/スキーマを確認してください)")
    lines.append("")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(out_path)
    subprocess.run(["notepad", out_path], check=False)

if __name__ == "__main__":
    main()
