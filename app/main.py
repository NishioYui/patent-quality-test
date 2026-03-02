# app/main.py
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
from app.storage import job_dir, ensure_dir, atomic_write_json, read_json
from app.job_runner import start_job

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")

app = FastAPI(title="PatentDraft API", version="0.1")

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
    try:
        payload = json.loads(form_json)
        if not isinstance(payload, dict):
            raise ValueError("form_json must be an object")
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"Invalid form_json: {repr(ex)}")

    job_id = uuid.uuid4().hex
    jdir = job_dir(job_id)
    ensure_dir(jdir)

    req_obj = {
        "job_id": job_id,
        "created_at": _now_iso(),
        "payload": payload,
        "has_pdf": bool(drawing_pdf),
        "model": os.getenv("MODEL", "gpt-5.2"),
        "temperature": float(os.getenv("TEMPERATURE", "0.2")),
    }
    atomic_write_json(jdir / "request.json", req_obj)

    invention_text = build_invention_text(payload)
    (jdir / "input.txt").write_text(invention_text, encoding="utf-8")

    h = hashlib.sha256(invention_text.encode("utf-8")).hexdigest()
    atomic_write_json(jdir / "input_meta.json", {"sha256": h})

    if drawing_pdf is not None:
        if drawing_pdf.content_type not in (None, "", "application/pdf"):
            raise HTTPException(status_code=400, detail="drawing_pdf must be application/pdf")
        pdf_path = jdir / "drawings.pdf"
        content = await drawing_pdf.read()
        pdf_path.write_bytes(content)

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
    })

    run_dir_rel = f"runs/{job_id}"
    env = os.environ.copy()
    env["OPEN_NOTEPAD"] = "0"
    env["RUN_ID"] = job_id
    env["RUN_DIR"] = run_dir_rel
    env["CASE_FILE"] = run_dir_rel + "/input.txt"

    pdf_rel = run_dir_rel + "/drawings.pdf"
    if (jdir / "drawings.pdf").exists():
        env["PDF_FILE"] = pdf_rel
        env["IMG_DIR"] = run_dir_rel + "/images_drawings"
    else:
        env["PDF_FILE"] = ""

    start_job(job_id, env)

    return {"job_id": job_id, "status": "queued", "urls": {"status": f"/jobs/{job_id}"}}

@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    jdir = job_dir(job_id)
    st_path = jdir / "status.json"
    if not st_path.exists():
        raise HTTPException(status_code=404, detail="job not found")
    return read_json(st_path)

@app.get("/jobs/{job_id}/download/{filename}")
def download(job_id: str, filename: str):
    jdir = job_dir(job_id)
    if not jdir.exists():
        raise HTTPException(status_code=404, detail="job not found")

    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="invalid filename")

    fpath = jdir / filename
    if not fpath.exists() or not fpath.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    return FileResponse(path=str(fpath), filename=filename)
