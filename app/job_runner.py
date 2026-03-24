from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, Optional
import os
import sys
import threading
import time
import subprocess
import json
import traceback
import hashlib

from app.storage import (
    job_dir,
    atomic_write_json,
    read_json,
    list_artifacts,
    find_latest,
    copy_if_exists,
    ROOT,
    RUNS_ROOT,
)
from app.severity import attach_severity
from app.docx_export import build_patent_docx


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _status_path(jdir: Path) -> Path:
    return jdir / "status.json"


def _logs_path(jdir: Path) -> Path:
    return jdir / "logs.txt"


def _write_status(jdir: Path, patch: Dict[str, Any]) -> None:
    path = _status_path(jdir)
    base: Dict[str, Any] = {}
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


def _extract_metadata(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        md = obj.get("metadata", {}) if isinstance(obj, dict) else {}
        return md if isinstance(md, dict) else {}
    except Exception:
        return {}


def _build_warnings_and_block(jdir: Path) -> tuple[list, bool]:
    claims = jdir / "claims.json"
    spec = jdir / "spec.json"
    warnings_raw: list = []
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


def _build_prompt_versions(jdir: Path) -> dict:
    md_claims = _extract_metadata(jdir / "claims.json")
    md_spec = _extract_metadata(jdir / "spec.json")
    return {
        "claims": md_claims.get("prompt_version"),
        "spec": md_spec.get("prompt_version"),
    }


def _build_runtime_meta(jdir: Path, env: Dict[str, str]) -> dict:
    md_claims = _extract_metadata(jdir / "claims.json")
    md_spec = _extract_metadata(jdir / "spec.json")

    model = md_spec.get("model") or md_claims.get("model") or env.get("MODEL")
    temperature = md_spec.get("temperature") or md_claims.get("temperature") or env.get("TEMPERATURE")

    out: Dict[str, Any] = {"prompt_versions": _build_prompt_versions(jdir)}
    if model is not None:
        out["model"] = model
    if temperature is not None:
        try:
            out["temperature"] = float(temperature)
        except Exception:
            out["temperature"] = temperature
    return out


def _classify_error(tail: str) -> tuple[str, str]:
    """
    returns: (error_code, error_detail_for_ops)
    UIに出す文言は固定。ここは運用向けの分類だけ行う。
    """
    t = (tail or "")
    tl = t.lower()

    # ---- subprocess / local runtime ----
    if "no such file or directory" in tl and "run_case_all.py" in tl:
        return "SUBPROCESS_START_FAILED", "run_case_all.py の起動失敗"

    if "no such file or directory" in tl or "filenotfounderror" in tl or "[errno 2]" in tl:
        return "FILE_NOT_FOUND", "必要ファイルが見つからない"

    if "permissionerror" in tl or "[errno 13]" in tl or "access is denied" in tl:
        return "PERMISSION_DENIED", "ファイル/ディレクトリアクセス拒否"

    # ---- OpenAI auth / quota / rate ----
    if "api_key must be set" in tl or "openai_api_key" in tl:
        return "API_KEY_NOT_SET", "APIキー未設定/読み込み失敗"

    if "error code: 401" in tl or "authenticationerror" in tl or "invalid api key" in tl:
        return "AUTH_FAILED", "OpenAI認証失敗（401 / invalid api key）"

    if "error code: 403" in tl or ("permission denied" in tl and "openai" in tl):
        return "AUTH_FAILED", "OpenAI権限不足（403）"

    if "insufficient_quota" in tl:
        return "INSUFFICIENT_QUOTA", "OpenAI quota不足（insufficient_quota）"

    if "ratelimiterror" in tl or "error code: 429" in tl:
        return "RATE_LIMIT", "OpenAI 429 RateLimit"

    # ---- OpenAI request / server ----
    if "error code: 400" in tl or "badrequesterror" in tl:
        return "OPENAI_BAD_REQUEST", "OpenAI 400 Bad Request"

    if (
        "internalservererror" in tl
        or "error code: 500" in tl
        or "error code: 502" in tl
        or "error code: 503" in tl
        or "error code: 504" in tl
    ):
        return "OPENAI_SERVER_ERROR", "OpenAIサーバ側エラー（5xx）"

    # ---- network / timeout ----
    if (
        "apiconnectionerror" in tl
        or "connectionerror" in tl
        or "connecttimeout" in tl
        or "readtimeout" in tl
        or "sslerror" in tl
    ):
        return "NETWORK_ERROR", "外部API接続失敗（ネットワーク/SSL）"

    if (
        "apitimeouterror" in tl
        or "timeouterror" in tl
        or "timed out" in tl
        or "timeout expired" in tl
    ):
        return "TIMEOUT", "タイムアウト"

    # ---- dependency ----
    if "modulenotfounderror" in tl and ("fitz" in tl or "pymupdf" in tl):
        return "DRAWING_DEPENDENCY_MISSING", "図面解析依存不足（PyMuPDF/fitz）"

    if "modulenotfounderror" in tl:
        return "DEPENDENCY_MISSING", "依存ライブラリ不足（ModuleNotFoundError）"

    # ---- drawing / pdf ----
    if "fitz" in tl or "pymupdf" in tl:
        return "DRAWING_PARSE_FAILED", "図面解析失敗（PyMuPDF/fitz）"

    if "pdf" in tl and (
        "cannot open" in tl
        or "invalid pdf" in tl
        or "pdfdataerror" in tl
        or "is empty" in tl
        or "broken" in tl
        or "corrupt" in tl
    ):
        return "PDF_INVALID", "PDF不正/破損/読込失敗"

    # ---- JSON / schema ----
    if (
        "json_schema" in tl
        or "schema validation" in tl
        or "does not conform to schema" in tl
        or ("validationerror" in tl and "schema" in tl)
    ):
        return "JSON_SCHEMA_INVALID", "JSON schema不一致"

    if (
        "jsondecodeerror" in tl
        or "expecting value" in tl
        or "extra data" in tl
        or "expecting ',' delimiter" in tl
    ):
        return "OUTPUT_JSON_INVALID", "JSONパース失敗"

    return "UNKNOWN", "未知の失敗（logs.txt参照）"


def _detect_failed_step(tail: str) -> str | None:
    tl = (tail or "").lower()

    # run_case_all の例外メッセージで判定
    if "run_drawings.py failed" in tl:
        return "drawings"
    if "render_pdf_pages.py failed" in tl:
        return "drawings"
    if "run_claims.py failed" in tl:
        return "claims"
    if "run_spec.py failed" in tl:
        return "spec"
    return None


# ---------- prompt fingerprint & mismatch (status.json only, no new output files) ----------

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT)).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def _files_for_step(step: str) -> list[Path]:
    if step == "claims":
        return [
            ROOT / "prompts" / "claims_system.txt",
            ROOT / "prompts" / "claims_user.txt",
            ROOT / "schemas" / "claims_only.schema.json",
        ]
    if step == "spec":
        return [
            ROOT / "prompts" / "spec_system.txt",
            ROOT / "prompts" / "spec_user.txt",
            ROOT / "schemas" / "spec_only.schema.json",
        ]
    return []


