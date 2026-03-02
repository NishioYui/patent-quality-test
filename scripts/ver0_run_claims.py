import os, json, uuid
from openai import OpenAI

client = OpenAI()

MODEL = os.getenv("MODEL", "gpt-5.2")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))

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

run_id = str(uuid.uuid4())

user_prompt = (usr_t
    .replace("{{INVENTION_TEXT}}", invention_text)
    .replace("{{DRAWINGS_JSON}}", drawings_json)
)

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

data = json.loads(resp.output_text)

data.setdefault("metadata", {})
data["metadata"]["model"] = MODEL
data["metadata"]["temperature"] = TEMPERATURE
data["metadata"]["prompt_version"] = "claims_v0.1"
data["metadata"]["run_id"] = run_id
data["metadata"]["language"] = "ja"

os.makedirs("runs", exist_ok=True)
out_path = f"runs/claims_{os.path.basename(case_file)}_{run_id}.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(out_path)
