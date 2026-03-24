from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta
import os
import shutil

from app.storage import RUNS_ROOT, read_json


def _parse_iso(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S%z")
    except Exception:
        return None


def load_retention_config() -> dict:
    mode = (os.getenv("RUN_RETENTION_MODE", "delete_after_days") or "").strip().lower()
    if mode not in {"delete_after_days", "keep_forever"}:
        mode = "delete_after_days"

    try:
        days = int(os.getenv("RUN_RETENTION_DAYS", "7"))
    except Exception:
        days = 7

    if days < 0:
        days = 7

    return {
        "mode": mode,
        "days": days,
    }


def should_delete_run(jdir: Path, now: datetime | None = None) -> tuple[bool, str]:
    """
    returns: (delete?, reason)
    安全第一:
    - done / failed 以外は消さない
    - finished_at が読めないものは消さない
    """
    cfg = load_retention_config()

    if cfg["mode"] == "keep_forever":
        return False, "keep_forever"

    st_path = jdir / "status.json"
    if not st_path.exists():
        return False, "missing_status"

    try:
        st = read_json(st_path)
    except Exception:
        return False, "invalid_status"

    status = str(st.get("status") or "")
    if status not in {"done", "failed"}:
        return False, f"status={status or 'unknown'}"

    finished_at = _parse_iso(st.get("finished_at"))
    if finished_at is None:
        return False, "missing_or_invalid_finished_at"

    if now is None:
        now = datetime.now(finished_at.tzinfo)

    cutoff = now - timedelta(days=cfg["days"])
    if finished_at > cutoff:
        return False, "not_expired"

    return True, "expired"


def cleanup_runs(dry_run: bool = False) -> dict:
    """
    runs/ 配下を走査して、保持期限切れを削除する。
    """
    cfg = load_retention_config()

    summary = {
        "mode": cfg["mode"],
        "days": cfg["days"],
        "checked": 0,
        "deleted": 0,
        "skipped": 0,
        "errors": 0,
        "deleted_job_ids": [],
        "skip_details": [],
        "error_details": [],
    }

    if not RUNS_ROOT.exists():
        return summary

    for jdir in RUNS_ROOT.iterdir():
        if not jdir.is_dir():
            continue

        summary["checked"] += 1

        try:
            do_delete, reason = should_delete_run(jdir)
            if not do_delete:
                summary["skipped"] += 1
                summary["skip_details"].append({"job_id": jdir.name, "reason": reason})
                continue

            if dry_run:
                summary["deleted"] += 1
                summary["deleted_job_ids"].append(jdir.name)
                continue

            shutil.rmtree(jdir)
            summary["deleted"] += 1
            summary["deleted_job_ids"].append(jdir.name)

        except Exception as ex:
            summary["errors"] += 1
            summary["error_details"].append({"job_id": jdir.name, "error": repr(ex)})

    return summary