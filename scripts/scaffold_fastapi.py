# scripts/scaffold_fastapi.py
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILES: dict[str, str] = {
    "requirements_api.txt": """\
fastapi==0.115.0
uvicorn[standard]==0.30.6
python-multipart==0.0.9
""",
    "app/__init__.py": """\
# app/__init__.py
""",
    "app/severity.py": """\
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
""",
    "app/invention_text.py": """\
# app/invention_text.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple

TEMPLATE_VERSION = "invention_text_v0.1"

def _get_values(payload: Dict[str, Any]) -> Dict[str, str]:
    v = payload.get("values", {})
    if not isinstance(v, dict):
        return {}
    return {str(k): "" if val is None else str(val) for k, val in v.items()}

def _get_right_types(payload: Dict[str, Any]) -> List[str]:
    rt = payload.get("rightTypes")
    if rt is None:
        rt = payload.get("right_types")
    if not isinstance(rt, list):
        return []
    return [str(x).strip() for x in rt if str(x).strip()]

def _figure_rows(payload: Dict[str, Any], values: Dict[str, str]) -> List[Tuple[str, str]]:
    figs = payload.get("figures")
    rows: List[Tuple[str, str]] = []

    if isinstance(figs, list) and figs:
        if isinstance(figs[0], dict) and ("label" in figs[0] or "desc" in figs[0]):
            for i, f in enumerate(figs):
                if not isinstance(f, dict):
                    continue
                label = str(f.get("label", "")).strip() or f"図{i+1}"
                desc = str(f.get("desc", "")).strip()
                rows.append((label, desc))
            return rows

        if isinstance(figs[0], dict) and "id" in figs[0]:
            for i, f in enumerate(figs):
                fid = str(f.get("id", "")).strip()
                if not fid:
                    continue
                label = (values.get(f"figure.{fid}.label", "") or "").strip() or f"図{i+1}"
                desc = (values.get(f"figure.{fid}.desc", "") or "").strip()
                rows.append((label, desc))
            return rows

    ids: List[str] = []
    for k in values.keys():
        if k.startswith("figure.") and k.endswith(".label"):
            mid = k[len("figure.") : -len(".label")]
            ids.append(mid)
    ids = sorted(set(ids))
    for i, fid in enumerate(ids):
        label = (values.get(f"figure.{fid}.label", "") or "").strip() or f"図{i+1}"
        desc = (values.get(f"figure.{fid}.desc", "") or "").strip()
        rows.append((label, desc))
    return rows

def build_invention_text(payload: Dict[str, Any]) -> str:
    values = _get_values(payload)
    right_types = _get_right_types(payload)

    def g(k: str) -> str:
        return (values.get(k, "") or "").rstrip()

    drawing_notes = payload.get("drawing_notes")
    if not isinstance(drawing_notes, str):
        lines: List[str] = []
        for label, desc in _figure_rows(payload, values):
            if label or desc:
                lines.append(f"{label}：{desc}".strip())
        signs = (values.get("reference_signs", "") or "").strip()
        if signs:
            lines.append("主要な符号：")
            lines.append(signs)
        drawing_notes = "\\n".join(lines).strip()

    parts: List[str] = []
    parts.append("【注意】")
    parts.append("- 捏造禁止：入力に無い新規要素・新規数値条件・新規関係を事実として追加しない。")
    parts.append("- 空欄OK：不明点は空欄のまま残す。")
    parts.append("")
    parts.append(f"【テンプレート】{TEMPLATE_VERSION}")
    parts.append("")
    parts.append("【発明の名称】")
    parts.append(g("invention_name"))
    parts.append("")
    parts.append("【権利化の種類（候補）】")
    parts.append(" / ".join(right_types))
    parts.append("")
    parts.append("【絶対に入れたい要素】")
    parts.append(g("must_include"))
    parts.append("")
    parts.append("【できれば入れたい要素】")
    parts.append(g("nice_include"))
    parts.append("")
    parts.append("【避けたい言い方・限定】")
    parts.append(g("avoid_limits"))
    parts.append("")
    parts.append("【背景技術】")
    parts.append(g("background"))
    parts.append("")
    parts.append("【課題】")
    parts.append(g("problem"))
    parts.append("")
    parts.append("【発明のコア】")
    parts.append(g("core"))
    parts.append("")
    parts.append("【主要構成要素】")
    parts.append(g("components"))
    parts.append("")
    parts.append("【処理の流れ】")
    parts.append(g("flow_steps"))
    parts.append("")
    parts.append("【条件・パラメータ】")
    parts.append(g("params"))
    parts.append("")
    parts.append("【変形例】")
    parts.append(g("variations"))
    parts.append("")
    parts.append("【効果】")
    parts.append(g("effects"))
    parts.append("")
    parts.append("【図面の状況】")
    parts.append(g("drawing_pdf_status"))
    parts.append("")
    parts.append("【図面メモ（作成予定図／符号）】")
    parts.append(str(drawing_notes or ""))
    parts.append("")
    parts.append("【未確定・要確認事項】")
    parts.append(g("uncertain"))
    parts.append("")
    return "\\n".join(parts).rstrip() + "\\n"
""",
    "app/storage.py": """\
# app/storage.py
from __future__ import annotations
from pathlib import Path
from typing import List, Optional
import json
import hashlib
import shutil

ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "runs"

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def job_dir(job_id: str) -> Path:
    return RUNS_ROOT / job_id

def atomic_write_json(path: Path, obj: dict) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def list_artifacts(jdir: Path) -> List[dict]:
    out: List[dict] = []
    for p in sorted(jdir.glob("*")):
        if p.is_dir():
            continue
        name = p.name
        size = p.stat().st_size
        digest = sha256_file(p)
        out.append({
            "name": name,
            "bytes": size,
            "sha256": digest,
            "download_url": f"/jobs/{jdir.name}/download/{name}",
        })
    return out

def copy_if_exists(src: Optional[Path], dst: Path) -> None:
    if src and src.exists():
        shutil.copy2(src, dst)

def find_latest(jdir: Path, pattern: str) -> Optional[Path]:
    files = list(jdir.glob(pattern))
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]
""",
    "app/job_runner.py": """\
# app/job_runner.py
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any
import os
import sys
import threading
import time
import subprocess
import json
import traceback

from app.storage import job_dir, atomic_write_json, read_json, list_artifacts, find_latest, copy_if_exists, ROOT
from app.severity import attach_severity

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")

def _status_path(jdir: Path) -> Path:
    return jdir / "status.json"

def _logs_path(jdir: Path) -> Path:
    return jdir / "logs.txt"

def _write_status(jdir: Path, patch: Dict[str, Any]) -> None:
    path = _status_path(jdir)
    base = {}
    if path.exists():
        try:
            base = read_json(path)
        except Exception:
            base = {}
    base.update(patch)
    atomic_write_json(path, base)

def _extract_warnings_from_json_file(p: Path) -> list:
    if not p.exists():
        return []
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        ws = obj.get("warnings", [])
        return ws if isinstance(ws, list) else []
    except Exception:
        return []

def _build_warnings_and_block(jdir: Path) -> tuple[list, bool]:
    claims = jdir / "claims.json"
    spec = jdir / "spec.json"
    warnings_raw = []
    if claims.exists():
        warnings_raw += _extract_warnings_from_json_file(claims)
    if spec.exists():
        warnings_raw += _extract_warnings_from_json_file(spec)

    warnings_with_sev, blocked = attach_severity(warnings_raw)
    return warnings_with_sev, blocked

def _canonicalize_outputs(jdir: Path) -> None:
    latest_claims = find_latest(jdir, "claims_*.json")
    latest_spec = find_latest(jdir, "spec_*.json")
    copy_if_exists(latest_claims, jdir / "claims.json")
    copy_if_exists(latest_spec, jdir / "spec.json")

def start_job(job_id: str, env: Dict[str, str]) -> None:
    t = threading.Thread(target=_run_job, args=(job_id, env), daemon=True)
    t.start()

def _run_job(job_id: str, env: Dict[str, str]) -> None:
    jdir = job_dir(job_id)
    logs_path = _logs_path(jdir)

    _write_status(jdir, {
        "job_id": job_id,
        "status": "running",
        "started_at": _now_iso(),
        "error": None,
    })

    cmd = [sys.executable, str(ROOT / "scripts" / "run_case_all.py")]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        logs_path.write_text(
            "===== STDOUT =====\\n" + (proc.stdout or "") + "\\n\\n===== STDERR =====\\n" + (proc.stderr or "") + "\\n",
            encoding="utf-8"
        )

        if proc.returncode != 0:
            _write_status(jdir, {
                "status": "failed",
                "finished_at": _now_iso(),
                "error": f"run_case_all.py failed (exit={proc.returncode})",
            })
        else:
            _canonicalize_outputs(jdir)

            warnings, blocked = _build_warnings_and_block(jdir)
            artifacts = list_artifacts(jdir)

            _write_status(jdir, {
                "status": "done",
                "finished_at": _now_iso(),
                "warnings": warnings,
                "is_blocked": blocked,
                "artifacts": artifacts,
                "error": None,
            })

    except Exception as ex:
        logs_path.write_text(
            "EXCEPTION:\\n" + repr(ex) + "\\n\\n" + traceback.format_exc(),
            encoding="utf-8"
        )
        _write_status(jdir, {
            "status": "failed",
            "finished_at": _now_iso(),
            "error": f"Exception: {repr(ex)}",
        })

    # failedでも artifacts/warnings はできるだけ埋める（logsは必ず）
    try:
        st = read_json(_status_path(jdir))
        if st.get("status") == "failed":
            _canonicalize_outputs(jdir)
            warnings, blocked = _build_warnings_and_block(jdir)
            artifacts = list_artifacts(jdir)
            _write_status(jdir, {
                "warnings": warnings,
                "is_blocked": blocked,
                "artifacts": artifacts,
            })
    except Exception:
        pass
""",
    "app/main.py": """\
# app/main.py
from __future__ import annotations
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import uuid
import os
import hashlib
import time

from app.invention_text import build_invention_text
from app.storage import job_dir, ensure_dir, atomic_write_json, read_json
from app.job_runner import start_job

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")

app = FastAPI(title="PatentDraft API", version="0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/jobs")
async def create_job(
    form_json: str = Form(...),
    drawing_pdf: UploadFile | None = File(None),
):
    try:
        payload = json.loads(form_json)
        if not isinstance(payload, dict):
            raise ValueError("form_json must be an object")
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"Invalid form_json: {repr(ex)}")

    job_id = uuid.uuid4().hex
    jdir = job_dir(job_id)
    ensure_dir(jdir)

    req_obj = {
        "job_id": job_id,
        "created_at": _now_iso(),
        "payload": payload,
        "has_pdf": bool(drawing_pdf),
        "model": os.getenv("MODEL", "gpt-5.2"),
        "temperature": float(os.getenv("TEMPERATURE", "0.2")),
    }
    atomic_write_json(jdir / "request.json", req_obj)

    invention_text = build_invention_text(payload)
    (jdir / "input.txt").write_text(invention_text, encoding="utf-8")

    h = hashlib.sha256(invention_text.encode("utf-8")).hexdigest()
    atomic_write_json(jdir / "input_meta.json", {"sha256": h})

    if drawing_pdf is not None:
        if drawing_pdf.content_type not in (None, "", "application/pdf"):
            raise HTTPException(status_code=400, detail="drawing_pdf must be application/pdf")
        pdf_path = jdir / "drawings.pdf"
        content = await drawing_pdf.read()
        pdf_path.write_bytes(content)

    atomic_write_json(jdir / "status.json", {
        "job_id": job_id,
        "status": "queued",
        "created_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "warnings": [],
        "is_blocked": False,
        "artifacts": [],
        "error": None,
    })

    run_dir_rel = f"runs/{job_id}"
    env = os.environ.copy()
    env["OPEN_NOTEPAD"] = "0"
    env["RUN_ID"] = job_id
    env["RUN_DIR"] = run_dir_rel
    env["CASE_FILE"] = run_dir_rel + "/input.txt"

    pdf_rel = run_dir_rel + "/drawings.pdf"
    if (jdir / "drawings.pdf").exists():
        env["PDF_FILE"] = pdf_rel
        env["IMG_DIR"] = run_dir_rel + "/images_drawings"
    else:
        env["PDF_FILE"] = ""

    start_job(job_id, env)

    return {"job_id": job_id, "status": "queued", "urls": {"status": f"/jobs/{job_id}"}}

@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    jdir = job_dir(job_id)
    st_path = jdir / "status.json"
    if not st_path.exists():
        raise HTTPException(status_code=404, detail="job not found")
    return read_json(st_path)

@app.get("/jobs/{job_id}/download/{filename}")
def download(job_id: str, filename: str):
    jdir = job_dir(job_id)
    if not jdir.exists():
        raise HTTPException(status_code=404, detail="job not found")

    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="invalid filename")

    fpath = jdir / filename
    if not fpath.exists() or not fpath.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    return FileResponse(path=str(fpath), filename=filename)
""",
}

def write_file(path: Path, content: str, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        print(f"[SKIP] exists: {path.relative_to(ROOT)}")
        return
    path.write_text(content, encoding="utf-8")
    print(f"[OK] wrote:  {path.relative_to(ROOT)}")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    args = ap.parse_args()

    for rel, content in FILES.items():
        write_file(ROOT / rel, content, args.force)

    print("\nDone.")
    print("Next:")
    print('  1) .venv\\Scripts\\python -m pip install -r requirements_api.txt')
    print('  2) .venv\\Scripts\\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload')

if __name__ == "__main__":
    main()