import os, subprocess, json, glob
from collections import Counter

CASES = [
  "cases/case_A_normal.txt",
  "cases/case_B_term_variation.txt",
  "cases/case_C_support_lacking.txt",
]
REPEAT = 3

def run_case(case_file):
    env = os.environ.copy()
    env["CASE_FILE"] = case_file
    p = subprocess.run(["python", "scripts/run_claims.py"], env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr)
    return p.stdout.strip()  # run_claims.py が出力する jsonパス

def summarize_one(path):
    data = json.load(open(path, "r", encoding="utf-8"))
    warns = data.get("warnings", [])
    codes = [w.get("code") for w in warns]
    return codes, warns

paths = []
all_codes = []
print("=== Running stability test ===")

for c in CASES:
    print("\n----------------------------------------")
    print(f"[CASE] {c}")
    case_codes = []
    for i in range(REPEAT):
        path = run_case(c)
        paths.append(path)

        codes, warns = summarize_one(path)
        case_codes.extend(codes)
        all_codes.extend(codes)

        print(f" run{i+1}: {path}")
        if not warns:
            print("  warnings: (none)")
        else:
            for w in warns:
                print(f"  - {w.get('code')} [{w.get('severity')}] {w.get('message')}")

    print(f"[CASE SUMMARY] {Counter(case_codes)}")

print("\n========================================")
print("ALL SUMMARY:", Counter(all_codes))
print("Saved:", len(paths), "files")