def _compute_prompt_fingerprints() -> dict:
    """
    status.json に保存するための指紋（sha256）。
    """
    out: dict[str, dict[str, str]] = {}
    for step in ("claims", "spec"):
        fps: dict[str, str] = {}
        for p in _files_for_step(step):
            key = _rel(p)
            if p.exists():
                fps[key] = _sha256_file(p)
            else:
                fps[key] = "MISSING"
        out[step] = fps
    return out


def _find_prev_fingerprints(job_id: str, step: str, prompt_version: str) -> Optional[dict]:
    """
    出力ファイルを増やさないため、runs/配下の過去 job の status.json を走査し、
    同じ prompt_version の直近ジョブの fingerprints を取得する。
    """
    if not prompt_version:
        return None

    candidates: list[tuple[float, dict]] = []

    for d in RUNS_ROOT.iterdir():
        if not d.is_dir():
            continue
        if d.name == job_id:
            continue
        stp = d / "status.json"
        if not stp.exists():
            continue
        try:
            st = read_json(stp)
        except Exception:
            continue

        pv = (st.get("prompt_versions") or {}).get(step)
        if pv != prompt_version:
            continue

        fps = (st.get("prompt_fingerprints") or {}).get(step)
        if not isinstance(fps, dict):
            continue

        try:
            mtime = stp.stat().st_mtime
        except Exception:
            mtime = 0.0
        candidates.append((mtime, fps))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _build_prompt_mismatch_ops(job_id: str, prompt_versions: dict, cur_fps: dict) -> dict:
    mismatch_any = False
    baseline_missing_steps = []
    details: dict[str, Any] = {}

    for step in ("claims", "spec"):
        pv = prompt_versions.get(step)
        cur = cur_fps.get(step) or {}
        prev = _find_prev_fingerprints(job_id, step, str(pv) if pv is not None else "")

        if prev is None:
            baseline_missing_steps.append(step)
            details[step] = {
                "prompt_version": pv,
                "mismatch": False,
                "baseline": "missing (first seen for this prompt_version)",
                "changed_files": [],
            }
            continue

        changed = [k for k, v in cur.items() if prev.get(k) != v]
        mismatch = len(changed) > 0
        if mismatch:
            mismatch_any = True

        details[step] = {
            "prompt_version": pv,
            "mismatch": mismatch,
            "changed_files": changed,
        }

    # 優先順位：mismatch > baseline_missing > OK
    ops_flags = []
    if mismatch_any:
        ops_flags.append("PROMPT_VERSION_MISMATCH")
        bad_steps = [s for s in ("claims", "spec") if details.get(s, {}).get("mismatch")]
        ops_summary = f"PROMPT_VERSION_MISMATCH: same prompt_version but prompt/schema changed. steps={','.join(bad_steps)}"
        check_state = "MISMATCH"
    elif baseline_missing_steps:
        ops_flags.append("PROMPT_VERSION_BASELINE_MISSING")
        ops_summary = f"PROMPT_VERSION_BASELINE_MISSING: first run for prompt_version. steps={','.join(baseline_missing_steps)}"
        check_state = "BASELINE_MISSING"
    else:
        ops_summary = "OK"
        check_state = "OK"

    return {
        "prompt_version_mismatch": mismatch_any,
        "prompt_version_mismatch_details": details,
        "prompt_version_baseline_missing": bool(baseline_missing_steps),
        "prompt_version_baseline_missing_steps": baseline_missing_steps,
        "ops_flags": ops_flags,
        "ops_summary": ops_summary,
        "ops_prompt_version_check": check_state,
    }


