from __future__ import annotations

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import uuid
import os
import hashlib
import time

from app.invention_text import build_invention_text
from app.storage import job_dir, ensure_dir, atomic_write_json, read_json, list_artifacts
from app.job_runner import start_job
from app.severity import attach_severity
from pathlib import Path
from dotenv import load_dotenv

# プロジェクトルートの .env を読む（無ければ何もしない）
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT / ".env")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


app = FastAPI(title="PatentDraft API", version="0.1")

# CORS（Next devの想定）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/jobs")
async def create_job(
    form_json: str = Form(...),
    drawing_pdf: UploadFile | None = File(None),
):
    # form_json parse
    try:
        payload = json.loads(form_json)
        if not isinstance(payload, dict):
            raise ValueError("form_json must be an object")
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"Invalid form_json: {repr(ex)}")

    job_id = uuid.uuid4().hex
    jdir = job_dir(job_id)
    ensure_dir(jdir)

    # input.txt 作成（従来互換のCASE_FILE）
    invention_text = build_invention_text(payload)
    (jdir / "input.txt").write_text(invention_text, encoding="utf-8")

    # input_hash
    h = hashlib.sha256(invention_text.encode("utf-8")).hexdigest()
    atomic_write_json(jdir / "input_meta.json", {"sha256": h})

    # 保存：request.json（監査/再現性）※1回で書く
    req_obj = {
        "job_id": job_id,
        "created_at": _now_iso(),
        "payload": payload,
        "has_pdf": bool(drawing_pdf),
        "model": os.getenv("MODEL", "gpt-5.2"),
        "temperature": float(os.getenv("TEMPERATURE", "0.2")),
        "run_id": job_id,
        "run_dir": f"runs/{job_id}",
        "input_template_version": "invention_text_v0.1",
        "input_sha256": h,
    }
    atomic_write_json(jdir / "request.json", req_obj)

    # PDF保存（任意）
    if drawing_pdf is not None:
        if drawing_pdf.content_type not in (None, "", "application/pdf"):
            raise HTTPException(status_code=400, detail="drawing_pdf must be application/pdf")
        pdf_path = jdir / "drawings.pdf"
        content = await drawing_pdf.read()
        pdf_path.write_bytes(content)

    # status.json 初期
    atomic_write_json(jdir / "status.json", {
        "job_id": job_id,
        "status": "queued",
        "created_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "warnings": [],
        "is_blocked": False,
        "artifacts": [],
        "error": None,
        "run_id": job_id,
        "input_sha256": h,
    })

    # 実行env（run_case_allへ）
    # RUN_DIR を job_dir にする（出力がこのジョブ配下に集約される）
    run_dir_rel = f"runs/{job_id}"
    env = os.environ.copy()
    env["OPEN_NOTEPAD"] = "0"
    env["RUN_ID"] = job_id
    env["RUN_DIR"] = run_dir_rel

    # 必須：CASE_FILE
    env["CASE_FILE"] = run_dir_rel + "/input.txt"

    # 図面PDFがある場合だけPDF_FILEを指定。無ければ明示的に空文字。
    pdf_rel = run_dir_rel + "/drawings.pdf"
    if (jdir / "drawings.pdf").exists():
        env["PDF_FILE"] = pdf_rel
        env["IMG_DIR"] = run_dir_rel + "/images_drawings"
    else:
        env["PDF_FILE"] = ""  # 明示スキップ（run_case_all側で未指定扱いにしないこと）

    # start
    start_job(job_id, env)

    return {
        "job_id": job_id,
        "status": "queued",
        "urls": {"status": f"/jobs/{job_id}"},
    }


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    """
    1) runs/<id>/status.json を読み取り
    2) (保険) artifacts が空なら runs/<id>/ 配下から生成
    3) (保険) warnings が空なら claims/spec から抽出し severity 付与
    4) UIがそのまま描画できるJSONを返す
    """
    jdir = job_dir(job_id)
    st_path = jdir / "status.json"
    if not st_path.exists():
        raise HTTPException(status_code=404, detail="job not found")

    st = read_json(st_path)

    # ---- 保険1：artifacts が空なら再計算して返す ----
    if not st.get("artifacts"):
        try:
            st["artifacts"] = list_artifacts(jdir)
        except Exception:
            pass

    # ---- 保険2：warnings が空なら claims/spec から抽出してseverity付け ----
    if not st.get("warnings"):
        warnings_raw = []
        for fname in ("claims.json", "spec.json"):
            fp = jdir / fname
            if fp.exists():
                try:
                    obj = json.loads(fp.read_text(encoding="utf-8"))
                    ws = obj.get("warnings", [])
                    if isinstance(ws, list):
                        warnings_raw += ws
                except Exception:
                    pass
        try:
            warnings_with_sev, blocked = attach_severity(warnings_raw)
            st["warnings"] = warnings_with_sev
            st["is_blocked"] = bool(blocked)
        except Exception:
            pass

    return st


@app.get("/jobs/{job_id}/download/{filename}")
def download(job_id: str, filename: str):
    jdir = job_dir(job_id)
    if not jdir.exists():
        raise HTTPException(status_code=404, detail="job not found")

    # path traversal防止：ルート直下のファイルだけ許可
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="invalid filename")

    fpath = jdir / filename
    if not fpath.exists() or not fpath.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    return FileResponse(path=str(fpath), filename=filename)