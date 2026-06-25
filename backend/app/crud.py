"""Database access helpers.

Thin async functions that query MongoDB and hand back plain dicts. Kept
separate from the route/WebSocket code so the transport layer stays clean.
"""

from __future__ import annotations

from typing import Any

from .config import settings
from .database import get_database

# Mongo's internal _id is not JSON-serialisable as-is; we drop it everywhere.
_HIDE_ID: dict[str, int] = {"_id": 0}


async def list_captures(limit: int = 20, category: str | None = None) -> list[dict[str, Any]]:
    """List captures, newest-insertion order, optionally filtered by category."""
    db = get_database()
    query: dict[str, Any] = {}
    if category:
        query["category"] = category
    cursor = db[settings.capture_collection].find(query, _HIDE_ID).limit(limit)
    return await cursor.to_list(length=limit)


async def get_capture(source_file: str) -> dict[str, Any] | None:
    """One capture by its source .bin file name."""
    db = get_database()
    return await db[settings.capture_collection].find_one(
        {"source_file": source_file}, _HIDE_ID
    )


async def summary() -> dict[str, Any]:
    """Dataset-wide vital-sign statistics (counts + rate ranges across subjects)."""
    db = get_database()
    coll = db[settings.capture_collection]

    total_captures = await coll.count_documents({})
    # Unwind subjects so each person contributes one row to the aggregate.
    pipeline = [
        {"$unwind": "$subjects"},
        {"$group": {
            "_id": None,
            "total_subjects": {"$sum": 1},
            "avg_breathing_bpm": {"$avg": "$subjects.respiration.breathing_rate_bpm"},
            "min_breathing_bpm": {"$min": "$subjects.respiration.breathing_rate_bpm"},
            "max_breathing_bpm": {"$max": "$subjects.respiration.breathing_rate_bpm"},
            "avg_heart_bpm": {"$avg": "$subjects.heartbeat.heart_rate_bpm"},
            "min_heart_bpm": {"$min": "$subjects.heartbeat.heart_rate_bpm"},
            "max_heart_bpm": {"$max": "$subjects.heartbeat.heart_rate_bpm"},
        }},
        {"$project": {"_id": 0}},
    ]
    agg = await coll.aggregate(pipeline).to_list(length=1)
    stats = agg[0] if agg else {}

    # Round the averages for a tidy response.
    for k in ("avg_breathing_bpm", "avg_heart_bpm"):
        if k in stats and stats[k] is not None:
            stats[k] = round(stats[k], 1)

    # How many captures per category.
    by_cat = await coll.aggregate([
        {"$group": {"_id": "$category", "captures": {"$sum": 1}}},
        {"$project": {"_id": 0, "category": "$_id", "captures": 1}},
    ]).to_list(length=None)

    return {
        "total_captures": total_captures,
        "by_category": by_cat,
        **stats,
    }
