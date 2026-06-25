"""
Query the Indian STG guideline knowledge base built by ingest_guidelines.py.

Two entry points:
  - query(text)          : free-text semantic search over the guidelines.
  - assess_vitals(...)   : given ChronoSense radar readings (breathing rate,
                           heart rate), build a clinical query and retrieve the
                           most relevant guideline chunks. This is the seam where
                           a GenAI layer would consume the retrieved context to
                           produce an Indian-localized assessment / alert.

Usage (from clinical_guidelines/, after ingest_guidelines.py has run):
    python query_guidelines.py "respiratory rate threshold for distress"
    python query_guidelines.py --breathing 32 --heart 110
"""

from __future__ import annotations

import argparse
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

_SCRIPT_DIR = Path(__file__).resolve().parent
_CHROMA_DIR = _SCRIPT_DIR / "chroma_db"
_COLLECTION = "indian_stg_guidelines"


def get_collection() -> chromadb.Collection:
    """Open the persistent guideline collection (raises if not built yet)."""
    client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
    embed_fn = embedding_functions.DefaultEmbeddingFunction()
    return client.get_collection(name=_COLLECTION, embedding_function=embed_fn)


def query(text: str, k: int = 4, specialty: str | None = None) -> list[dict]:
    """Semantic search. Optionally restrict to one specialty (cardiology/pulmonology)."""
    collection = get_collection()
    where = {"specialty": specialty} if specialty else None
    res = collection.query(query_texts=[text], n_results=k, where=where)

    out: list[dict] = []
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        out.append({"text": doc, "metadata": meta, "distance": dist})
    return out


def assess_vitals(breathing_rate: float | None = None,
                  heart_rate: float | None = None,
                  k: int = 4) -> dict:
    """Retrieve the guideline context relevant to a ChronoSense reading.

    Builds a natural-language clinical query from the radar-measured rates and
    pulls the matching guideline chunks from each relevant specialty. Returns a
    dict of {reading, retrieved_context} ready to feed a GenAI summarizer.
    """
    results: dict[str, list[dict]] = {}

    if breathing_rate is not None:
        q = (f"adult respiratory rate {breathing_rate} breaths per minute - "
             f"is this normal or respiratory distress, and what action is advised")
        results["respiration"] = query(q, k=k, specialty="pulmonology")

    if heart_rate is not None:
        q = (f"adult heart rate {heart_rate} beats per minute - "
             f"tachycardia or bradycardia threshold and management")
        results["heartbeat"] = query(q, k=k, specialty="cardiology")

    return {
        "reading": {"breathing_rate_bpm": breathing_rate, "heart_rate_bpm": heart_rate},
        "retrieved_context": results,
    }


def _print_hits(label: str, hits: list[dict]) -> None:
    print(f"\n=== {label} ===")
    for i, h in enumerate(hits, 1):
        m = h["metadata"]
        print(f"[{i}] ({m['specialty']} p{m['page']}, dist={h['distance']:.3f})")
        print(f"    {h['text'][:300]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Query the STG guideline knowledge base.")
    ap.add_argument("text", nargs="?", help="Free-text query.")
    ap.add_argument("--breathing", type=float, default=None,
                    help="Breathing rate (breaths/min) to assess.")
    ap.add_argument("--heart", type=float, default=None,
                    help="Heart rate (bpm) to assess.")
    ap.add_argument("-k", type=int, default=4, help="Number of chunks to return.")
    args = ap.parse_args()

    if args.breathing is not None or args.heart is not None:
        result = assess_vitals(args.breathing, args.heart, k=args.k)
        print(f"Reading: {result['reading']}")
        for label, hits in result["retrieved_context"].items():
            _print_hits(label, hits)
    elif args.text:
        _print_hits(f"query: {args.text!r}", query(args.text, k=args.k))
    else:
        ap.error("provide a free-text query, or --breathing / --heart")
