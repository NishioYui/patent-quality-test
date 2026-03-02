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
        drawing_notes = "\n".join(lines).strip()

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
    return "\n".join(parts).rstrip() + "\n"
