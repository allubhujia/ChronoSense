"""MongoDB access — uses the async Motor client from backend/app/database.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pymongo import ASCENDING

from backend.app.database import get_database

from . import config


async def fetch_last_7_days(patient_id: str, end: datetime | None = None) -> list[dict]:
    end = end or datetime.now(timezone.utc)
    start = end - timedelta(days=config.TRAJECTORY_DAYS)

    db = get_database()
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
