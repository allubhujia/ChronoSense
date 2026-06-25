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
import re
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions
import pypdf

# ── Paths / config ──────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_PDF_DIR = _SCRIPT_DIR / "stg_pdfs"
_CHROMA_DIR = _SCRIPT_DIR / "chroma_db"
_COLLECTION = "indian_stg_guidelines"

# Which PDFs to ingest, and the specialty tag each gets in its metadata.
_SOURCES = [
    {"file": "cardiology_stw.pdf", "specialty": "cardiology"},
    {"file": "pulmonology_stw.pdf", "specialty": "pulmonology"},
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
    pages: list[tuple[int, str]] = []
    for i, page in enumerate(reader.pages, start=1):
        pages.append((i, page.extract_text() or ""))
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


def build_chunks_for_pdf(pdf_path: Path, specialty: str) -> list[dict]:
    """Extract -> clean -> chunk one PDF into records ready for ChromaDB."""
    records: list[dict] = []
    for page_num, raw in extract_pages(pdf_path):
        cleaned = clean_text(raw)
        if not cleaned:
            continue
        for idx, chunk in enumerate(chunk_text(cleaned)):
            records.append({
                "id": f"{specialty}_p{page_num}_c{idx}",
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
def get_client() -> chromadb.ClientAPI:
    """Persistent ChromaDB client rooted at clinical_guidelines/chroma_db/."""
    return chromadb.PersistentClient(path=str(_CHROMA_DIR))


def ingest(rebuild: bool = False) -> None:
    print(f"PDF dir     : {_PDF_DIR}")
    print(f"Chroma dir  : {_CHROMA_DIR}")
    print(f"Collection  : {_COLLECTION}\n")

    client = get_client()
    embed_fn = embedding_functions.DefaultEmbeddingFunction()

    if rebuild:
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

    total = 0
    for src in _SOURCES:
        pdf_path = _PDF_DIR / src["file"]
        if not pdf_path.is_file():
            print(f"[WARN] missing PDF, skipping: {pdf_path}")
            continue

        records = build_chunks_for_pdf(pdf_path, src["specialty"])
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

    print(f"\n{'=' * 56}")
    print(f"DONE: {total} chunks in collection '{_COLLECTION}' "
          f"({collection.count()} total stored)")
    print(f"{'=' * 56}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Ingest Indian STG PDFs into ChromaDB.")
    ap.add_argument("--rebuild", action="store_true",
                    help="Drop and rebuild the collection from scratch.")
    args = ap.parse_args()
    ingest(rebuild=args.rebuild)
