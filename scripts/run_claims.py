import os, json, uuid
import sys, time
from openai import OpenAI
from cost_utils import get_price_info, estimate_cost_usd

client = OpenAI()

MODEL = os.getenv("MODEL", "gpt-5.2")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))

# RUN_ID / RUN_DIR は run_case_all から渡せるようにする（無ければ生成）
run_id = os.getenv("RUN_ID", "").strip() or str(uuid.uuid4())
RUN_DIR = os.getenv("RUN_DIR", "runs").strip() or "runs"
os.makedirs(RUN_DIR, exist_ok=True)

schema = json.load(open("schemas/claims_only.schema.json", "r", encoding="utf-8"))
sys_p = open("prompts/claims_system.txt", "r", encoding="utf-8").read()
usr_t = open("prompts/claims_user.txt", "r", encoding="utf-8").read()

case_file = os.getenv("CASE_FILE", "").strip()
if not case_file:
    raise SystemExit('CASE_FILE が未設定です。例: set "CASE_FILE=cases\\case_A_normal.txt"')

invention_text = open(case_file, "r", encoding="utf-8").read()

# ★図面が無いときでも「空のJSON」を必ず渡す（空文字はNG）
EMPTY_DRAWINGS = json.dumps(
    {"figures": [], "reference_signs": [], "warnings": []},
    ensure_ascii=False
)

drawings_path = os.getenv("DRAWINGS_JSON_PATH", "").strip()
if drawings_path:
    if not os.path.exists(drawings_path):
        raise SystemExit(f'DRAWINGS_JSON_PATH が見つかりません: {drawings_path}')
    drawings_json = open(drawings_path, "r", encoding="utf-8").read()
else:
    drawings_json = EMPTY_DRAWINGS

user_prompt = (usr_t
    .replace("{{INVENTION_TEXT}}", invention_text)
    .replace("{{DRAWINGS_JSON}}", drawings_json)
)

# ===== Token counting（事前に入力トークンだけ計測） =====
COUNT_INPUT_TOKENS = os.getenv("COUNT_INPUT_TOKENS", "0") == "1"
COUNT_TOKENS_ONLY  = os.getenv("COUNT_TOKENS_ONLY", "0") == "1"

input_tokens_counted = None
token_file_path = None

if COUNT_INPUT_TOKENS or COUNT_TOKENS_ONLY:
    tc = client.responses.input_tokens.count(
        model=MODEL,
        input=[
            {"role": "system", "content": sys_p},
            {"role": "user", "content": user_prompt},
        ],
        # create() と同じ text format を渡す（schema含めて正確に数える）
        text={
            "format": {
                "type": "json_schema",
                "name": "claims_only",
                "strict": True,
                "schema": schema
            }
        },
    )
    input_tokens_counted = int(tc.input_tokens)

    token_file_path = os.path.join(
        RUN_DIR,
        f"token_input_claims_{os.path.basename(case_file)}_{run_id}.json"
    )
    with open(token_file_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "step": "claims",
                "input_tokens": input_tokens_counted,
                "model": MODEL,
                "temperature": TEMPERATURE,
                "run_id": run_id,
                "case_file": case_file,
                "drawings_path": drawings_path,
                "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
            f,
            ensure_ascii=False,
            indent=2
        )

    # stdout を汚さない
    print(f"[token_count] claims input_tokens={input_tokens_counted} saved={token_file_path}", file=sys.stderr)

    # 計測だけして終了したい時（※ run_case_all では使わない）
    if COUNT_TOKENS_ONLY:
        print(json.dumps({"step": "claims", "input_tokens": input_tokens_counted, "token_file": token_file_path}, ensure_ascii=False))
        raise SystemExit(0)
# ==========================================================

resp = client.responses.create(
    model=MODEL,
    temperature=TEMPERATURE,
    input=[
        {"role": "system", "content": sys_p},
        {"role": "user", "content": user_prompt},
    ],
    text={
        "format": {
            "type": "json_schema",
            "name": "claims_only",
            "strict": True,
            "schema": schema
        }
    }
)

# --- Extract usage tokens (input/output) ---
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

usage_in, usage_out = _extract_usage_tokens(resp)

# --- Save usage ---
usage_path = os.path.join(RUN_DIR, f"usage_claims_{os.path.basename(case_file)}_{run_id}.json")
with open(usage_path, "w", encoding="utf-8") as f:
    json.dump(
        {
            "step": "claims",
            "model": MODEL,
            "temperature": TEMPERATURE,
            "run_id": run_id,
            "case_file": case_file,
            "input_tokens": usage_in,
            "output_tokens": usage_out,
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        },
        f, ensure_ascii=False, indent=2
    )

# --- Cost (USD) ---
price = get_price_info(MODEL)
cost_obj = {
    "step": "claims",
    "model": MODEL,
    "run_id": run_id,
    "input_tokens": usage_in,
    "output_tokens": usage_out,
}

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
    cost_obj.update({
        "cost_usd": None,
        "note": "Unknown model price. Set PRICE_IN_PER_1M and PRICE_OUT_PER_1M.",
    })

cost_path = os.path.join(RUN_DIR, f"cost_claims_{os.path.basename(case_file)}_{run_id}.json")
with open(cost_path, "w", encoding="utf-8") as f:
    json.dump(cost_obj, f, ensure_ascii=False, indent=2)

# --- Parse output JSON ---
data = json.loads(resp.output_text)

# --- Metadata ---
data.setdefault("metadata", {})
data["metadata"]["model"] = MODEL
data["metadata"]["temperature"] = TEMPERATURE
data["metadata"]["prompt_version"] = "claims_v0.1"
data["metadata"]["run_id"] = run_id
data["metadata"]["language"] = "ja"

# 計測値（あれば）
if input_tokens_counted is not None:
    data["metadata"]["input_tokens_counted"] = input_tokens_counted
    data["metadata"]["token_count_file"] = os.path.basename(token_file_path) if token_file_path else None

# usage / cost（実績）
data["metadata"]["usage_input_tokens"] = usage_in
data["metadata"]["usage_output_tokens"] = usage_out
data["metadata"]["usage_file"] = os.path.basename(usage_path)
data["metadata"]["cost_usd"] = cost_obj["cost_usd"]
data["metadata"]["cost_file"] = os.path.basename(cost_path)

# --- Save ---
out_path = os.path.join(RUN_DIR, f"claims_{os.path.basename(case_file)}_{run_id}.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(out_path)