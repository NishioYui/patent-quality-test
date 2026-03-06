from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple, Any
import os
import json
import hashlib
import time

from app.storage import ROOT, atomic_write_json, read_json, ensure_dir


INDEX_PATH = ROOT / "runs" / "_prompt_version_index.json"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


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


def _files_for_step(step: str) -> List[Path]:
    """
    「この step の prompt_version」を名乗るなら、このファイル群が同一であるべき、という対象。
    """
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


def compute_prompt_fingerprints(step: str) -> Dict[str, str]:
    fps: Dict[str, str] = {}
    for p in _files_for_step(step):
        key = _rel(p)
        if p.exists():
            fps[key] = _sha256_file(p)
        else:
            # 欠けている場合も検知できるように
            fps[key] = "MISSING"
    return fps


def _load_index() -> Dict[str, Any]:
    if INDEX_PATH.exists():
        try:
            return read_json(INDEX_PATH)
        except Exception:
            return {}
    return {}


def _save_index(idx: Dict[str, Any]) -> None:
    ensure_dir(INDEX_PATH.parent)
    atomic_write_json(INDEX_PATH, idx)


def check_prompt_version_mismatch(step: str, prompt_version: str) -> Dict[str, Any]:
    """
    返り値は status.json にそのまま入れられる形。
    - 初回: baseline_created=True
    - 同versionで内容が変化: mismatch=True (＝版番号上げ忘れ検知)
    """
    fps = compute_prompt_fingerprints(step)
    idx = _load_index()

    key = f"{step}:{prompt_version}"

    # 初回は baseline を保存して mismatch なし
    if key not in idx:
        idx[key] = {
            "created_at": _now_iso(),
            "fingerprints": fps,
        }
        _save_index(idx)
        return {
            "step": step,
            "prompt_version": prompt_version,
            "baseline_created": True,
            "mismatch": False,
            "changed_files": [],
            "fingerprints": fps,
            "index_path": _rel(INDEX_PATH),
        }

    base = idx.get(key, {}).get("fingerprints", {}) or {}
    changed = [k for k, v in fps.items() if base.get(k) != v]

    if changed:
        # デフォルトでは baseline を更新しない（＝忘れたままだと毎回警告が出続ける）
        allow_update = os.getenv("ACCEPT_PROMPT_FINGERPRINT", "0") == "1"
        if allow_update:
            idx[key]["fingerprints"] = fps
            idx[key]["updated_at"] = _now_iso()
            _save_index(idx)
            return {
                "step": step,
                "prompt_version": prompt_version,
                "baseline_created": False,
                "mismatch": False,
                "changed_files": changed,
                "fingerprints": fps,
                "index_path": _rel(INDEX_PATH),
                "note": "baseline updated because ACCEPT_PROMPT_FINGERPRINT=1",
            }

        return {
            "step": step,
            "prompt_version": prompt_version,
            "baseline_created": False,
            "mismatch": True,
            "changed_files": changed,
            "fingerprints": fps,
            "index_path": _rel(INDEX_PATH),
            "action": "prompt_version を上げる（例: v0.1→v0.2）か、検証後に ACCEPT_PROMPT_FINGERPRINT=1 で baseline を更新してください",
        }

    return {
        "step": step,
        "prompt_version": prompt_version,
        "baseline_created": False,
        "mismatch": False,
        "changed_files": [],
        "fingerprints": fps,
        "index_path": _rel(INDEX_PATH),
    }