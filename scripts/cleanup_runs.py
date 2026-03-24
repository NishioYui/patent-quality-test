from __future__ import annotations

from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT / ".env")

from app.retention import cleanup_runs  # noqa: E402


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    summary = cleanup_runs(dry_run=dry_run)

    print("=== cleanup_runs ===")
    print(f"mode    : {summary['mode']}")
    print(f"days    : {summary['days']}")
    print(f"checked : {summary['checked']}")
    print(f"deleted : {summary['deleted']}")
    print(f"skipped : {summary['skipped']}")
    print(f"errors  : {summary['errors']}")

    if summary["deleted_job_ids"]:
        print("deleted_job_ids:")
        for job_id in summary["deleted_job_ids"]:
            print(f"  - {job_id}")

    if summary["error_details"]:
        print("error_details:")
        for item in summary["error_details"]:
            print(f"  - {item['job_id']}: {item['error']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())