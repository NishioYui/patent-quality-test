import glob
import json
import os
import subprocess
from datetime import datetime

CASES = [
    "cases/case_A_normal.txt",
    "cases/case_B_term_variation.txt",
    "cases/case_C_support_lacking.txt",
]
RUNS_PER_CASE = 3  # 直近何回分を比較に載せるか

def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def pick_latest_runs(case_file: str, n: int) -> list[str]:
    base = os.path.basename(case_file)  # case_A_normal.txt
    pattern = os.path.join("runs", f"claims_{base}_*.json")
    paths = glob.glob(pattern)
    # 更新日時でソート（新しい順）
    paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return paths[:n]

def format_run(data: dict, path: str) -> str:
    md = data.get("metadata", {})
    claims = data.get("claims", {})
    indep = claims.get("independent", {})
    deps = claims.get("dependent", [])
    warns = data.get("warnings", [])

    lines = []
    lines.append(f"--- run file: {path}")
    lines.append(f"model={md.get('model')} temp={md.get('temperature')} prompt={md.get('prompt_version')} run_id={md.get('run_id')}")
    lines.append("")
    lines.append("[Independent]")
    lines.append(f"{indep.get('id','I1')}: {indep.get('text','').strip()}")
    lines.append("")
    lines.append("[Dependent]")
    for d in deps:
        lines.append(f"{d.get('id')} (depends_on={d.get('depends_on')}): {d.get('text','').strip()}")
    lines.append("")
    lines.append("[Warnings]")
    if not warns:
        lines.append("(none)")
    else:
        for w in warns:
            code = w.get("code")
            sev = w.get("severity")
            msg = w.get("message","").strip()
            lines.append(f"- {code} [{sev}] {msg}")
    lines.append("")
    return "\n".join(lines)

def main():
    os.makedirs("runs", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join("runs", f"compare_claims_{ts}.txt")

    out = []
    out.append("=== Claims Compare Report (A/B/C) ===")
    out.append(f"generated_at={ts}")
    out.append("")

    any_found = False
    for case in CASES:
        out.append("============================================================")
        out.append(f"[CASE] {case}")
        out.append("------------------------------------------------------------")
        runs = pick_latest_runs(case, RUNS_PER_CASE)
        if not runs:
            out.append("(no runs found for this case yet)")
            out.append("")
            continue

        any_found = True
        for p in runs[::-1]:  # 古い→新しい順で表示
            data = load_json(p)
            out.append(format_run(data, p))

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))

    print(report_path)

    # 見やすくするためにメモ帳を自動で開く
    if any_found:
        subprocess.run(["notepad", report_path], check=False)
    else:
        print("No run files found. Run batch_stability_test.py first.")

if __name__ == "__main__":
    main()
