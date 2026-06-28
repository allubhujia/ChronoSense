# ChronoSense — Temporal RAG Pipeline

A Temporal RAG pipeline for the ChronoSense telemedicine system. When a patient
**drift event** fires, it builds a **7-day drift trajectory** from MongoDB,
turns it into a clinician-style natural-language query, retrieves the most
relevant **Ayushman Bharat Digital Mission** guideline chunks from ChromaDB
(cosine similarity), and feeds them to a **multi-agent LLM system on Groq** for
an Indian-localized, PM-JAY-aligned clinical assessment.

```
drift event ─▶ MongoDB (last 7 days)
                   │
                   ▼
        trajectory.py  ── "Patient with COPD, age 68. 7-day RR-driven drift
                            trajectory showing acceleration: day1 score 0.034 …
                            RR primary driver (avg attribution 0.158). HR secondary
                            involvement from day 1. Drift rate accelerating."
                   │  (embed: clinical_guidelines DefaultEmbeddingFunction)
                   ▼
        ChromaDB `indian_stg_guidelines`  ── top-3 cosine chunks (+ source, page)
                   │
                   ▼
        Groq multi-agent  ── ClinicalAnalyst ▶ GuidelineGrounder ▶ CareCoordinator
                   │
                   ▼
        triage decision + cited recommendation + patient message
```

## Layout
```
temporal_rag/
├── config.py              # paths, constants, shared embedder (reuses clinical_guidelines/chroma_db)
├── drift_model.py         # interpretable linear drift scorer + EXACT analytic SHAP
├── build_patient_vitals.py# captures → patient_vitals (+ patients) collections
├── db.py                  # MongoDB (async Motor, via backend/app/database.py)
├── trajectory.py          # 7-day records → drift trajectory summary (the RAG query)
├── retrieval.py           # embed summary → top-3 cosine guideline chunks
├── agents.py              # Groq 3-agent clinical reasoning chain
├── pipeline.py            # end-to-end orchestration + CLI
├── app.py                 # FastAPI surface
├── seed_mongo.py          # (optional) seed one synthetic CHF patient
├── requirements.txt
└── .env.example
```
> The vector store is **reused** from `../clinical_guidelines/chroma_db/`
> (collection `indian_stg_guidelines`, built by `clinical_guidelines/ingest_guidelines.py`).
> This module does not ingest PDFs itself.

## Setup
```bash
# from ChronoSense/ (venv active) — only groq is a genuinely new dep
pip install -r temporal_rag/requirements.txt
cp temporal_rag/.env.example temporal_rag/.env   # then fill in GROQ_API_KEY
```

## 1. Knowledge base — already built
The RAG layer reuses `clinical_guidelines/chroma_db` (the `indian_stg_guidelines`
collection of ICMR/MoHFW STW PDFs). If it isn't built yet:
```bash
cd ../clinical_guidelines && python ingest_guidelines.py && cd -
```

## 2. Build `patient_vitals` from the radar captures
The radar `captures` collection has no patient identity/timeline, so this step
constructs synthetic patients + a 7-day window over the **real** radar vitals and
scores each day with the interpretable drift model (real drift + exact SHAP):
```bash
python -m temporal_rag.build_patient_vitals          # ~46 patients (PT001…)
python -m temporal_rag.build_patient_vitals --no-sort  # keep capture order
```
> Or, for a single fully-synthetic demo patient: `python -m temporal_rag.seed_mongo`.

## 3. Run the pipeline
```bash
# CLI — full pipeline (needs GROQ_API_KEY)
python -m temporal_rag.pipeline PT010

# CLI — trajectory + retrieval only, no LLM / no API key
python -m temporal_rag.pipeline PT010 --no-agents

# API
uvicorn temporal_rag.app:app --reload --port 8001
```

### API
| Method | Path           | Purpose                                             |
|--------|----------------|-----------------------------------------------------|
| GET    | `/health`      | Liveness + indexed-chunk count                      |
| POST   | `/drift-event` | Full pipeline for `{patient_id}`                    |
| POST   | `/trajectory`  | Trajectory summary only (no retrieval/LLM)          |
| POST   | `/retrieve`    | Top-k chunks for an arbitrary `{query}`             |

```bash
curl -X POST localhost:8001/drift-event \
  -H 'content-type: application/json' \
  -d '{"patient_id": "PT010"}'
```

## MongoDB schema (`patient_vitals`)
`patient_id, timestamp, heart_rate, respiratory_rate, movement_score,
drift_score, drift_score_lower_ci, drift_score_upper_ci, shap_hr, shap_rr,
shap_movement`. Demographics (`condition`, `age`) are read, if present, from an
optional `patients` collection to enrich the trajectory summary.

> Radar measures HR, RR and a movement proxy only (no SpO2 — that needs a pulse
> oximeter), so the model uses three SHAP features: `shap_hr, shap_rr,
> shap_movement`.

## The multi-agent layer
Three Groq agents run in sequence, each seeing the trajectory summary + retrieved
chunks plus the prior agent's output:
1. **ClinicalAnalyst** — physiological interpretation of the drift trajectory.
2. **GuidelineGrounder** — maps it to the retrieved guidelines, citing source + page.
3. **CareCoordinator** — emits JSON: `triage_level`, `rationale`,
   `recommended_actions`, `citations`, `patient_message`.

Default model: `llama-3.3-70b-versatile` (override with `GROQ_MODEL`).
