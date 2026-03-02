import os, json, uuid
from openai import OpenAI

client = OpenAI()

MODEL = os.getenv("MODEL", "gpt-5.2")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))

# --- Load schema & prompts ---
schema = json.load(open("schemas/spec_only.schema.json", "r", encoding="utf-8"))
sys_p = open("prompts/spec_system.txt", "r", encoding="utf-8").read()
usr_t = open("prompts/spec_user.txt", "r", encoding="utf-8").read()

# --- Inputs ---
case_file = os.getenv("CASE_FILE", "").strip()
if not case_file:
    raise SystemExit('CASE_FILE が未設定です。例: set "CASE_FILE=cases\\case_A_normal.txt"')

invention_text = open(case_file, "r", encoding="utf-8").read()

claims_path = os.getenv("CLAIMS_JSON_PATH", "").strip()
if not claims_path:
    raise SystemExit('CLAIMS_JSON_PATH が未設定です。例: set "CLAIMS_JSON_PATH=runs\\claims_....json"')
claims_json = open(claims_path, "r", encoding="utf-8").read()

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

# --- Build prompt ---
run_id = str(uuid.uuid4())

user_prompt = (usr_t
    .replace("{{INVENTION_TEXT}}", invention_text)
    .replace("{{CLAIMS_JSON}}", claims_json)
)

# spec_user.txt に {{DRAWINGS_JSON}} がある場合だけ埋める（無ければ末尾に追記）
if "{{DRAWINGS_JSON}}" in user_prompt:
    user_prompt = user_prompt.replace("{{DRAWINGS_JSON}}", drawings_json)
else:
    # 後方互換：drawings_json を明示して渡す（空でもJSONとして渡す）
    user_prompt += "\n\n【drawings_json（図面解析結果。無ければ空のJSON）】\n" + drawings_json

# --- Call model ---
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
            "name": "spec_only",
            "strict": True,
            "schema": schema
        }
    }
)

data = json.loads(resp.output_text)

# --- Metadata ---
data.setdefault("metadata", {})
data["metadata"]["model"] = MODEL
data["metadata"]["temperature"] = TEMPERATURE
data["metadata"]["prompt_version"] = "spec_v0.1"
data["metadata"]["run_id"] = run_id
data["metadata"]["language"] = "ja"

# --- Save ---
os.makedirs("runs", exist_ok=True)
out_path = f"runs/spec_{os.path.basename(case_file)}_{run_id}.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(out_path)
