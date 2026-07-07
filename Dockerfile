# ── ChronoSense API image ────────────────────────────────────────────────────
# Serves the Temporal RAG dashboard API (temporal_rag.app:app on :8001).
# temporal_rag imports backend.app.database, so both packages live in the image.
# Retrieval uses sentence-transformers (all-mpnet-base-v2) — CPU-only torch.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Build tools for any packages without prebuilt wheels (e.g. chromadb deps).
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

# Install CPU-only torch first so sentence-transformers doesn't pull the huge
# CUDA build, then the three project requirement sets.
COPY backend/requirements.txt          backend/requirements.txt
COPY temporal_rag/requirements.txt     temporal_rag/requirements.txt
COPY clinical_guidelines/requirements.txt clinical_guidelines/requirements.txt
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install \
      -r backend/requirements.txt \
      -r temporal_rag/requirements.txt \
      -r clinical_guidelines/requirements.txt

# Bake the embedding model into the image so the first query is instant and the
# container needs no network at runtime.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-mpnet-base-v2')"

# Application code. The FMCW_dataset is bind-mounted at runtime; the prebuilt
# ChromaDB store is baked in here (on the container's native FS, so SQLite can
# lock/query it reliably — a Windows bind mount can't).
COPY backend                          backend
COPY temporal_rag                     temporal_rag
COPY observability                    observability
COPY clinical_guidelines/chroma_db    clinical_guidelines/chroma_db

EXPOSE 8001
CMD ["uvicorn", "temporal_rag.app:app", "--host", "0.0.0.0", "--port", "8001"]
