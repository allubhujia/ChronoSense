"""
Ingest the Indian STG (Standard Treatment Workflow) PDFs into ChromaDB.

This builds the clinical-knowledge layer for ChronoSense: the ICMR / MoHFW
cardiology and pulmonology guidelines are extracted, chunked, embedded, and
stored in a local ChromaDB collection. ChronoSense's radar vital-sign readings
(breathing rate, heart rate) can then be matched against these localized,
Indian clinical thresholds via query_guidelines.py.

Pipeline
--------
1. Extract text page-by-page from each STG PDF (pypdf).
2. Clean and sentence-chunk the text (with small overlap so a threshold split
   across a boundary isn't lost).
3. Embed each chunk (ChromaDB's default MiniLM embedder) and store it with
   metadata (specialty, source file, page, chunk index) in a persistent
   collection.

Idempotent: with --rebuild the collection is dropped and rebuilt; otherwise
chunks are upserted on a stable id so re-running won't duplicate them.

Usage (from clinical_guidelines/):
    python ingest_guidelines.py
    python ingest_guidelines.py --rebuild
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import tempfile
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions
import pypdf

# ── Paths / config ──────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_PDF_DIR = _SCRIPT_DIR / "stg_pdfs"
# CHROMA_DIR can redirect the store off the WSL→Windows mount (where ChromaDB's
# SQLite compaction fails on large builds) onto a native ext4 path.
_CHROMA_DIR = Path(os.getenv("CHROMA_DIR", str(_SCRIPT_DIR / "chroma_db")))
_COLLECTION = "indian_stg_guidelines"

# All PDFs in stg_pdfs/ are ingested automatically. The specialty tag is inferred
# from the filename (keyword match); anything unrecognised is tagged "general".
_SPECIALTY_KEYWORDS = {
    "cardiology": ("cardio", "heart", "cardiac", "hf", "832ea0f4"),
    "pulmonology": ("pulmo", "copd", "gold", "respir", "lung", "asthma"),
}


def infer_specialty(filename: str) -> str:
    name = filename.lower()
    for specialty, keywords in _SPECIALTY_KEYWORDS.items():
        if any(k in name for k in keywords):
            return specialty
    return "general"


def discover_sources() -> list[dict]:
    """Find every PDF in stg_pdfs/ and tag each with an inferred specialty."""
    return [
        {"file": p.name, "specialty": infer_specialty(p.name)}
        for p in sorted(_PDF_DIR.glob("*.pdf"))
    ]

# Chunking: clinical thresholds are short, so keep chunks tight for precise
# retrieval, with a one-sentence overlap to preserve context across splits.
_MAX_CHARS = 600
_OVERLAP_SENTENCES = 1
_BATCH = 100


# ── Text extraction & chunking ──────────────────────────────────────────────
def extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    """Return [(page_number, text), ...] for a PDF (1-based page numbers)."""
    reader = pypdf.PdfReader(str(pdf_path))
    if reader.is_encrypted:
        # Try an empty owner password (common for "protected but not locked" PDFs).
        try:
            reader.decrypt("")
        except Exception:
            pass
    pages: list[tuple[int, str]] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            pages.append((i, page.extract_text() or ""))
        except Exception:
            pages.append((i, ""))  # skip just this page
    return pages


def clean_text(text: str) -> str:
    """Collapse whitespace and strip control noise from extracted PDF text."""
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def chunk_text(text: str, max_chars: int = _MAX_CHARS,
               overlap: int = _OVERLAP_SENTENCES) -> list[str]:
    """Sentence-aware chunking: pack sentences up to `max_chars`, overlapping
    the last `overlap` sentences into the next chunk."""
    # Split on sentence enders and hard line breaks; keep bullet-like fragments.
    sentences = re.split(r"(?<=[.;:!?])\s+|\n+", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        if current_len + len(sentence) > max_chars and current:
            chunks.append(" ".join(current))
            current = current[-overlap:] if overlap else []
            current_len = sum(len(s) + 1 for s in current)
        current.append(sentence)
        current_len += len(sentence) + 1
    if current:
        chunks.append(" ".join(current))
    # Drop trivially short chunks (page headers, stray tokens).
    return [c for c in chunks if len(c) >= 40]


def is_reference_chunk(chunk: str) -> bool:
    """True if a chunk looks like a bibliography / citation list rather than
    clinical guidance. GOLD/WHO PDFs have many reference pages that otherwise
    pollute retrieval (they match statistical query language but carry no
    directives), so we drop them at ingest time."""
    low = chunk.lower()
    if "pubmed" in low or "doi.org" in low or low.count("http") >= 2:
        return True
    if low.count("et al") >= 2:
        return True
    # Journal-citation pattern like "2017; 72(2): 117-21", appearing repeatedly.
    if len(re.findall(r"\b\d{4};\s*\d+\(\d+\)", chunk)) >= 2:
        return True
    return False


def build_chunks_for_pdf(pdf_path: Path, specialty: str) -> list[dict]:
    """Extract -> clean -> chunk one PDF into records ready for ChromaDB."""
    records: list[dict] = []
    for page_num, raw in extract_pages(pdf_path):
        cleaned = clean_text(raw)
        if not cleaned:
            continue
        for idx, chunk in enumerate(chunk_text(cleaned)):
            if is_reference_chunk(chunk):
                continue
            records.append({
                "id": f"{pdf_path.stem}_p{page_num}_c{idx}",
                "document": chunk,
                "metadata": {
                    "specialty": specialty,
                    "source_file": pdf_path.name,
                    "page": page_num,
                    "chunk_index": idx,
                },
            })
    return records


# ── ChromaDB ────────────────────────────────────────────────────────────────
def _on_windows_mount(path: Path) -> bool:
    """True if `path` lives on a WSL→Windows drvfs mount (/mnt/<drive>/...),
    where ChromaDB's SQLite compaction is unreliable."""
    return str(path).startswith("/mnt/")


