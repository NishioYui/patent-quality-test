import os, glob, json, base64, sys, time, uuid
from datetime import datetime
from openai import OpenAI
from cost_utils import get_price_info, estimate_cost_usd
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT / ".env")


MODEL = os.getenv("MODEL", "gpt-5.2")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))

# run_case_all から渡す想定（無ければ既定）
RUN_DIR = os.getenv("RUN_DIR", "runs").strip() or "runs"
os.makedirs(RUN_DIR, exist_ok=True)

# run_case_all から渡す想定（無ければ生成）
RUN_ID = os.getenv("RUN_ID", "").strip() or str(uuid.uuid4())

# costファイル命名のため（run_case_allがCASE_FILEを渡す）
CASE_FILE = os.getenv("CASE_FILE", "").strip()
CASE_BASE = os.path.basename(CASE_FILE) if CASE_FILE else "case_unknown.txt"

IMG_DIR = os.getenv("IMG_DIR", fr"{RUN_DIR}\images_drawings")

# 読ませたいページを絞る（例: "3,4,5" / 未指定ならIMG_DIR内の全png）
PAGES = os.getenv("DRAWING_PAGES", "").strip()

def data_url_from_png(path: str) -> str:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"

def pick_images():
    if PAGES:
        nums = []
        for x in PAGES.split(","):
            x = x.strip()
            if x.isdigit():
                nums.append(int(x))
        paths = [os.path.join(IMG_DIR, f"page_{n:03d}.png") for n in nums]
        return [p for p in paths if os.path.exists(p)]

    paths = glob.glob(os.path.join(IMG_DIR, "page_*.png"))
    paths.sort()
    return paths

def _extract_usage_tokens(r) -> tuple[int, int]:
    u = getattr(r, "usage", None)
    if u is not None:
        it = getattr(u, "input_tokens", None)
        ot = getattr(u, "output_tokens", None)
        if it is not None and ot is not None:
            return int(it), int(ot)
    d = r.model_dump() if hasattr(r, "model_dump") else {}
    u2 = d.get("usage", {}) if isinstance(d, dict) else {}
    return int(u2.get("input_tokens", 0)), int(u2.get("output_tokens", 0))

def main():
    images = pick_images()
    if not images:
        raise SystemExit(f"No images found. IMG_DIR={IMG_DIR} DRAWING_PAGES={PAGES}")

    client = OpenAI()

    schema = {
        "name": "drawing_extract_v0_1",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["figures", "reference_signs", "warnings"],
            "properties": {
                "figures": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["label", "description", "confidence"],
                        "properties": {
                            "label": {"type": "string"},
                            "description": {"type": "string"},
                            "confidence": {"type": "number"}
                        }
                    }
                },
                "reference_signs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["sign", "name", "confidence"],
                        "properties": {
                            "sign": {"type": "string"},
                            "name": {"type": "string"},
                            "confidence": {"type": "number"}
                        }
                    }
                },
                "warnings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["code", "message"],
                        "properties": {
                            "code": {"type": "string"},
                            "message": {"type": "string"}
                        }
                    }
                }
            }
        }
    }

    system = (
        "あなたは特許図面の読取補助です。図面画像から次を抽出してJSONで返してください。\n"
        "1) figures: 図番号（図１など）と簡単な説明（ブロック図/フロー図等）。\n"
        "2) reference_signs: 図中の符号（10, 11など）と名称（端末装置、制御部等）。\n"
        "不確実なら confidence を低くし、warnings に理由を書く。捏造禁止。\n"
        "図番号が読み取れない場合は label を '図１' のように推測で付けない。空にするか warnings。\n"
    )

    content = [{"type": "input_text", "text": "以下の図面画像を解析してください。"}]
    for p in images:
        content.append({
            "type": "input_image",
            "image_url": data_url_from_png(p),
            "detail": "high"
        })

    resp = client.responses.create(
        model=MODEL,
        temperature=TEMPERATURE,
        input=[
            {"role": "system", "content": [{"type": "input_text", "text": system}]},
            {"role": "user", "content": content},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": schema["name"],
                "strict": schema["strict"],
                "schema": schema["schema"],
            }
        },
    )

    # ---- usage / cost 保存（drawings）----
    usage_in, usage_out = _extract_usage_tokens(resp)

    usage_path = os.path.join(RUN_DIR, f"usage_drawings_{CASE_BASE}_{RUN_ID}.json")
    with open(usage_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "step": "drawings",
                "model": MODEL,
                "temperature": TEMPERATURE,
                "run_id": RUN_ID,
                "case_file": CASE_FILE,
                "input_tokens": usage_in,
                "output_tokens": usage_out,
                "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
            f, ensure_ascii=False, indent=2
        )

    price = get_price_info(MODEL)
    cost_obj = {"step": "drawings", "model": MODEL, "run_id": RUN_ID, "input_tokens": usage_in, "output_tokens": usage_out}
    if price:
        cost_usd = estimate_cost_usd(usage_in, usage_out, price)
        cost_obj.update({
            "cost_usd": cost_usd,
            "price_input_per_1m": price.input_per_1m,
            "price_output_per_1m": price.output_per_1m,
            "price_model_key": price.model_key,
            "price_source": price.source,
        })
    else:
        cost_obj.update({"cost_usd": None, "note": "Unknown model price. Set PRICE_IN_PER_1M and PRICE_OUT_PER_1M."})

    cost_path = os.path.join(RUN_DIR, f"cost_drawings_{CASE_BASE}_{RUN_ID}.json")
    with open(cost_path, "w", encoding="utf-8") as f:
        json.dump(cost_obj, f, ensure_ascii=False, indent=2)

    # stdoutは汚さない（run_case_allがstdoutを見ても安全）
    print(f"[cost] drawings cost_usd={cost_obj.get('cost_usd')} saved={cost_path}", file=sys.stderr)

    # ---- drawings_extract 出力 ----
    data = json.loads(resp.output_text)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {
        "metadata": {
            "model": MODEL,
            "temperature": TEMPERATURE,
            "prompt_version": "drawings_v0.1",
            "run_id": RUN_ID,
            "language": "ja",
            "usage_input_tokens": usage_in,
            "usage_output_tokens": usage_out,
            "usage_file": os.path.basename(usage_path),
            "cost_usd": cost_obj.get("cost_usd"),
            "cost_file": os.path.basename(cost_path),
        },
        "source": {"img_dir": IMG_DIR, "pages": PAGES or "ALL"},
        **data
    }

    out_path = os.path.join(RUN_DIR, f"drawings_extract_{ts}_{RUN_ID}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(out_path)

if __name__ == "__main__":
    main()