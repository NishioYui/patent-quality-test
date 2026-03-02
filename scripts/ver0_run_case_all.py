# scripts/run_case_all.py
import os
import sys
import glob
import time
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # project root
SCRIPTS = ROOT / "scripts"

def eprint(*args):
    print(*args, file=sys.stderr)

def run_script(script_filename: str, env: dict) -> str:
    script_path = SCRIPTS / script_filename
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")

    cmd = [sys.executable, str(script_path)]
    proc = subprocess.run(
        cmd,
        env=env,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.stdout.strip():
        print(proc.stdout.rstrip())
    if proc.returncode != 0:
        if proc.stderr.strip():
            eprint(proc.stderr.rstrip())
        raise RuntimeError(f"{script_filename} failed with exit code {proc.returncode}")
    return proc.stdout

def latest_file(patterns, since_ts=None):
    files = []
    for pat in patterns:
        files.extend(glob.glob(str(ROOT / pat)))

    if since_ts is not None:
        files = [f for f in files if os.path.getmtime(f) >= since_ts - 1.0]

    if not files:
        return None

    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return files[0]

def main():
    base_env = os.environ.copy()

    case_file = base_env.get("CASE_FILE", "").strip()
    if not case_file:
        raise SystemExit('CASE_FILE が未設定です。例: set "CASE_FILE=cases\\case_A_normal.txt"')

    # ---- 共通化ポイント：PDFは「指定があれば使う」「無ければ既定を探す」「無ければスキップ」 ----
    pdf_file = base_env.get("PDF_FILE", "").strip()
    default_pdf_rel = r"inputs\drawings.pdf"
    default_pdf_abs = ROOT / default_pdf_rel

    if not pdf_file:
        # PDF_FILE 未指定なら、既定パスが存在する場合だけ自動採用
        if default_pdf_abs.exists():
            pdf_file = default_pdf_rel
            print(f"[INFO] PDF_FILE not set -> using default: {pdf_file}")
        else:
            pdf_file = ""  # drawings step skip
    else:
        # PDF_FILE 指定あり：存在しなければエラーにせずスキップ（共通コマンド化のため）
        pdf_abs = ROOT / pdf_file
        if not pdf_abs.exists():
            print(f"[WARN] PDF_FILE is set but not found -> skip drawings: {pdf_abs}")
            pdf_file = ""

    img_dir = base_env.get("IMG_DIR", r"runs\images_drawings").strip()
    drawing_pages = base_env.get("DRAWING_PAGES", "").strip()

    # 既に drawings json があるならそれを優先
    drawings_json_path = base_env.get("DRAWINGS_JSON_PATH", "").strip()
    if drawings_json_path:
        p = ROOT / drawings_json_path
        if not p.exists():
            raise SystemExit(f"DRAWINGS_JSON_PATH が見つかりません: {p}")

    model = base_env.get("MODEL", "gpt-5.2")
    temperature = base_env.get("TEMPERATURE", "0.2")
    open_notepad = base_env.get("OPEN_NOTEPAD", "1").strip()  # "1" or "0"

    # ---- Step A: Drawings (optional) ----
    if not drawings_json_path:
        if pdf_file:
            env = base_env.copy()
            env["PDF_FILE"] = pdf_file
            env["IMG_DIR"] = img_dir
            env["MODEL"] = model
            env["TEMPERATURE"] = str(temperature)

            print("=== [1/4] Render PDF pages -> PNG ===")
            run_script("render_pdf_pages.py", env)

            print("=== [2/4] Extract drawings JSON from PNGs ===")
            env2 = env.copy()
            if drawing_pages:
                env2["DRAWING_PAGES"] = drawing_pages
            t1 = time.time()
            run_script("run_drawings.py", env2)

            drawings_json_path = latest_file(
                patterns=["runs/drawings_extract_*.json"],
                since_ts=t1,
            )
            if not drawings_json_path:
                raise RuntimeError("drawings_extract_*.json が見つかりません。run_drawings.py の出力を確認してください。")

            drawings_json_path = str(Path(drawings_json_path).relative_to(ROOT))
            print(f"[OK] DRAWINGS_JSON_PATH = {drawings_json_path}")
        else:
            print("=== [1/4] Drawings step skipped (no PDF provided) ===")

    # ---- Step B: Claims ----
    print("=== [3/4] Generate claims JSON ===")
    env_claims = base_env.copy()
    env_claims["CASE_FILE"] = case_file
    env_claims["MODEL"] = model
    env_claims["TEMPERATURE"] = str(temperature)
    if drawings_json_path:
        env_claims["DRAWINGS_JSON_PATH"] = drawings_json_path

    t2 = time.time()
    run_script("run_claims.py", env_claims)

    case_base = os.path.basename(case_file)
    case_stem = os.path.splitext(case_base)[0]
    claims_json_path = latest_file(
        patterns=[
            f"runs/claims_{case_base}_*.json",
            f"runs/claims_{case_stem}_*.json",
            "runs/claims_*.json",
        ],
        since_ts=t2,
    )
    if not claims_json_path:
        raise RuntimeError("claims_*.json が見つかりません。run_claims.py の出力を確認してください。")

    claims_json_path = str(Path(claims_json_path).relative_to(ROOT))
    print(f"[OK] CLAIMS_JSON_PATH = {claims_json_path}")

    # ---- Step C: Spec ----
    print("=== [4/4] Generate specification JSON ===")
    env_spec = base_env.copy()
    env_spec["CASE_FILE"] = case_file
    env_spec["CLAIMS_JSON_PATH"] = claims_json_path
    env_spec["MODEL"] = model
    env_spec["TEMPERATURE"] = str(temperature)
    if drawings_json_path:
        env_spec["DRAWINGS_JSON_PATH"] = drawings_json_path

    t3 = time.time()
    run_script("run_spec.py", env_spec)

    spec_json_path = latest_file(
        patterns=[
            f"runs/spec_{case_base}_*.json",
            f"runs/spec_{case_stem}_*.json",
            "runs/spec_*.json",
        ],
        since_ts=t3,
    )
    if not spec_json_path:
        raise RuntimeError("spec_*.json が見つかりません。run_spec.py の出力を確認してください。")

    spec_json_path = str(Path(spec_json_path).relative_to(ROOT))
    print(f"[OK] SPEC_JSON_PATH = {spec_json_path}")

    if open_notepad != "0":
        print("=== Open formatted claims in Notepad (helper) ===")
        try:
            env_np_claims = base_env.copy()
            env_np_claims["CLAIMS_JSON_PATH"] = claims_json_path
            run_script("make_claims_notepad.py", env_np_claims)
        except Exception as ex:
            eprint(f"[WARN] make_claims_notepad.py failed (ignored): {ex}")


        env_np = base_env.copy()
        env_np["SPEC_JSON_PATH"] = spec_json_path
        print("=== Open formatted spec in Notepad (helper) ===")
        try:
            run_script("make_spec_notepad.py", env_np)
        except Exception as ex:
            eprint(f"[WARN] make_spec_notepad.py failed (ignored): {ex}")

    print("\n=== DONE ===")
    print("Artifacts:")
    if drawings_json_path:
        print(f"  drawings: {drawings_json_path}")
    else:
        print("  drawings: (none)")
    print(f"  claims  : {claims_json_path}")
    print(f"  spec    : {spec_json_path}")

if __name__ == "__main__":
    main()