# ---------- venv python for run_case_all (optional but safe) ----------

def _detect_python_bin() -> str:
    if os.name == "nt":
        cand = ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        cand = ROOT / ".venv" / "bin" / "python"
    if cand.exists():
        return str(cand)
    return sys.executable


def start_job(job_id: str, env: Dict[str, str]) -> None:
    t = threading.Thread(target=_run_job, args=(job_id, env), daemon=True)
    t.start()


def _run_job(job_id: str, env: Dict[str, str]) -> None:
    jdir = job_dir(job_id)
    logs_path = _logs_path(jdir)

    # 1) running に更新
    _write_status(
        jdir,
        {
            "job_id": job_id,
            "status": "running",
            "started_at": _now_iso(),
            "error": None,
            "error_code": None,
            "error_detail": None,
            "failed_step": None,
        },
    )

    # 2) logs.txt を必ず作る（固定名保証）
    logs_path.write_text(f"START job_id={job_id} at {_now_iso()}\n", encoding="utf-8")

    try:
        # 親プロセスも venv python を優先（混在事故を減らす）
        PYTHON_BIN = (env.get("PYTHON_BIN") or _detect_python_bin())
        cmd = [PYTHON_BIN, str(ROOT / "scripts" / "run_case_all.py")]

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
            code, detail = _classify_error(tail)
            failed_step = _detect_failed_step(tail)

            # UI向け文言は固定（詳細は出さない）
            user_msg = f"生成に失敗しました。時間をおいてもう一度お試しください。\n解決しない場合は受付IDを添えて下のボタンからご連絡ください。\n受付ID: {job_id}"

            _canonicalize_outputs(jdir)

            # 失敗でも、取れる範囲でメタ・指紋を残す
            runtime_meta = _build_runtime_meta(jdir, env)
            cur_fps = _compute_prompt_fingerprints()
            ops = _build_prompt_mismatch_ops(job_id, runtime_meta.get("prompt_versions", {}), cur_fps)

            _write_status(
                jdir,
                {
                    "status": "failed",
                    "finished_at": _now_iso(),
                    "error": user_msg,
                    "error_code": code,
                    "error_detail": detail,
                    "failed_step": failed_step,
                    "prompt_fingerprints": cur_fps,
                    **runtime_meta,
                    **ops,
                },
            )

        else:
            _canonicalize_outputs(jdir)

            # DOCX生成（非fatal：失敗してもJSON成果物は返す）
            try:
                build_patent_docx(jdir, include_warnings=True)
            except Exception as ex:
                with open(logs_path, "a", encoding="utf-8", errors="replace") as lf:
                    lf.write("\n===== DOCX EXPORT FAILED =====\n")
                    lf.write(repr(ex) + "\n")
                    lf.write(traceback.format_exc() + "\n")
                    lf.flush()

            warnings, blocked = _build_warnings_and_block(jdir)
            artifacts = list_artifacts(jdir)

            runtime_meta = _build_runtime_meta(jdir, env)
            cur_fps = _compute_prompt_fingerprints()
            ops = _build_prompt_mismatch_ops(job_id, runtime_meta.get("prompt_versions", {}), cur_fps)

            _write_status(
                jdir,
                {
                    "status": "done",
                    "finished_at": _now_iso(),
                    "warnings": warnings,
                    "is_blocked": blocked,
                    "artifacts": artifacts,
                    "error": None,
                    "error_code": None,
                    "error_detail": None,
                    "failed_step": None,
                    "prompt_fingerprints": cur_fps,
                    **runtime_meta,
                    **ops,
                },
            )

    except Exception as ex:
        logs_path.write_text(
            _read_tail_text(logs_path, max_chars=10_000)
            + "\n\nEXCEPTION:\n"
            + repr(ex)
            + "\n\n"
            + traceback.format_exc(),
            encoding="utf-8",
            errors="replace",
        )

        tail = _read_tail_text(logs_path)
        code, detail = _classify_error(tail)
        failed_step = _detect_failed_step(tail)

        # 例外時も、運用しやすい最小の情報は残す
        runtime_meta = _build_runtime_meta(jdir, env)
        cur_fps = _compute_prompt_fingerprints()
        ops = _build_prompt_mismatch_ops(job_id, runtime_meta.get("prompt_versions", {}), cur_fps)

        _write_status(
            jdir,
            {
                "status": "failed",
                "finished_at": _now_iso(),
                "error": f"生成に失敗しました。時間をおいてもう一度お試しください。\n解決しない場合は受付IDを添えて下のボタンからご連絡ください。\n受付ID: {job_id}",
                "error_code": code,
                "error_detail": f"{detail} / raw={repr(ex)}",
                "failed_step": failed_step,
                "prompt_fingerprints": cur_fps,
                **runtime_meta,
                **ops,
            },
        )

    # 5) failedでも artifacts/warnings はできるだけ埋める（logsは必ず）
    try:
        st = read_json(_status_path(jdir))
        if st.get("status") == "failed":
            _canonicalize_outputs(jdir)

            warnings, blocked = _build_warnings_and_block(jdir)
            artifacts = list_artifacts(jdir)

            patch = {
                "warnings": warnings,
                "is_blocked": blocked,
                "artifacts": artifacts,
            }
            _write_status(jdir, patch)
    except Exception:
        pass