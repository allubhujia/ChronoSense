"""Central configuration and the shared embedding function.

Retrieval must embed with the same model used to build the ChromaDB store
(clinical_guidelines/ingest_guidelines.py), so the embedder is defined here once.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load the .env sitting next to this module, regardless of the current working
# directory the command was launched from. Falls back to a normal upward search.
_MODULE_DIR = Path(__file__).resolve().parent
load_dotenv(_MODULE_DIR / ".env")
load_dotenv()  # also pick up a project-root .env if present

# ── ChromaDB (vector store reused from clinical_guidelines/) ──────────────────
PROJECT_ROOT = _MODULE_DIR.parent
CHROMA_DIR = Path(os.getenv("CHROMA_DIR", str(PROJECT_ROOT / "clinical_guidelines" / "chroma_db")))
COLLECTION_NAME = "indian_stg_guidelines"
TOP_K = 3

# ── MongoDB (connection managed by backend/app/database.py) ──────────────────
VITALS_COLLECTION = "patient_vitals"
PATIENTS_COLLECTION = "patients"   # optional demographics: {patient_id, condition, age}
TRAJECTORY_DAYS = 7

# ── Groq (multi-agent LLM) ───────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Human-readable labels for the SHAP attribution fields.
SHAP_FIELDS = {
    "shap_hr": "HR",
    "shap_rr": "RR",
    "shap_movement": "Movement",
}


def get_embedding_function():
    """Return the same DefaultEmbeddingFunction used by clinical_guidelines/ingest_guidelines.py.

    Must match the embedder used at ingest time — mixing models would make
    cosine similarity meaningless.
    """
    from chromadb.utils import embedding_functions

    return embedding_functions.DefaultEmbeddingFunction()
