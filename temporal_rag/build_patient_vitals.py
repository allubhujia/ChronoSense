"""Build the `patient_vitals` (+ `patients`) collections from radar `captures`.

WHAT IS REAL vs CONSTRUCTED
---------------------------
The `captures` collection is **cross-sectional**: 162 one-shot radar recordings
of 2 anonymous subjects each, with no patient identity and no timestamps. So:

  * REAL        : every heart_rate, respiratory_rate, movement proxy, and SNR is
                  taken directly from the radar captures; every drift_score and
                  SHAP value is computed by the interpretable drift_model.
  * CONSTRUCTED : the grouping of readings into "patients", and the assignment of
                  a 7-day timeline, are fabricated here — the dataset contains no
                  such information. With --sort-trajectory (default) each
                  patient's 7 readings are ordered by ascending drift so the
                  trajectory reads as a clinical progression for demo purposes.

This is the missing middle layer between batch_process.py (captures) and the
Temporal RAG pipeline (which reads patient_vitals).

Usage (from ChronoSense/, venv active):
    python -m temporal_rag.build_patient_vitals
    python -m temporal_rag.build_patient_vitals --days 7 --no-sort
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
from datetime import datetime, timedelta, timezone

from backend.app.database import close_mongo_connection, connect_to_mongo, get_database

from . import config, drift_model

# Condition assigned from a patient's dominant drift driver (for demographics).
_CONDITION_BY_DRIVER = {
    "hr": "CHF",
    "rr": "COPD",
    "movement": "Post-operative recovery",
}


def _movement_proxy(subject: dict) -> float:
    """Chest-movement amplitude proxy = std of the respiration preview waveform.

    A genuinely radar-derived restlessness signal (no patient label needed).
    """
    preview = subject.get("respiration", {}).get("per_second_preview") or []
    if len(preview) < 2:
        return 0.0
    return round(statistics.pstdev(preview), 4)


def _extract_readings(captures: list[dict]) -> list[dict]:
    """Flatten every capture's subjects into individual vital-sign readings."""
    readings: list[dict] = []
    for cap in captures:
        for subj in cap.get("subjects", []):
            hr = subj.get("heartbeat", {}).get("heart_rate_bpm")
            rr = subj.get("respiration", {}).get("breathing_rate_bpm")
            if hr is None or rr is None:
                continue
            hr_snr = subj.get("heartbeat", {}).get("snr_db", 0.0)
            rr_snr = subj.get("respiration", {}).get("snr_db", 0.0)
            readings.append(
                {
                    "heart_rate": float(hr),
                    "respiratory_rate": float(rr),
                    "movement_score": _movement_proxy(subj),
                    "snr_db": (float(hr_snr) + float(rr_snr)) / 2.0,
                    "source_file": cap.get("source_file"),
                }
            )
    return readings


def _dominant_driver(daily: list[drift_model.DriftResult]) -> str:
    totals = {
        "hr": sum(d.shap_hr for d in daily),
        "rr": sum(d.shap_rr for d in daily),
        "movement": sum(d.shap_movement for d in daily),
    }
    return max(totals, key=totals.get)


async def build(days: int = config.TRAJECTORY_DAYS, sort_trajectory: bool = True) -> None:
    await connect_to_mongo()
    db = get_database()

    captures = await db["captures"].find().sort("source_file", 1).to_list(length=None)
    readings = _extract_readings(captures)
    if not readings:
        raise SystemExit("No usable readings in captures collection.")

    n_patients = len(readings) // days
    if n_patients == 0:
        raise SystemExit(f"Need at least {days} readings; have {len(readings)}.")

    vitals_docs: list[dict] = []
    patient_docs: list[dict] = []
    now = datetime.now(timezone.utc)

    for p in range(n_patients):
        patient_id = f"PT{p + 1:03d}"
        window = readings[p * days : (p + 1) * days]

        # Score every reading, then (optionally) order by ascending drift so the
        # constructed 7-day trajectory reads as a worsening progression.
        scored = [
            (r, drift_model.score(r["heart_rate"], r["respiratory_rate"],
                                  r["movement_score"], r["snr_db"]))
            for r in window
        ]
        if sort_trajectory:
            scored.sort(key=lambda rs: rs[1].drift_score)

        daily_results = [s for _, s in scored]
        for i, (r, res) in enumerate(scored):
            ts = now - timedelta(days=days - 1 - i)
            vitals_docs.append(
                {
                    "patient_id": patient_id,
                    "timestamp": ts,
                    "heart_rate": r["heart_rate"],
                    "respiratory_rate": r["respiratory_rate"],
                    "movement_score": r["movement_score"],
                    "drift_score": res.drift_score,
                    "drift_score_lower_ci": res.lower_ci,
                    "drift_score_upper_ci": res.upper_ci,
                    "shap_hr": res.shap_hr,
                    "shap_rr": res.shap_rr,
                    "shap_movement": res.shap_movement,
                    "source_capture": r["source_file"],
                }
            )

        driver = _dominant_driver(daily_results)
        patient_docs.append(
            {
                "patient_id": patient_id,
                "condition": _CONDITION_BY_DRIVER[driver],
                "age": 45 + (p * 7) % 40,  # deterministic spread 45-84
                "primary_driver": driver,
            }
        )

    # Replace any previous build.
    await db[config.VITALS_COLLECTION].delete_many({})
    await db[config.PATIENTS_COLLECTION].delete_many({})
    await db[config.VITALS_COLLECTION].insert_many(vitals_docs)
    await db[config.PATIENTS_COLLECTION].insert_many(patient_docs)

    print(f"Captures read     : {len(captures)}")
    print(f"Readings extracted: {len(readings)}")
    print(f"Patients built    : {n_patients}  ({days} days each)")
    print(f"Vitals written    : {len(vitals_docs)} → '{config.VITALS_COLLECTION}'")
    print(f"Sample patient ids : {[d['patient_id'] for d in patient_docs[:5]]}")
    await close_mongo_connection()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build patient_vitals from radar captures.")
    ap.add_argument("--days", type=int, default=config.TRAJECTORY_DAYS)
    ap.add_argument("--no-sort", action="store_true",
                    help="Keep capture order instead of sorting each trajectory by drift.")
    args = ap.parse_args()
    asyncio.run(build(days=args.days, sort_trajectory=not args.no_sort))
