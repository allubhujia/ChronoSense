# Running ChronoSense with Docker

The whole stack — **MongoDB + Temporal RAG API + React dashboard** — runs with one
`docker compose` command. No local Python venv, Node, or Mongo install needed on
the host; only Docker Desktop (with WSL integration enabled).

```
┌──────────────┐     /api/*      ┌──────────────┐   mongodb://mongo  ┌──────────┐
│  frontend    │ ───────────────▶│  api         │ ──────────────────▶│  mongo   │
│  nginx :5173 │  (nginx proxy)  │ FastAPI :8001│                    │  :27017  │
└──────────────┘                 └──────────────┘                    └──────────┘
   React build                    temporal_rag.app                    captures +
                                  + baked ChromaDB                    patient_vitals
```

## Prerequisites

1. Docker Desktop running, with **WSL Integration** enabled for your Ubuntu distro
   (Settings → Resources → WSL Integration).
2. A Groq key in **`temporal_rag/.env`** (already gitignored):
   ```
   GROQ_API_KEY=gsk_your_real_key
   GROQ_MODEL=llama-3.3-70b-versatile
   ```
3. The prebuilt vector store at `clinical_guidelines/chroma_db/` (baked into the
   api image). If it's missing, build it once on the host first:
   `cd clinical_guidelines && python ingest_guidelines.py --rebuild`.

## First run

```bash
# 1. Build the api + frontend images (first build is slow: torch + mpnet model)
docker compose build

# 2. Start everything
docker compose up -d

# 3. Seed MongoDB (one-time) — captures, then the 46 patients
docker compose exec api python -m backend.app.ingest
docker compose exec api python -m temporal_rag.build_patient_vitals
```

Then open:
- **Dashboard** → http://localhost:5173
- **API docs** → http://localhost:8001/docs

## Everyday use

```bash
docker compose up -d       # start
docker compose down        # stop (keeps Mongo data in the mongo_data volume)
docker compose logs -f api # watch API logs
```

MongoDB data persists in the `mongo_data` named volume, so you only seed once.

## Notes

- **ChromaDB is baked into the api image**, not mounted — SQLite needs write
  access to lock, which a Windows bind mount can't reliably provide. If you
  change the guideline PDFs and rebuild the store on the host, run
  `docker compose build api` to bake the new store in.
- **Groq calls are live**; the nginx proxy allows a 120s timeout for the
  multi-agent assessment.
- To rebuild after code changes: `docker compose up -d --build`.
