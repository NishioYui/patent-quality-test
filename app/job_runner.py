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
            "===== STDOUT =====\n" + (proc.stdout or "") + "\n\n===== STDERR =====\n" + (proc.stderr or "") + "\n",
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
            "EXCEPTION:\n" + repr(ex) + "\n\n" + traceback.format_exc(),
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
