"""Load the processed vital-sign JSONs into MongoDB.

The radar pipeline (digital_processing/batch_process.py) writes one JSON per
`.bin` capture under Processed_Data/, each holding both subjects' respiration
and heartbeat. This script walks those files and upserts them into the
`captures` collection.

  Processed_Data/**/<stem>.json   -> captures collection

The master Processed_Data/vitals_index.json is skipped (it's only a summary;
the per-capture files hold the full data).

Idempotent: re-running upserts on json_path, so it will not create duplicates.

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

_PROCESSED_DIR_NAME = "Processed_Data"
_INDEX_FILENAME = "vitals_index.json"


def _load_capture_jsons(processed: Path) -> list[dict]:
    """Read every per-capture JSON under Processed_Data/ (skipping the index)."""
    if not processed.is_dir():
        raise FileNotFoundError(f"Processed data folder not found: {processed}")
    docs: list[dict] = []
    for path in sorted(processed.rglob("*.json")):
        if path.name == _INDEX_FILENAME:
            continue
        with open(path, encoding="utf-8") as f:
            docs.append(json.load(f))
    return docs


def _upsert(collection, docs: list[dict], key: str) -> int:
    """Upsert each doc keyed on a unique field; returns number written."""
    if not docs:
        return 0
    ops = [UpdateOne({key: d[key]}, {"$set": d}, upsert=True) for d in docs]
    result = collection.bulk_write(ops, ordered=False)
    return result.upserted_count + result.modified_count


def ingest(dataset_root: str | Path | None = None) -> None:
    root = Path(dataset_root or settings.dataset_root).resolve()
    processed = root / _PROCESSED_DIR_NAME

    print(f"Dataset root : {root}")
    print(f"Mongo URI    : {settings.mongo_uri}")
    print(f"Database     : {settings.mongo_db}\n")

    client = MongoClient(settings.mongo_uri)
    db = client[settings.mongo_db]
    coll = db[settings.capture_collection]

    docs = _load_capture_jsons(processed)
    # json_path is unique per capture; source_file is too, but json_path is the
    # safest stable key (it encodes category + position + stem).
    n = _upsert(coll, docs, key="json_path")

    # Indexes backing the server's queries.
    coll.create_index("json_path", unique=True)
    coll.create_index("source_file")
    coll.create_index("category")

    print(f"captures : {n} upserted ({coll.count_documents({})} total)")
    print("\nDone.")
    client.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Ingest ChronoSense vital-sign JSONs into MongoDB.")
    ap.add_argument("--dataset-root", default=None,
                    help="Path to FMCW_dataset (default: from settings/.env).")
    args = ap.parse_args()
    ingest(args.dataset_root)
