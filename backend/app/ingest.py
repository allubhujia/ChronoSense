"""Load the processed dataset's two index JSON files into MongoDB.

  Processed_Data/index.json      -> radar_captures collection (X)
  Processed_Data/log_index.json  -> labels collection         (Y)

Idempotent: re-running upserts on a stable key, so it will not create
duplicates. Run it once before starting the server.

Usage (from the backend/ folder):
    python -m app.ingest
    python -m app.ingest --dataset-root ../FMCW_dataset
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pymongo import MongoClient, UpdateOne

from .config import settings


def _load_index(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"Index file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("files", [])


def _upsert(collection, docs: list[dict], key: str) -> int:
    """Upsert each doc keyed on a unique field; returns number written."""
    if not docs:
        return 0
    ops = [UpdateOne({key: d[key]}, {"$set": d}, upsert=True) for d in docs]
    result = collection.bulk_write(ops, ordered=False)
    return result.upserted_count + result.modified_count


def ingest(dataset_root: str | Path | None = None) -> None:
    root = Path(dataset_root or settings.dataset_root).resolve()
    processed = root / "Processed_Data"
    radar_index = processed / "index.json"
    label_index = processed / "log_index.json"

    print(f"Dataset root : {root}")
    print(f"Mongo URI    : {settings.mongo_uri}")
    print(f"Database     : {settings.mongo_db}\n")

    client = MongoClient(settings.mongo_uri)
    db = client[settings.mongo_db]

    radar_docs = _load_index(radar_index)
    label_docs = _load_index(label_index)

    # Unique keys = the file paths, which are guaranteed distinct per document.
    n_radar = _upsert(db[settings.radar_collection], radar_docs, key="npy_path")
    n_label = _upsert(db[settings.label_collection], label_docs, key="label_npz_path")

    # Indexes that back the queries the server runs (pairing + lookups).
    db[settings.radar_collection].create_index("npy_path", unique=True)
    db[settings.label_collection].create_index("label_npz_path", unique=True)
    db[settings.label_collection].create_index("matched_radar_npy")
    db[settings.label_collection].create_index("source_file")

    print(f"radar_captures : {n_radar} docs upserted "
          f"({db[settings.radar_collection].count_documents({})} total)")
    print(f"labels         : {n_label} docs upserted "
          f"({db[settings.label_collection].count_documents({})} total)")
    print("\nDone.")
    client.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Ingest ChronoSense dataset into MongoDB.")
    ap.add_argument("--dataset-root", default=None,
                    help="Path to FMCW_dataset (default: from settings/.env).")
    args = ap.parse_args()
    ingest(args.dataset_root)
