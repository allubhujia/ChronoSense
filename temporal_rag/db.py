"""MongoDB access — uses the async Motor client from backend/app/database.py."""

from __future__ import annotations

from datetime import datetime, timedelta

from pymongo import ASCENDING

from backend.app.database import get_database

from . import config


async def fetch_last_7_days(patient_id: str, end: datetime | None = None) -> list[dict]:
    db = get_database()

    # When no explicit end is given, anchor the 7-day window to the patient's
    # MOST RECENT reading rather than wall-clock now. The demo dataset is fixed
    # (built once), so as real time moves past 7 days a now-based window would
    # silently return nothing. Anchoring to the latest record keeps the
    # trajectory resolving regardless of how old the data is.
    if end is None:
        latest = await db[config.VITALS_COLLECTION].find_one(
            {"patient_id": patient_id}, sort=[("timestamp", -1)]
        )
        if not latest:
            return []
        end = latest["timestamp"]

    start = end - timedelta(days=config.TRAJECTORY_DAYS)
    cursor = (
        db[config.VITALS_COLLECTION]
        .find({"patient_id": patient_id, "timestamp": {"$gte": start, "$lte": end}})
        .sort("timestamp", ASCENDING)
    )
    return await cursor.to_list(length=None)


async def fetch_demographics(patient_id: str) -> dict:
    try:
        db = get_database()
        doc = await db[config.PATIENTS_COLLECTION].find_one({"patient_id": patient_id})
    except Exception:
        doc = None
    return doc or {}
