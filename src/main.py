"""FastAPI Service for Frontier Hackathon 2026 - Reto 1: Kipu Pay Data Anonymization.

Implements all endpoints defined in participante.openapi.yaml:
- GET /health
- POST /run
- GET /run/{job_id}
- GET /output/{archivo}
- POST /anonymize
- GET /entities
Both under root and under /v1 prefix.
"""

import datetime
import json
import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from src.config import (
    DB_PATH,
    DEFAULT_MODEL,
    FUENTES_TOKEN,
    FUENTES_URL,
    OUTPUT_DIR,
    SAMPLE_DIR,
)
from src.pipeline import EntityManager, anonymize_live_batch, run_pipeline

logger = logging.getLogger("api")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Kipu Pay Fintech Data Anonymization API",
    version="1.0.0",
    description="Privacy-preserving PII anonymization engine adhering strictly to Frontier Hackathon 2026 contract.",
)

# Enable CORS for external judge and Frontier dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_OUTPUT_FILES = {
    "chats.jsonl": "application/x-ndjson",
    "docs.jsonl": "application/x-ndjson",
    "tables.jsonl": "application/x-ndjson",
    "entities.json": "application/json",
}


# -----------------------------------------------------------------------------
# Pydantic Schemas
# -----------------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    team: str = "Kipu-Anonymizers"
    version: str = "1.0.0"
    models: List[str] = Field(default_factory=lambda: [DEFAULT_MODEL])


class RunRequest(BaseModel):
    sources_url: str = Field(..., example="https://reto-pii-fuentes-production.up.railway.app/v1")
    token: str = Field(..., description="Token de equipo para el API de fuentes")


class RunAcceptedResponse(BaseModel):
    job_id: str