def ingest(rebuild: bool = False) -> None:
    print(f"PDF dir     : {_PDF_DIR}")
    print(f"Chroma dir  : {_CHROMA_DIR}")
    print(f"Collection  : {_COLLECTION}\n")

    # ChromaDB's SQLite store fails compaction on /mnt/c (drvfs). So when the
    # final location is on such a mount, build into a native temp dir first and
    # copy the finished store across at the end. Transparent to the caller.
    final_dir = _CHROMA_DIR
    relocate = _on_windows_mount(final_dir)
    build_dir = Path(tempfile.mkdtemp(prefix="cs_chroma_")) if relocate else final_dir
    if relocate:
        print(f"Building on native FS: {build_dir}")
        print(f"(will copy to {final_dir} when done)\n")

    client = chromadb.PersistentClient(path=str(build_dir))
    embed_fn = embedding_functions.DefaultEmbeddingFunction()

    if rebuild and not relocate:
        try:
            client.delete_collection(_COLLECTION)
            print("Dropped existing collection (rebuild).")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=_COLLECTION,
        embedding_function=embed_fn,
        metadata={"description": "Indian ICMR/MoHFW STG guidelines for ChronoSense"},
    )

    sources = discover_sources()
    print(f"Discovered {len(sources)} PDF(s): "
          f"{', '.join(s['file'] + ' [' + s['specialty'] + ']' for s in sources)}\n")

    total = 0
    for src in sources:
        pdf_path = _PDF_DIR / src["file"]
        if not pdf_path.is_file():
            print(f"[WARN] missing PDF, skipping: {pdf_path}")
            continue

        # A single unreadable PDF (encrypted, corrupt, scanned-image-only) must
        # not abort the whole build — skip it and keep going.
        try:
            records = build_chunks_for_pdf(pdf_path, src["specialty"])
        except Exception as exc:
            print(f"[SKIP] could not read {src['file']}: {exc}")
            continue
        if not records:
            print(f"[SKIP] no extractable text in {src['file']}")
            continue
        print(f"{src['specialty']:12s}: {len(records)} chunks from {src['file']}")

        # Upsert in batches so re-running is safe and memory stays bounded.
        for i in range(0, len(records), _BATCH):
            batch = records[i:i + _BATCH]
            collection.upsert(
                ids=[r["id"] for r in batch],
                documents=[r["document"] for r in batch],
                metadatas=[r["metadata"] for r in batch],
            )
        total += len(records)

    stored = collection.count()

    # Release the client's file handles before moving the store across.
    del collection, client

    if relocate:
        print(f"\nCopying store {build_dir} → {final_dir} ...")
        if final_dir.exists():
            shutil.rmtree(final_dir, ignore_errors=True)
        shutil.copytree(build_dir, final_dir)
        shutil.rmtree(build_dir, ignore_errors=True)
        print("Copy complete.")

    print(f"\n{'=' * 56}")
    print(f"DONE: {total} chunks in collection '{_COLLECTION}' "
          f"({stored} total stored)")
    print(f"{'=' * 56}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Ingest Indian STG PDFs into ChromaDB.")
    ap.add_argument("--rebuild", action="store_true",
                    help="Drop and rebuild the collection from scratch.")
    args = ap.parse_args()
    ingest(rebuild=args.rebuild)
