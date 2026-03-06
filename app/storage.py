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
    """
    UI向けに公開する成果物のみ返す（規約固定）。
    - 固定名: claims.json / spec.json / logs.txt
    - 任意: cost_summary_*.json, drawings_extract_*.json, *.docx
    """
    allow_names = {"claims.json", "spec.json", "logs.txt"}
    allow_prefixes = {"drawings_extract_"}
    allow_suffixes = {".docx"}

    out: List[dict] = []
    for p in sorted(jdir.glob("*")):
        if p.is_dir():
            continue
        name = p.name

        ok = False
        if name in allow_names:
            ok = True
        elif any(name.startswith(pref) for pref in allow_prefixes):
            ok = True
        elif p.suffix.lower() in allow_suffixes:
            ok = True

        if not ok:
            continue

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
