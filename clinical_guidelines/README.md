# ChronoSense — Clinical Guidelines (RAG layer)

Indian clinical-knowledge layer for ChronoSense. The radar pipeline measures
**breathing rate** and **heart rate**; this folder turns the official
**ICMR / MoHFW Standard Treatment Workflows (STWs)** into a queryable ChromaDB
knowledge base so those readings can be interpreted against **localized Indian
clinical thresholds** (and PM-JAY care pathways) instead of generic WHO averages.

## Why STWs (not raw patient datasets)
The STW PDFs are text-based clinical manuals with explicit rules — numeric
thresholds, normal/abnormal cutoffs, and referral pathways (e.g. *"Respiratory
rate ≥30/min → refer to higher centre"*). That's exactly what a chunk-and-embed
RAG layer needs. Raw tabular patient data only gives historical trends, not the
concrete directives required for real-time monitoring.

## Folder layout
```
clinical_guidelines/
├── stg_pdfs/
│   ├── cardiology_stw.pdf      # ICMR cardiology STW  (16 pages)
│   └── pulmonology_stw.pdf     # ICMR pulmonology STW (14 pages)
├── ingest_guidelines.py        # PDF → clean → chunk → embed → ChromaDB
├── query_guidelines.py         # semantic search + vital-sign assessment
├── chroma_db/                  # (generated) persistent vector store
├── requirements.txt
└── README.md
```

## Setup
```bash
# from clinical_guidelines/ (venv active)
pip install -r requirements.txt
```
> First run downloads ChromaDB's default MiniLM embedding model (~80 MB), then
> works offline. CPU-only is fine.

## 1. Build the knowledge base
```bash
python ingest_guidelines.py            # incremental (upsert)
python ingest_guidelines.py --rebuild  # drop and rebuild from scratch
```
Extracts both PDFs, chunks them (~600-char, sentence-aware, 1-sentence overlap),
embeds each chunk, and stores it with metadata `{specialty, source_file, page,
chunk_index}` in the `indian_stg_guidelines` collection.

## 2. Query it
```bash
# free-text semantic search
python query_guidelines.py "respiratory rate threshold for distress"

# assess a ChronoSense reading directly
python query_guidelines.py --breathing 32 --heart 110
```
`assess_vitals()` builds a clinical query from the measured rates and pulls the
most relevant guideline chunks per specialty (respiration → pulmonology, heart →
cardiology).

## How it plugs into ChronoSense
```
radar .bin → vital_signs.py → breathing/heart rate
                                   │
                                   ▼
                 query_guidelines.assess_vitals(br, hr)
                                   │  retrieves Indian STW context
                                   ▼
                       GenAI layer → localized assessment / alert
```
`assess_vitals()` returns `{reading, retrieved_context}` — the retrieved chunks
are the grounding context a GenAI summarizer would turn into an Indian-localized,
PM-JAY-aligned assessment.
