# scripts/run_case_all.py
import os
import sys
import glob
import time
import json
import uuid
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
    # stdout は従来どおり表示（run_claims/run_spec は out_path をprintする）
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

def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

def main():
    base_env = os.environ.copy()

    # ---- RUN_ID / RUN_DIR を確定して全ステップに渡す（コスト集計のため） ----
    run_dir = base_env.get("RUN_DIR", "runs").strip() or "runs"
    base_env["RUN_DIR"] = run_dir
    (ROOT / run_dir).mkdir(parents=True, exist_ok=True)

    run_id = base_env.get("RUN_ID", "").strip() or str(uuid.uuid4())
    base_env["RUN_ID"] = run_id

    print(f"[INFO] RUN_DIR = {run_dir}")
    print(f"[INFO] RUN_ID  = {run_id}")

    case_file = base_env.get("CASE_FILE", "").strip()
    if not case_file:
        raise SystemExit('CASE_FILE が未設定です。例: set "CASE_FILE=cases\\case_A_normal.txt"')

    # ---- 共通化ポイント：PDFは「指定があれば使う」「未指定なら既定を探す」「空文字ならスキップ」 ----
    # 重要：base_env.get("PDF_FILE", None)
    #   - None: 未指定（CLIで既定PDFを自動採用したいケース）
    #   - ""  : 明示スキップ（API経由の図面なし）
    pdf_env = base_env.get("PDF_FILE", None)

    default_pdf_rel = r"inputs\drawings.pdf"
    default_pdf_abs = ROOT / default_pdf_rel

    if pdf_env is None:
        # PDF_FILE が“未指定”のときだけ、既定PDFを自動採用（CLI向け）
        if default_pdf_abs.exists():
            pdf_file = default_pdf_rel
            print(f"[INFO] PDF_FILE not set -> using default: {pdf_file}")
        else:
            pdf_file = ""  # drawings step skip
    else:
        # PDF_FILE が“指定”されている（空文字も含む）
        pdf_file = str(pdf_env).strip()
        if not pdf_file:
            pdf_file = ""  # 明示スキップ（API経由の図面なし）
        else:
            pdf_abs = ROOT / pdf_file
            if not pdf_abs.exists():
                print(f"[WARN] PDF_FILE is set but not found -> skip drawings: {pdf_abs}")
                pdf_file = ""

    # IMG_DIR の既定は RUN_DIR 配下に寄せる（整理）
    img_dir = base_env.get("IMG_DIR", fr"{run_dir}\images_drawings").strip()
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

    # 探索パターン（RUN_DIR と runs の両方を見る：移行途中の事故防止）
    run_dir_posix = run_dir.replace("\\", "/")
    def pats(*rel_patterns: str):
        out = []
        for p in rel_patterns:
            out.append(p.format(run=run_dir_posix))
            if run_dir_posix != "runs":
                out.append(p.format(run="runs"))
        return out

    # ---- Step A: Drawings (optional) ----
    if not drawings_json_path:
        if pdf_file:
            env = base_env.copy()
            env["CASE_FILE"] = case_file            # ★drawingsのcost命名に必要
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
                patterns=pats("{run}/drawings_extract_*.json"),
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
        patterns=pats(
            "{run}/claims_" + case_base + "_*.json",
            "{run}/claims_" + case_stem + "_*.json",
            "{run}/claims_*.json",
        ),
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
        patterns=pats(
            "{run}/spec_" + case_base + "_*.json",
            "{run}/spec_" + case_stem + "_*.json",
            "{run}/spec_*.json",
        ),
        since_ts=t3,
    )
    if not spec_json_path:
        raise RuntimeError("spec_*.json が見つかりません。run_spec.py の出力を確認してください。")

    spec_json_path = str(Path(spec_json_path).relative_to(ROOT))
    print(f"[OK] SPEC_JSON_PATH = {spec_json_path}")

    # ---- Cost summary（drawings/claims/spec：式＋JPY） ----
    usd_jpy = float((base_env.get("USDJPY", "") or os.getenv("USDJPY", "") or "155").strip())

    def _format_formula(it: int, ot: int, pin: float, pout: float, cost_usd):
        template = "cost_usd = (input_tokens/1e6)*price_in + (output_tokens/1e6)*price_out"
        if cost_usd is None:
            return {"template": template, "substituted": None}

        in_usd = (it / 1_000_000.0) * pin
        out_usd = (ot / 1_000_000.0) * pout
        substituted = (
            f"= ({it}/1e6)*{pin} + ({ot}/1e6)*{pout} "
            f"= {in_usd:.6f} + {out_usd:.6f} "
            f"= {float(cost_usd):.6f}"
        )
        return {
            "template": template,
            "substituted": substituted,
            "input_cost_usd": in_usd,
            "output_cost_usd": out_usd,
        }

    summary = {
        "run_id": run_id,
        "run_dir": run_dir,
        "case_file": case_file,
        "model": model,
        "temperature": float(temperature) if str(temperature).strip() else None,
        "fx": {"usd_jpy": usd_jpy, "source": "ENV:USDJPY (default=155)"},
        "steps": {},
        "total": {"cost_usd": 0.0, "cost_jpy": 0.0, "input_tokens": 0, "output_tokens": 0},
    }

    required_steps = {"claims", "spec"}   # ここが無いと “一連” として成立しない
    total_cost_known = True
    step_costs_usd = []

    for step in ["drawings", "claims", "spec"]:
        cost_candidates = [ROOT / run_dir / f"cost_{step}_{case_base}_{run_id}.json"]
        if run_dir != "runs":
            cost_candidates.append(ROOT / "runs" / f"cost_{step}_{case_base}_{run_id}.json")

        cost_path = next((p for p in cost_candidates if p.exists()), None)
        if cost_path is None:
            summary["steps"][step] = {"found": False}
            if step in required_steps:
                total_cost_known = False
            continue

        obj = _read_json(cost_path)
        it = int(obj.get("input_tokens", 0))
        ot = int(obj.get("output_tokens", 0))

        pin = obj.get("price_input_per_1m")
        pout = obj.get("price_output_per_1m")
        cost_usd = obj.get("cost_usd")

        summary["steps"][step] = {"found": True, **obj}

        # 式の表示（priceが無いと代入が作れない）
        if isinstance(pin, (int, float)) and isinstance(pout, (int, float)):
            summary["steps"][step]["formula"] = _format_formula(it, ot, float(pin), float(pout), cost_usd)
        else:
            summary["steps"][step]["formula"] = {
                "template": "cost_usd = (input_tokens/1e6)*price_in + (output_tokens/1e6)*price_out",
                "substituted": None,
                "note": "price not available in cost file",
            }

        summary["total"]["input_tokens"] += it
        summary["total"]["output_tokens"] += ot

        if cost_usd is not None:
            summary["total"]["cost_usd"] += float(cost_usd)
            step_costs_usd.append({"step": step, "cost_usd": float(cost_usd)})
        else:
            if step in required_steps:
                total_cost_known = False

    if not total_cost_known:
        summary["total"]["cost_usd"] = None
        summary["total"]["cost_jpy"] = None
    else:
        summary["total"]["cost_jpy"] = round(summary["total"]["cost_usd"] * usd_jpy, 2)
        summary["total"]["cost_usd_breakdown"] = step_costs_usd
        summary["total"]["equation_jpy"] = (
            f"cost_jpy = cost_usd * USDJPY = {summary['total']['cost_usd']:.6f} * {usd_jpy} = {summary['total']['cost_jpy']}"
        )

    summary_path = ROOT / run_dir / f"cost_summary_{case_base}_{run_id}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] COST_SUMMARY_PATH = {str(summary_path.relative_to(ROOT))}")

    # ---- Notepad helpers ----
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
    print(f"  cost    : {str(summary_path.relative_to(ROOT))}")

if __name__ == "__main__":
    main()