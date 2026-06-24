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


async def list_captures(limit: int = 20) -> list[dict[str, Any]]:
    db = get_database()
    cursor = db[settings.radar_collection].find({}, _HIDE_ID).limit(limit)
    return await cursor.to_list(length=limit)


async def list_labels(limit: int = 20) -> list[dict[str, Any]]:
    db = get_database()
    cursor = db[settings.label_collection].find({}, _HIDE_ID).limit(limit)
    return await cursor.to_list(length=limit)


async def get_capture(radar_npy: str) -> dict[str, Any] | None:
    db = get_database()
    return await db[settings.radar_collection].find_one(
        {"npy_path": radar_npy}, _HIDE_ID
    )


async def get_labels_for_capture(radar_npy: str) -> list[dict[str, Any]]:
    db = get_database()
    cursor = db[settings.label_collection].find(
        {"matched_radar_npy": radar_npy}, _HIDE_ID
    )
    return await cursor.to_list(length=None)


async def get_label(source_file: str) -> dict[str, Any] | None:
    db = get_database()
    return await db[settings.label_collection].find_one(
        {"source_file": source_file}, _HIDE_ID
    )


async def get_pair(radar_npy: str) -> dict[str, Any] | None:
    """Return {radar, labels} for one capture, or None if the radar is unknown."""
    radar = await get_capture(radar_npy)
    if radar is None:
        return None
    labels = await get_labels_for_capture(radar_npy)
    return {"radar": radar, "labels": labels}
