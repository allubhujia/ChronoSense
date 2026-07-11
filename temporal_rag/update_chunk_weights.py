"""Turn doctors' 👍/👎 chunk ratings into retrieval weights — manually, on demand.

No scheduler, no background job: the team runs this from the terminal whenever
they want retrieval to learn from accumulated feedback.

What it does
------------
1. Reads every rating from the `chunk_feedback` collection.
2. Per chunk: counts ups vs downs and computes a net score in [-1, +1]:
       score = (ups - downs) / (ups + downs)
3. Maps the score to a retrieval weight, linearly:
       score -1.0 → WEIGHT_MIN (0.3)   score 0 → 1.0   score +1.0 → WEIGHT_MAX (1.5)
   Chunks with fewer than --min-ratings ratings are left at neutral 1.0
   (not enough evidence to move them).
4. Prints a full report — every chunk's ups/downs/score/current→new weight,
   flagging consistently underperforming chunks — and asks for confirmation.
5. Only on "y": upserts the new weights into `chunk_weights`, which
   retrieval.py multiplies into similarity at query time (60s cache TTL, so a
   running server picks the change up within a minute).

Usage (from ChronoSense/, venv active — Mongo must be running):
    python -m temporal_rag.update_chunk_weights
    python -m temporal_rag.update_chunk_weights --min-ratings 3
    python -m temporal_rag.update_chunk_weights --yes        # skip the prompt (CI)
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone

from pymongo import MongoClient, UpdateOne

from backend.app.config import settings

from . import config


def _weight_from_score(score: float) -> float:
    """Linear map: -1 → WEIGHT_MIN, 0 → 1.0, +1 → WEIGHT_MAX (clamped)."""
    if score >= 0:
        w = 1.0 + score * (config.WEIGHT_MAX - 1.0)
    else:
        w = 1.0 + score * (1.0 - config.WEIGHT_MIN)  # score is negative
    return round(max(config.WEIGHT_MIN, min(config.WEIGHT_MAX, w)), 3)


def analyse(feedback: list[dict], min_ratings: int) -> list[dict]:
    """Aggregate ratings per chunk → proposed weights."""
    per_chunk: dict[str, dict] = defaultdict(lambda: {"up": 0, "down": 0, "sources": set()})
    for fb in feedback:
        entry = per_chunk[fb["chunk_id"]]
        entry[fb["rating"]] += 1
        if fb.get("source_document"):
            entry["sources"].add(f'{fb["source_document"]} p{fb.get("page", "?")}')

    rows: list[dict] = []
    for chunk_id, e in sorted(per_chunk.items()):
        total = e["up"] + e["down"]
        score = (e["up"] - e["down"]) / total
        enough = total >= min_ratings
        rows.append(
            {
                "chunk_id": chunk_id,
                "ups": e["up"],
                "downs": e["down"],
                "total": total,
                "score": round(score, 3),
                "new_weight": _weight_from_score(score) if enough else 1.0,
                "enough_evidence": enough,
                "source": next(iter(e["sources"]), "?"),
            }
        )
    return rows


def print_report(rows: list[dict], current: dict[str, float], min_ratings: int) -> list[dict]:
    """Show the full picture; return only the rows whose weight actually changes."""
    print("=" * 88)
    print("CHUNK FEEDBACK REPORT")
    print("=" * 88)
    if not rows:
        print("No feedback stored yet — nothing to do.")
        return []

    changes: list[dict] = []
    hdr = f'{"chunk_id":42s} {"👍":>3s} {"👎":>3s} {"score":>6s} {"now":>5s} {"→ new":>6s}  note'
    print(hdr)
    print("-" * 88)
    for r in rows:
        cur = current.get(r["chunk_id"], 1.0)
        note = ""
        if not r["enough_evidence"]:
            note = f"(<{min_ratings} ratings — kept neutral)"
        elif r["score"] <= -0.5:
            note = "⚠ consistently underperforming"
        elif r["score"] >= 0.5:
            note = "★ consistently useful"
        print(
            f'{r["chunk_id"][:42]:42s} {r["ups"]:3d} {r["downs"]:3d} '
            f'{r["score"]:6.2f} {cur:5.2f} {r["new_weight"]:6.2f}  {note}'
        )
        if abs(r["new_weight"] - cur) >= 0.001:
            changes.append(r)

    print("-" * 88)
    print(f"{len(rows)} rated chunk(s); {len(changes)} weight change(s) proposed.")
    return changes


def main() -> None:
    ap = argparse.ArgumentParser(description="Update chunk retrieval weights from doctor feedback.")
    ap.add_argument("--min-ratings", type=int, default=2,
                    help="Minimum ratings before a chunk's weight moves (default 2).")
    ap.add_argument("--yes", action="store_true", help="Apply without the confirmation prompt.")
    args = ap.parse_args()

    client = MongoClient(settings.mongo_uri)
    db = client[settings.mongo_db]

    feedback = list(db[config.FEEDBACK_COLLECTION].find())
    current = {
        d["chunk_id"]: float(d["weight"])
        for d in db[config.CHUNK_WEIGHTS_COLLECTION].find()
    }

    rows = analyse(feedback, args.min_ratings)
    changes = print_report(rows, current, args.min_ratings)
    if not changes:
        print("Nothing to apply.")
        client.close()
        return

    if not args.yes:
        answer = input("\nApply these weight updates? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted — no changes written.")
            client.close()
            return

    now = datetime.now(timezone.utc)
    ops = [
        UpdateOne(
            {"chunk_id": r["chunk_id"]},
            {"$set": {
                "chunk_id": r["chunk_id"],
                "weight": r["new_weight"],
                "score": r["score"],
                "ups": r["ups"],
                "downs": r["downs"],
                "updated_at": now,
            }},
            upsert=True,
        )
        for r in changes
    ]
    result = db[config.CHUNK_WEIGHTS_COLLECTION].bulk_write(ops, ordered=False)
    print(f"\nApplied: {result.upserted_count + result.modified_count} weight(s) written "
          f"to '{config.CHUNK_WEIGHTS_COLLECTION}'.")
    print("A running API picks these up within ~60s (weights cache TTL).")
    client.close()


if __name__ == "__main__":
    main()
