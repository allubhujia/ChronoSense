"""ChronoSense — LLM/RAG quality-evaluation pipeline (ZenML).

Runs the real assessment pipeline across a sample of patients, scores each with
groundedness + citation accuracy, aggregates the results, and compares against
the previous run to detect improvement or regression.
"""

import sys
from pathlib import Path

# Make the ChronoSense project importable (temporal_rag / backend live one level up).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio

from zenml import pipeline, step
from zenml.client import Client
from zenml.logger import get_logger

logger = get_logger(__name__)


# ── Step 1: load patient ids from MongoDB ────────────────────────────────────
@step
def load_patients(sample_size: int = 3) -> list:
    from backend.app.database import (
        close_mongo_connection,
        connect_to_mongo,
        get_database,
    )
    from temporal_rag import config

    async def _load():
        await connect_to_mongo()
        try:
            db = get_database()
            docs = (
                await db[config.PATIENTS_COLLECTION]
                .find({}, {"patient_id": 1, "_id": 0})
                .sort("patient_id", 1)
                .to_list(length=None)
            )
            return [d["patient_id"] for d in docs]
        finally:
            await close_mongo_connection()

    ids = asyncio.run(_load())
    selected = ids[:sample_size]
    logger.info(f"Loaded {len(ids)} patients; evaluating {len(selected)}: {selected}")
    return selected


# ── Step 2: run the real assessment + evaluation for each patient ────────────
@step
def run_assessments(patient_ids: list) -> list:
    from backend.app.database import close_mongo_connection, connect_to_mongo
    from temporal_rag import agents, db, evaluation, retrieval, trajectory

    async def _run():
        await connect_to_mongo()
        results = []
        try:
            for pid in patient_ids:
                recs = await db.fetch_last_7_days(pid)
                demo = await db.fetch_demographics(pid)
                if not recs:
                    logger.info(f"{pid}: no vitals, skipping")
                    continue
                analysis = trajectory.analyze(recs, demographics=demo)
                chunks = retrieval.retrieve(analysis.retrieval_query, k=3)
                assessment = agents.run_pipeline(analysis.summary, chunks)
                ev = evaluation.evaluate(assessment, chunks, summary=analysis.summary)
                g = ev.get("groundedness") or {}
                c = ev.get("citation_accuracy") or {}
                rec = {
                    "patient_id": pid,
                    "condition": demo.get("condition"),
                    "triage_level": assessment.get("care_coordination", {}).get("triage_level"),
                    "groundedness": g.get("groundedness"),
                    "verdict": g.get("verdict"),
                    "citation_accuracy": c.get("score"),
                }
                results.append(rec)
                logger.info(f"{pid}: groundedness={rec['groundedness']} citations={rec['citation_accuracy']}")
        finally:
            await close_mongo_connection()
        return results

    return asyncio.run(_run())


# ── Step 3: aggregate per-patient scores into one summary ────────────────────
@step
def aggregate_metrics(records: list) -> dict:
    scored = [r for r in records if r.get("groundedness") is not None]
    n = len(scored)
    if n == 0:
        summary = {"total": 0, "avg_groundedness": None, "avg_citation_accuracy": None, "below_threshold": 0}
        logger.info(f"SUMMARY: {summary}")
        return summary

    avg_g = round(sum(r["groundedness"] for r in scored) / n, 3)
    cites = [r["citation_accuracy"] for r in scored if r["citation_accuracy"] is not None]
    avg_c = round(sum(cites) / len(cites), 3) if cites else None
    below = sum(1 for r in scored if r["groundedness"] < 0.75)

    summary = {
        "total": n,
        "avg_groundedness": avg_g,
        "avg_citation_accuracy": avg_c,
        "below_threshold": below,
    }
    logger.info(f"SUMMARY: {summary}")
    return summary


# ── Step 4: compare to the previous run (improved / regressed / same) ────────
@step
def check_regression(summary: dict) -> str:
    cur = summary.get("avg_groundedness")
    prev_avg = None
    try:
        client = Client()
        runs = client.list_pipeline_runs(sort_by="desc:created", size=15)
        for run in runs:
            try:
                out = run.steps["aggregate_metrics"].output.load()
                val = out.get("avg_groundedness")
                if val is not None and val != cur:
                    prev_avg = val
                    break
            except Exception:
                continue
    except Exception as e:
        logger.info(f"Could not read a previous run: {e}")

    if prev_avg is None:
        verdict = f"First run / no baseline. avg_groundedness = {cur}"
    else:
        delta = round((cur or 0) - prev_avg, 3)
        if delta > 0.001:
            verdict = f"IMPROVED by {delta}  ({prev_avg} -> {cur})"
        elif delta < -0.001:
            verdict = f"REGRESSED by {abs(delta)}  ({prev_avg} -> {cur})"
        else:
            verdict = f"SAME  ({cur})"
    logger.info(verdict)
    return verdict


# ── Pipeline: wire the 4 steps together ──────────────────────────────────────
@pipeline
def llm_quality_pipeline(sample_size: int = 3):
    patients = load_patients(sample_size=sample_size)
    records = run_assessments(patients)
    summary = aggregate_metrics(records)
    check_regression(summary)


if __name__ == "__main__":
    llm_quality_pipeline(sample_size=3)
