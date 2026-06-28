"""Retrieve guideline chunks from ChromaDB using the trajectory summary.

Embeds the natural-language trajectory summary with the same all-MiniLM-L6-v2
model used at ingest time and queries the `ayushman_guidelines` collection for
the top-K most semantically similar chunks (cosine similarity).
"""

from __future__ import annotations

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


def retrieve(query_text: str, k: int = config.TOP_K) -> list[dict]:
    """Return the top-k guideline chunks for `query_text`.

    Each hit: {text, source_document, page, similarity, distance}.
    Cosine distance d → similarity = 1 - d.
    """
    res = get_collection().query(
        query_texts=[query_text],
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )

    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]

    hits: list[dict] = []
    for doc, meta, dist in zip(docs, metas, dists):
        meta = meta or {}
        hits.append(
            {
                "text": doc,
                # collections may tag the source as either key
                "source_document": meta.get("source_document") or meta.get("source_file"),
                "specialty": meta.get("specialty"),
                "page": meta.get("page"),
                "chunk_index": meta.get("chunk_index"),
                "distance": round(float(dist), 4),
                "similarity": round(1.0 - float(dist), 4),
            }
        )
    return hits
