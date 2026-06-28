"""FastAPI surface for the ChronoSense Temporal RAG pipeline.

Run (from project root, venv active):
    uvicorn temporal_rag.app:app --reload --port 8001

Endpoints
---------
GET  /health                 — liveness + collection status.
GET  /patients               — patient ids + demographics (dashboard dropdown).
POST /dashboard              — full bundle for the 5-panel clinician dashboard.
POST /drift-event            — full pipeline (trajectory → retrieve → agents).
POST /trajectory             — trajectory summary only (no retrieval/LLM).
POST /retrieve               — retrieve top-k chunks for an arbitrary query.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.app.database import (
    close_mongo_connection,
    connect_to_mongo,
    get_database,
)

from . import agents, config, db, pipeline, retrieval, trajectory


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

# The React dashboard runs on a separate dev-server origin (Vite, :5173), so
# allow cross-origin calls. Tighten allow_origins for a real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request models ───────────────────────────────────────────────────────────
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


# ── Core endpoints ───────────────────────────────────────────────────────────
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
    return {"records_analyzed": n, "trajectory": asdict(analysis), "summary": analysis.summary}


@app.post("/retrieve")
async def retrieve(req: RetrieveRequest) -> dict:
    try:
        return {"query": req.query, "chunks": retrieval.retrieve(req.query, k=req.k)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ── Dashboard surface (consumed by the React UI) ─────────────────────────────
@app.get("/patients")
async def list_patients() -> dict:
    """All patient ids (+ demographics) for the dashboard dropdown."""
    database = get_database()
    docs = (
        await database[config.PATIENTS_COLLECTION]
        .find({}, {"_id": 0})
        .sort("patient_id", 1)
        .to_list(length=None)
    )
    return {"patients": docs}


def _record_to_point(rec: dict, day: int) -> dict:
    """Shape one vitals record into a flat chart/panel point."""
    return {
        "day": day,
        "date": rec.get("timestamp"),
        "heart_rate": rec.get("heart_rate"),
        "respiratory_rate": rec.get("respiratory_rate"),
        "movement_score": rec.get("movement_score"),
        "drift_score": rec.get("drift_score"),
        "lower_ci": rec.get("drift_score_lower_ci"),
        "upper_ci": rec.get("drift_score_upper_ci"),
        "shap_hr": rec.get("shap_hr"),
        "shap_rr": rec.get("shap_rr"),
        "shap_movement": rec.get("shap_movement"),
    }


@app.post("/dashboard")
async def dashboard(evt: DriftEvent) -> dict:
    """One call returning everything the 5-panel dashboard needs: daily vitals
    series, drift trajectory + CI band, latest SHAP, retrieved guideline chunks,
    and (best-effort) the multi-agent assessment.

    The assessment is wrapped so a Groq failure (timeout, rate-limit, missing
    key) still returns panels 1-4 with assessment=null + an error string,
    instead of failing the whole request.
    """
    records = await db.fetch_last_7_days(evt.patient_id, end=evt.end)
    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"No vitals for patient '{evt.patient_id}' in the last "
                   f"{config.TRAJECTORY_DAYS} days.",
        )

    demographics = await db.fetch_demographics(evt.patient_id)
    demographics.pop("_id", None)  # ObjectId is not JSON-serializable
    analysis = trajectory.analyze(records, demographics=demographics)

    series = [_record_to_point(r, i) for i, r in enumerate(records, start=1)]
    chunks = retrieval.retrieve(analysis.retrieval_query, k=evt.k)

    result: dict = {
        "patient_id": evt.patient_id,
        "demographics": demographics,
        "records_analyzed": len(records),
        "series": series,
        "latest": series[-1] if series else None,
        "trajectory": asdict(analysis),
        "trajectory_summary": analysis.summary,
        "retrieval_query": analysis.retrieval_query,
        "retrieved_chunks": chunks,
        "assessment": None,
        "assessment_error": None,
    }

    if evt.run_agents:
        try:
            result["assessment"] = agents.run_pipeline(analysis.summary, chunks)
        except Exception as exc:  # Groq down / no key / rate-limited
            result["assessment_error"] = str(exc)

    return result
