# ChronoSense — Clinician Dashboard (Frontend)

React + TypeScript + Tailwind dashboard for the ChronoSense Temporal RAG
pipeline. It's a pure presentation layer: every panel is driven by a single
live call to the FastAPI backend in [`../temporal_rag`](../temporal_rag).

## Panels

1. **Latest Contactless Vitals** — HR / RR / movement from the radar (`latest`).
2. **Drift Gauge** — the 0–1 `drift_score` as a semicircular gauge.
3. **7-Day Drift Trajectory** — drift line + confidence band (`series`).
4. **SHAP Attribution** — per-feature contribution to the latest drift.
5. **AI Clinical Assessment** — the multi-agent triage, rationale, recommended
   actions, citations, and patient-friendly message.

## How data flows

```
React (Vite :5173)  ──/api/*──►  FastAPI (uvicorn :8001)  ──►  Mongo / ChromaDB / Groq
```

Vite proxies `/api/*` to `http://127.0.0.1:8001` (see `vite.config.ts`), so the
frontend never hard-codes the backend URL and there are no CORS surprises.

The whole dashboard is one call to `POST /dashboard { patient_id }`. If the Groq
assessment fails (no key / timeout / rate-limit), panels 1–4 still render and
panel 5 shows a "Retry assessment" button.

## Run it

**1. Start the backend** (from the project root, venv active):

```bash
uvicorn temporal_rag.app:app --reload --port 8001
```

Prerequisites for real data: ChromaDB built (`clinical_guidelines/ingest_guidelines.py`),
`patient_vitals` seeded (`python -m temporal_rag.build_patient_vitals`), and a
`GROQ_API_KEY` in `temporal_rag/.env` for the AI panel.

**2. Start the frontend** (from this folder):

```bash
npm install
npm run dev
```

Open http://localhost:5173. Pick a patient (PT001–PT046) and the dashboard
loads live; "Re-run Assessment" re-fetches.

## Build for production

```bash
npm run build      # type-checks + bundles to dist/
npm run preview    # serve the production build
```
