"""FastAPI surface for the ChronoSense Temporal RAG pipeline.

Run (from project root, venv active):
    uvicorn temporal_rag.app:app --reload --port 8001

Endpoints
---------
GET  /health                         — liveness + collection status.
POST /drift-event                    — full pipeline (trajectory → retrieve → agents).
POST /trajectory                     — trajectory summary only (no retrieval/LLM).
POST /retrieve                       — retrieve top-k chunks for an arbitrary query.
"""

from __future__ import annotations

from datetime import datetime

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from backend.app.database import close_mongo_connection, connect_to_mongo

from . import config, pipeline, retrieval


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    yield
    await close_mongo_connection()

app = FastAPI(
    title="ChronoSense Temporal RAG",
    lifespan=lifespan,
    description="7-day drift trajectory → Ayushman Bharat guideline retrieval → multi-agent assessment.",
    version="1.0.0",
)


class DriftEvent(BaseModel):
    patient_id: str
    end: datetime | None = Field(
        default=None, description="End of the 7-day window (UTC). Defaults to now."
    )
    k: int = config.TOP_K
    run_agents: bool = True


class RetrieveRequest(BaseModel):
    query: str
    k: int = config.TOP_K


@app.get("/health")
def health() -> dict:
    info = {"status": "ok", "collection": config.COLLECTION_NAME}
    try:
        info["chunks_indexed"] = retrieval.get_collection().count()
    except Exception as exc:
        info["status"] = "degraded"
        info["collection_error"] = str(exc)
    return info


@app.post("/drift-event")
async def drift_event(evt: DriftEvent) -> dict:
    try:
        return await pipeline.run(
            evt.patient_id, end=evt.end, k=evt.k, run_agents=evt.run_agents
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:  # e.g. missing GROQ_API_KEY
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/trajectory")
async def trajectory_only(evt: DriftEvent) -> dict:
    try:
        analysis, n = await pipeline.build_trajectory(evt.patient_id, end=evt.end)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    from dataclasses import asdict

    return {"records_analyzed": n, "trajectory": asdict(analysis), "summary": analysis.summary}


@app.post("/retrieve")
async def retrieve(req: RetrieveRequest) -> dict:
    try:
        return {"query": req.query, "chunks": retrieval.retrieve(req.query, k=req.k)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))
