"""Async MongoDB connection using Motor.

We keep a single client for the whole app lifetime. FastAPI opens it on
startup and closes it on shutdown (see main.py's lifespan handler).
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .config import settings


class _MongoState:
    """Holds the live client so other modules can reach it after startup."""

    client: AsyncIOMotorClient | None = None


_state = _MongoState()


async def connect_to_mongo() -> None:
    """Open the MongoDB connection (called on FastAPI startup)."""
    _state.client = AsyncIOMotorClient(settings.mongo_uri)
    # Fail fast / log clearly if Mongo is unreachable.
    await _state.client.admin.command("ping")


async def close_mongo_connection() -> None:
    """Close the MongoDB connection (called on FastAPI shutdown)."""
    if _state.client is not None:
        _state.client.close()
        _state.client = None


def get_database() -> AsyncIOMotorDatabase:
    """Return the active database handle (raises if not connected yet)."""
    if _state.client is None:
        raise RuntimeError("MongoDB is not connected. Did startup run?")
    return _state.client[settings.mongo_db]
