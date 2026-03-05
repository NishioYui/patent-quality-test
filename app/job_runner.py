from __future__ import annotations
from pathlib import Path
from typing import Dict, Any
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
    # run_case_all の出力（claims_*.json/spec_*.json）を固定名に寄せる
    latest_claims = find_latest(jdir, "claims_*.json")
    latest_spec = find_latest(jdir, "spec_*.json")
    copy_if_exists(latest_claims, jdir / "claims.json")
    copy_if_exists(latest_spec, jdir / "spec.json")


def _read_tail_text(path: Path, max_chars: int = 20000) -> str:
    if not path.exists():
        return ""
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
        if len(txt) <= max_chars:
            return txt
        return txt[-max_chars:]
    except Exception:
        return ""


def start_job(job_id: str, env: Dict[str, str]) -> None:
    t = threading.Thread(target=_run_job, args=(job_id, env), daemon=True)
    t.start()


def _run_job(job_id: str, env: Dict[str, str]) -> None:
    jdir = job_dir(job_id)
    logs_path = _logs_path(jdir)

    # 1) running に更新
    _write_status(jdir, {
        "job_id": job_id,
        "status": "running",
        "started_at": _now_iso(),
        "error": None,
    })

    # 2) logs.txt を必ず作る（固定名保証）
    logs_path.write_text(f"START job_id={job_id} at {_now_iso()}\n", encoding="utf-8")

    cmd = [sys.executable, str(ROOT / "scripts" / "run_case_all.py")]

    try:
        # 3) subprocess 実行（ログはリアルタイム追記）
        with open(logs_path, "a", encoding="utf-8", errors="replace") as lf:
            lf.write("\n===== RUN_CASE_ALL OUTPUT (stdout+stderr) =====\n")
            lf.flush()

            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            assert proc.stdout is not None
            for line in proc.stdout:
                lf.write(line)
                lf.flush()

            rc = proc.wait()
            lf.write(f"\n===== END (exit={rc}) at {_now_iso()} =====\n")
            lf.flush()

        # 4) return code で done/failed
        if rc != 0:
            tail = _read_tail_text(logs_path)
            if "insufficient_quota" in tail:
                msg = "OpenAI quota不足（insufficient_quota）。Billing/Usage limitsを確認してください。"
            elif "RateLimitError" in tail or "Error code: 429" in tail:
                msg = "OpenAI RateLimit（429）。しばらく待つか制限/上限を確認してください。"
            else:
                msg = f"run_case_all.py failed (exit={rc})"

            _write_status(jdir, {
                "status": "failed",
                "finished_at": _now_iso(),
                "error": msg,
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
        # 例外でも logs.txt は必ず残す
        logs_path.write_text(
            _read_tail_text(logs_path, max_chars=10_000)
            + "\n\nEXCEPTION:\n" + repr(ex) + "\n\n" + traceback.format_exc(),
            encoding="utf-8",
            errors="replace",
        )
        _write_status(jdir, {
            "status": "failed",
            "finished_at": _now_iso(),
            "error": f"Exception: {repr(ex)}",
        })

    # 5) failedでも artifacts/warnings をできるだけ埋める（固定名＋一覧）
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