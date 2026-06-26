"""End-to-end Temporal RAG orchestration.

drift event for patient_id
   → fetch last 7 days of vitals (MongoDB)
   → build trajectory summary (+ optional demographics)
   → retrieve top-3 guideline chunks (ChromaDB, cosine)
   → multi-agent clinical assessment (Groq)
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from . import agents, config, db, retrieval, trajectory


async def build_trajectory(patient_id: str, end: datetime | None = None):
    """Stages 1-2: fetch vitals and construct the trajectory analysis."""
    records = await db.fetch_last_7_days(patient_id, end=end)
    if not records:
        raise ValueError(
            f"No vitals found for patient '{patient_id}' in the last "
            f"{config.TRAJECTORY_DAYS} days."
        )
    demographics = await db.fetch_demographics(patient_id)
    return trajectory.analyze(records, demographics=demographics), len(records)


async def run(
    patient_id: str,
    end: datetime | None = None,
    k: int = config.TOP_K,
    run_agents: bool = True,
) -> dict:
    """Full pipeline for a drift event. Set run_agents=False to skip the LLM
    stage (useful for testing retrieval without a Groq key)."""
    analysis, n_records = await build_trajectory(patient_id, end=end)
    # Retrieve with the clinical vignette (better guideline match), not the
    # ML-jargon summary; the summary is still what the agents reason over.
    chunks = retrieval.retrieve(analysis.retrieval_query, k=k)

    result = {
        "patient_id": patient_id,
        "records_analyzed": n_records,
        "trajectory": asdict(analysis),
        "trajectory_summary": analysis.summary,
        "retrieval_query": analysis.retrieval_query,
        "retrieved_chunks": chunks,
    }

    if run_agents:
        result["assessment"] = agents.run_pipeline(analysis.summary, chunks)

    return result


if __name__ == "__main__":
    import argparse
    import asyncio
    import json

    from backend.app.database import close_mongo_connection, connect_to_mongo

    ap = argparse.ArgumentParser(description="Run the ChronoSense Temporal RAG pipeline.")
    ap.add_argument("patient_id", help="Patient id to assess.")
    ap.add_argument("-k", type=int, default=config.TOP_K, help="Chunks to retrieve.")
    ap.add_argument("--no-agents", action="store_true", help="Skip the Groq LLM stage.")
    args = ap.parse_args()

    async def _main() -> None:
        # CLI doesn't go through the FastAPI lifespan, so open Mongo ourselves.
        await connect_to_mongo()
        try:
            out = await run(args.patient_id, k=args.k, run_agents=not args.no_agents)
            print(json.dumps(out, indent=2, default=str))
        finally:
            await close_mongo_connection()

    asyncio.run(_main())
