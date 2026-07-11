"""Retrieve guideline chunks from ChromaDB using the trajectory summary.

Embeds the query with the same model used at ingest time and returns the top-K
most similar chunks (cosine).

Doctor-feedback weighting: each chunk may have a retrieval weight in the
`chunk_weights` Mongo collection (written by the standalone
update_chunk_weights.py script from 👍/👎 ratings). Retrieval over-fetches
candidates, multiplies each raw similarity by its weight (default 1.0), then
re-ranks — so consistently down-voted chunks surface less even when their raw
similarity is high.
"""

from __future__ import annotations

import time
from functools import lru_cache

import chromadb

from . import config


@lru_cache(maxsize=1)
def get_collection() -> chromadb.Collection:
    """Open the persistent guideline collection (raises if not ingested yet)."""
    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    return client.get_collection(
        name=config.COLLECTION_NAME,
        embedding_function=config.get_embedding_function(),
    )


# ── Chunk weights (doctor feedback) ──────────────────────────────────────────
# Cached with a short TTL so a running server picks up new weights within a
# minute of the update script running, without a per-request Mongo round-trip.
_WEIGHTS_TTL_S = 60.0
_weights_cache: dict[str, float] = {}
_weights_loaded_at: float = 0.0


def _load_weights() -> dict[str, float]:
    """Fetch {chunk_id: weight} from Mongo via a short-lived sync client.

    Retrieval is synchronous (called inside async handlers via the event
    loop's default executor semantics), so a sync pymongo read keeps this
    self-contained. Any failure (Mongo down, collection absent) → no weights,
    which means every chunk keeps its neutral 1.0.
    """
    global _weights_cache, _weights_loaded_at
    now = time.monotonic()
    if now - _weights_loaded_at < _WEIGHTS_TTL_S:
        return _weights_cache

    weights: dict[str, float] = {}
    try:
        from pymongo import MongoClient

        from backend.app.config import settings

        client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=2000)
        coll = client[settings.mongo_db][config.CHUNK_WEIGHTS_COLLECTION]
        for doc in coll.find({}, {"_id": 0, "chunk_id": 1, "weight": 1}):
            weights[doc["chunk_id"]] = float(doc["weight"])
        client.close()
    except Exception:
        pass  # neutral weights on any failure

    _weights_cache = weights
    _weights_loaded_at = now
    return weights


def refresh_weights() -> None:
    """Force the next retrieve() to reload weights (used by tests/scripts)."""
    global _weights_loaded_at
    _weights_loaded_at = 0.0


def retrieve(query_text: str, k: int = config.TOP_K) -> list[dict]:
    """Return the top-k guideline chunks for `query_text`, feedback-weighted.

    Each hit: {chunk_id, text, source_document, page, similarity, distance,
    weight, weighted_similarity}. Cosine distance d → similarity = 1 - d.
    """
    # Over-fetch so a down-weighted high-similarity chunk can actually drop
    # out of the top-k and a slightly-lower neighbour can rise in.
    n_fetch = max(k, k * config.RETRIEVAL_OVERFETCH)
    res = get_collection().query(
        query_texts=[query_text],
        n_results=n_fetch,
        include=["documents", "metadatas", "distances"],
    )

    ids = res.get("ids", [[]])[0]
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]

    weights = _load_weights()

    hits: list[dict] = []
    for cid, doc, meta, dist in zip(ids, docs, metas, dists):
        meta = meta or {}
        similarity = round(1.0 - float(dist), 4)
        weight = weights.get(cid, 1.0)
        hits.append(
            {
                "chunk_id": cid,
                "text": doc,
                # collections may tag the source as either key
                "source_document": meta.get("source_document") or meta.get("source_file"),
                "specialty": meta.get("specialty"),
                "page": meta.get("page"),
                "chunk_index": meta.get("chunk_index"),
                "distance": round(float(dist), 4),
                "similarity": similarity,
                "weight": round(weight, 3),
                "weighted_similarity": round(similarity * weight, 4),
            }
        )

    # Re-rank on the feedback-adjusted score and keep the top-k.
    hits.sort(key=lambda h: h["weighted_similarity"], reverse=True)
    return hits[:k]
