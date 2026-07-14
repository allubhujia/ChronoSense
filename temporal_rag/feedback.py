"""Shared feedback → retrieval-weight logic.

Both the automatic path (POST /feedback recomputes a chunk's weight the moment a
doctor rates it) and the manual bulk script (update_chunk_weights.py) use the
same scoring so they can never disagree.

Weight mapping (linear, clamped):
    score -1.0 → WEIGHT_MIN (0.3)    score 0 → 1.0    score +1.0 → WEIGHT_MAX (1.5)
where  score = (ups - downs) / (ups + downs).
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import config


def weight_from_score(score: float) -> float:
    """Map a net rating score in [-1, 1] to a retrieval weight (clamped)."""
    if score >= 0:
        w = 1.0 + score * (config.WEIGHT_MAX - 1.0)
    else:
        w = 1.0 + score * (1.0 - config.WEIGHT_MIN)  # score negative → below 1.0
    return round(max(config.WEIGHT_MIN, min(config.WEIGHT_MAX, w)), 3)


async def recompute_chunk_weight(
    db, chunk_id: str, min_ratings: int = config.FEEDBACK_MIN_RATINGS
) -> float | None:
    """Recompute + persist one chunk's weight from its ratings (async/Motor).

    Called automatically after each 👍/👎. Returns the new weight, or None when
    the chunk doesn't yet have `min_ratings` ratings (kept neutral — no doc
    written, so it stays at the default 1.0 in retrieval).
    """
    coll = db[config.FEEDBACK_COLLECTION]
    ups = await coll.count_documents({"chunk_id": chunk_id, "rating": "up"})
    downs = await coll.count_documents({"chunk_id": chunk_id, "rating": "down"})
    total = ups + downs
    if total < min_ratings:
        return None

    score = (ups - downs) / total
    weight = weight_from_score(score)
    await db[config.CHUNK_WEIGHTS_COLLECTION].update_one(
        {"chunk_id": chunk_id},
        {"$set": {
            "chunk_id": chunk_id,
            "weight": weight,
            "score": round(score, 3),
            "ups": ups,
            "downs": downs,
            "updated_at": datetime.now(timezone.utc),
            "auto": True,  # distinguishes auto-updates from the bulk script
        }},
        upsert=True,
    )
    return weight
