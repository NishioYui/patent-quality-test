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


# ---- artifact visibility policy (user downloadable) ----
# ここを唯一の真実(SSOT)にして、list_artifacts / download 両方が同じ判定を使う。

_USER_ALLOW_NAMES = {"claims.json", "spec.json"}

# ★タプルは末尾にカンマ必須
_USER_ALLOW_PREFIXES = ("drawings_extract_",)

# ★docxは最小要件として許可（必要ならさらに絞る）
_USER_ALLOW_SUFFIXES = (".docx",)

# 明示的に拒否（将来増えても安全）
_USER_DENY_NAMES = {
    "logs.txt",
    "status.json",
    "request.json",
    "input.txt",
    "input_meta.json",
}

# ★prefixで拒否したいもの（cost_summary はここ）
_USER_DENY_PREFIXES = (
    "cost_summary_",
)


def is_user_downloadable(filename: str) -> bool:
    """
    ユーザーに見せて良い成果物だけ True。
    Windowsは大小文字が区別されないので lower() で判定する。
    """
    if not filename:
        return False

    name = filename.lower()

    # deny: prefix
    if any(name.startswith(p.lower()) for p in _USER_DENY_PREFIXES):
        return False

    # deny: exact names
    if name in {x.lower() for x in _USER_DENY_NAMES}:
        return False

    # allow: exact names
    if name in {x.lower() for x in _USER_ALLOW_NAMES}:
        return True

    # allow: prefixes (json/docx only)
    if any(name.startswith(p.lower()) for p in _USER_ALLOW_PREFIXES):
        return name.endswith(".json") or name.endswith(".docx")

    # allow: suffixes
    if any(name.endswith(s.lower()) for s in _USER_ALLOW_SUFFIXES):
        return True

    return False


def list_artifacts(jdir: Path) -> List[dict]:
    """
    UI向けに公開する成果物のみ返す（ユーザーに見せてよいものだけ）。
    ※ logs.txt や cost_summary_* はここで確実に除外される。
    """
    out: List[dict] = []
    for p in sorted(jdir.glob("*")):
        if p.is_dir():
            continue

        name = p.name
        if not is_user_downloadable(name):
            continue

        size = p.stat().st_size
        digest = sha256_file(p)
        out.append(
            {
                "name": name,
                "bytes": size,
                "sha256": digest,
                "download_url": f"/jobs/{jdir.name}/download/{name}",
            }
        )
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