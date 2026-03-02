# cost_utils.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Tuple
import os

# USD per 1M tokens（OpenAI公式モデルページの表に合わせる）
# gpt-5.2: input $1.75 / output $14.00 など :contentReference[oaicite:2]{index=2}
MODEL_PRICES_USD_PER_1M: Dict[str, Tuple[float, float]] = {
    "gpt-5.2": (1.75, 14.00),      # :contentReference[oaicite:3]{index=3}
    "gpt-5": (1.25, 10.00),        # :contentReference[oaicite:4]{index=4}
    "gpt-5.1": (1.25, 10.00),      # 5系は同水準（モデルページ表記に合わせて使う）
    "gpt-5-mini": (0.25, 2.00),    # :contentReference[oaicite:5]{index=5}
    "gpt-5-nano": (0.05, 0.40),    # :contentReference[oaicite:6]{index=6}
    "gpt-4o": (2.50, 10.00),       # :contentReference[oaicite:7]{index=7}
    "gpt-4o-mini": (0.15, 0.60),   # :contentReference[oaicite:8]{index=8}
    "gpt-4.1-mini": (0.40, 1.60),  # :contentReference[oaicite:9]{index=9}
    "o3-mini": (1.10, 4.40),       # :contentReference[oaicite:10]{index=10}
}

@dataclass
class PriceInfo:
    model_key: str
    input_per_1m: float
    output_per_1m: float
    source: str

def _normalize_model_key(model: str) -> Optional[str]:
    m = (model or "").strip()
    if not m:
        return None
    # スナップショット（例: gpt-5-mini-2025-08-07）でも先頭一致で拾う
    for key in MODEL_PRICES_USD_PER_1M.keys():
        if m == key or m.startswith(key + "-"):
            return key
    return None

def get_price_info(model: str) -> Optional[PriceInfo]:
    key = _normalize_model_key(model)
    if key:
        ip, op = MODEL_PRICES_USD_PER_1M[key]
        return PriceInfo(key, ip, op, "MODEL_PAGE_PER_1M_TOKENS")
    # 未知モデルは環境変数で上書きできるようにする（事故防止）
    # 例: set "PRICE_IN_PER_1M=1.75" / set "PRICE_OUT_PER_1M=14.0"
    env_in = os.getenv("PRICE_IN_PER_1M", "").strip()
    env_out = os.getenv("PRICE_OUT_PER_1M", "").strip()
    if env_in and env_out:
        return PriceInfo("ENV_OVERRIDE", float(env_in), float(env_out), "ENV_OVERRIDE")
    return None

def estimate_cost_usd(input_tokens: int, output_tokens: int, price: PriceInfo) -> float:
    return (input_tokens / 1_000_000.0) * price.input_per_1m + (output_tokens / 1_000_000.0) * price.output_per_1m