class CostRecord(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0


class RecordsCount(BaseModel):
    chats: int = 0
    docs: int = 0
    tables: int = 0


class JobStatusResponse(BaseModel):
    status: Literal["queued", "running", "done", "failed"]
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    records: Optional[RecordsCount] = None
    cost: Optional[CostRecord] = None
    error: Optional[str] = None


class AnonymizeRequest(BaseModel):
    source: Literal["chats", "docs", "tables"]
    records: List[Dict[str, Any]] = Field(..., max_length=50)


class AnonymizeResponse(BaseModel):
    records: List[Dict[str, Any]]
    entities: List[Dict[str, Any]]


# -----------------------------------------------------------------------------
# Job Database Helpers
# -----------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def create_job(job_id: str):
    conn = get_db()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with conn:
        conn.execute(
            """
            INSERT INTO jobs (job_id, status, started_at)
            VALUES (?, 'queued', ?)
            """,
            (job_id, now_iso),
        )


def update_job_running(job_id: str):
    conn = get_db()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with conn:
        conn.execute(
            "UPDATE jobs SET status = 'running', started_at = ? WHERE job_id = ?",
            (now_iso, job_id),
        )


def update_job_done(job_id: str, counts: Dict[str, int], seconds: float):
    conn = get_db()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with conn:
        conn.execute(
            """
            UPDATE jobs SET
                status = 'done',
                finished_at = ?,
                chats_count = ?,
                docs_count = ?,
                tables_count = ?,
                seconds = ?
            WHERE job_id = ?
            """,
            (
                now_iso,
                counts.get("chats", 0),
                counts.get("docs", 0),
                counts.get("tables", 0),
                round(seconds, 2),
                job_id,
            ),
        )


def update_job_failed(job_id: str, error_msg: str, seconds: float):
    conn = get_db()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with conn:
        conn.execute(
            """
            UPDATE jobs SET
                status = 'failed',
                finished_at = ?,
                error = ?,
                seconds = ?
            WHERE job_id = ?
            """,
            (now_iso, str(error_msg), round(seconds, 2), job_id),
        )


def background_run_pipeline(job_id: str, sources_url: str, token: str):
    """Executes the pipeline as a background task, updating the SQLite job status."""
    logger.info(f"Starting pipeline execution for job {job_id}")
    t0 = time.time()
    update_job_running(job_id)

    try:
        counts = run_pipeline(
            sources_url=sources_url,
            token=token,
            output_dir=OUTPUT_DIR,
        )
        elapsed = time.time() - t0
        update_job_done(job_id, counts, elapsed)
        logger.info(f"Job {job_id} completed successfully in {elapsed:.2f}s")
    except Exception as exc:
        elapsed = time.time() - t0
        logger.exception(f"Job {job_id} failed: {exc}")
        update_job_failed(job_id, str(exc), elapsed)


# -----------------------------------------------------------------------------
# Endpoints (Mapped at both root and /v1 for complete compatibility)
# -----------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
@app.get("/v1/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        team="Kipu-Anonymizers",
        version="1.0.0",
        models=[DEFAULT_MODEL],
    )


@app.post("/run", status_code=status.HTTP_202_ACCEPTED, response_model=RunAcceptedResponse)
@app.post("/v1/run", status_code=status.HTTP_202_ACCEPTED, response_model=RunAcceptedResponse)
def trigger_run(payload: RunRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    create_job(job_id)
    background_tasks.add_task(
        background_run_pipeline,
        job_id,
        payload.sources_url,
        payload.token,
    )
    return RunAcceptedResponse(job_id=job_id)


@app.get("/run/{job_id}", response_model=JobStatusResponse)
@app.get("/v1/run/{job_id}", response_model=JobStatusResponse)
def get_run_status(job_id: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job no encontrado")

    return JobStatusResponse(
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        records=RecordsCount(
            chats=row["chats_count"],
            docs=row["docs_count"],
            tables=row["tables_count"],
        ),
        cost=CostRecord(
            tokens_in=row["tokens_in"],
            tokens_out=row["tokens_out"],
            seconds=row["seconds"] or 0.0,
        ),
        error=row["error"],
    )


@app.get("/output/{archivo}")
@app.get("/v1/output/{archivo}")
def get_output_file(archivo: str):
    # Path traversal protection
    clean_name = os.path.basename(archivo)
    if clean_name not in ALLOWED_OUTPUT_FILES:
        raise HTTPException(
            status_code=404,
            detail=f"Archivo no permitido. Permitidos: {list(ALLOWED_OUTPUT_FILES.keys())}",
        )

    file_path = OUTPUT_DIR / clean_name
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"El archivo '{clean_name}' no existe aún en la salida terminada.",
        )

    media_type = ALLOWED_OUTPUT_FILES[clean_name]
    return FileResponse(path=str(file_path), media_type=media_type, filename=clean_name)


@app.post("/anonymize", response_model=AnonymizeResponse)
@app.post("/v1/anonymize", response_model=AnonymizeResponse)
def anonymize_live(payload: AnonymizeRequest):
    if len(payload.records) > 50:
        raise HTTPException(
            status_code=422,
            detail="El lote de registros supera el máximo permitido de 50 registros.",
        )
    try:
        anon_records, used_entities = anonymize_live_batch(
            source=payload.source,
            records=payload.records,
        )
        return AnonymizeResponse(records=anon_records, entities=used_entities)
    except Exception as exc:
        logger.exception(f"Error in /anonymize: {exc}")
        raise HTTPException(status_code=500, detail=f"Error al procesar lote: {exc}")


@app.get("/entities")
@app.get("/v1/entities")
def get_entities_dictionary():
    entities_path = OUTPUT_DIR / "entities.json"
    if entities_path.exists():
        try:
            with open(entities_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning(f"Error reading entities.json from disk: {exc}")

    em = EntityManager()
    return em.export_entities_json()


# -----------------------------------------------------------------------------
# Main entrypoint when run directly
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    logger.info(f"Starting Kipu Pay Anonymizer on {host}:{port}")
    uvicorn.run("src.main:app", host=host, port=port, reload=False)
