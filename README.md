<div align="center">

# 🩺 ChronoSense

### Contactless Telemedicine — from Radar Waves to Grounded Clinical Decisions

**A radar reads two people breathing. A drift model watches them worsen over a week.
A retrieval-augmented multi-agent LLM grounds the alarm in real clinical guidelines.
A clinician sees it all on one live dashboard — with full Prometheus/Grafana observability.**

<br/>

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)
![NumPy](https://img.shields.io/badge/NumPy-013243?style=for-the-badge&logo=numpy&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![MongoDB](https://img.shields.io/badge/MongoDB-47A248?style=for-the-badge&logo=mongodb&logoColor=white)
![ChromaDB](https://img.shields.io/badge/ChromaDB-FF6F61?style=for-the-badge&logo=databricks&logoColor=white)
![Groq](https://img.shields.io/badge/Groq_LLaMA_3.3_70B-F55036?style=for-the-badge&logo=meta&logoColor=white)

![React](https://img.shields.io/badge/React_18-61DAFF?style=for-the-badge&logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)
![Tailwind](https://img.shields.io/badge/Tailwind_CSS-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white)
![Docker](https://img.shields.io/badge/Docker_Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Prometheus](https://img.shields.io/badge/Prometheus-E6522C?style=for-the-badge&logo=prometheus&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-F46800?style=for-the-badge&logo=grafana&logoColor=white)

</div>

---

## 📖 Table of Contents

| # | Section | What's inside |
|---|---------|---------------|
| 1 | [🌐 Overview](#-1-overview) | The problem, the idea, the end-to-end story |
| 2 | [🏗️ System Architecture](#️-2-system-architecture) | How every layer connects |
| 3 | [🧰 Tech Stack](#-3-tech-stack) | Every technology and why |
| 4 | [📁 Repository Structure](#-4-repository-structure) | The full directory tree |
| 5 | [📡 Layer 1 — Radar Signal Processing](#-5-layer-1--radar-signal-processing) | `.bin` → respiration + heartbeat |
| 6 | [🗄️ Layer 2 — Backend & Database](#️-6-layer-2--backend--database) | Captures API + MongoDB |
| 7 | [📉 Layer 3 — Drift Model](#-7-layer-3--drift-model) | Interpretable drift + exact SHAP |
| 8 | [🧠 Layer 4 — Temporal RAG + Agents](#-8-layer-4--temporal-rag--agents) | Trajectory → retrieval → LLM |
| 9 | [🖥️ Layer 5 — Clinician Dashboard](#️-9-layer-5--clinician-dashboard) | React front-end |
| 10 | [📊 Layer 6 — Observability](#-10-layer-6--observability) | Prometheus + Grafana |
| 11 | [🚀 Running the Whole Stack](#-11-running-the-whole-stack) | Docker & local |
| 12 | [🔢 Key Numbers](#-12-key-numbers) | Dataset & model figures |
| 13 | [✅ Status & Roadmap](#-13-status--roadmap) | Done and next |

---

## 🌐 1. Overview

**ChronoSense** is a contactless remote-patient-monitoring system. It replaces body-worn
sensors with a **60 GHz FMCW radar** that measures the tiny chest micro-movements of up to
**two people at once**, and turns those raw waves into an early-warning clinical decision that
is *grounded in real medical guidelines* rather than an LLM's imagination.

The journey of a single measurement:

```
📡 Radar wave  →  ❤️ Vital signs  →  📉 Drift score  →  🧠 RAG + Agents  →  🩺 Triage decision
 (contactless)     (HR, RR, move)    (7-day trend)     (guideline-grounded)   (on a dashboard)
```

| Stage | What happens | Output |
|-------|--------------|--------|
| **Sense** | FMCW radar captures chest micro-motion of 2 subjects | respiration + heartbeat |
| **Score** | Interpretable drift model measures deviation from healthy baselines | drift score 0–1 + SHAP |
| **Track** | 7 days of scores form a deterioration trajectory | accelerating / stable / improving |
| **Retrieve** | The trajectory becomes a clinical query against a guideline vector store | top-3 guideline chunks |
| **Reason** | 3 LLM agents interpret, ground, and coordinate care | triage + cited rationale |
| **Act** | Clinician sees vitals, drift, SHAP, and the AI assessment | one live dashboard |
| **Observe** | Every request, drift event, and LLM call is measured | Prometheus + Grafana |

---

## 🏗️ 2. System Architecture

```
                            ┌───────────────────────────────────────────────┐
   URLLC / eMBB / mMTC      │              docker compose up                 │
   ───────────────────▶     │                                               │
                            │   ┌──────────┐   7-day    ┌──────────────┐     │
  📡 FMCW Radar .bin        │   │ MongoDB  │──trajectory▶│ Temporal RAG │     │
        │                   │   │ captures │◀──write────│  (FastAPI)   │     │
        ▼                   │   │ patient_ │            │  :8001       │     │
  digital_processing/       │   │ vitals   │            │              │     │
   (NumPy DSP)              │   └──────────┘            │  ┌─────────┐ │     │
        │                   │   ┌──────────┐  retrieve  │  │ 3 Groq  │─┼──▶ Groq API
        ▼                   │   │ ChromaDB │◀──guideline─│  │ Agents  │ │   (LLaMA 3.3)
   captures + vitals ──────▶│   │ (mpnet)  │            │  └─────────┘ │     │
                            │   └──────────┘            └──────┬───────┘     │
                            │        ▲                         │ /metrics    │
                            │        │ scrape          ┌───────▼───────┐     │
                            │   ┌────┴─────┐  query     │   React 18    │     │
                            │   │Prometheus│◀───────────│  Dashboard    │◀───── 🩺 Clinician
                            │   │  :9090   │            │  nginx :5173  │     │
                            │   └────┬─────┘            └───────────────┘     │
                            │        │ visualize                             │
                            │   ┌────▼─────┐                                 │
                            │   │ Grafana  │  line / bar / stat / alerts     │
                            │   │  :3000   │                                 │
                            │   └──────────┘                                 │
                            └───────────────────────────────────────────────┘
```

---

## 🧰 3. Tech Stack

| Layer | Technology | Used for |
|-------|-----------|----------|
| 📡 **Signal processing** | Python · **NumPy** | Parsing raw radar ADC `.bin`, MTI, range-FFT, MVDR beamforming, phase→vitals |
| 🗄️ **Database** | **MongoDB** (Motor async · PyMongo sync) | `captures` (radar) + `patient_vitals` + `patients` |
| 🔎 **Vector store** | **ChromaDB** + **all-mpnet-base-v2** (768-dim) | Semantic retrieval of clinical guideline chunks (cosine similarity) |
| 🧠 **LLM agents** | **Groq · LLaMA 3.3 70B** | 3-agent clinical reasoning chain |
| 🌐 **API framework** | **FastAPI · Pydantic · Uvicorn** | REST + WebSocket, typed schemas |
| 🖥️ **Frontend** | **React 18 · TypeScript · Tailwind · Recharts** | Clinician dashboard |
| 🐳 **Orchestration** | **Docker Compose** | One-command full stack |
| 📊 **Observability** | **Prometheus · Grafana** | Metrics, live dashboards, alerts |
| 💻 **Runtime** | **WSL2 Ubuntu 24.04** (CPU-only) | Development environment |

---

## 📁 4. Repository Structure

```
ChronoSense/
│
├── 📡 digital_processing/          # Layer 1 — radar-only vital-sign extraction (NumPy DSP)
│   ├── fmcw_bin_parser.py          #   raw radar .bin → complex64 cube
│   ├── vital_signs.py              #   cube → per-subject respiration & heartbeat
│   └── batch_process.py            #   all .bin → .json + .npz + vitals_index.json
│
├── 🗄️ backend/                     # Layer 2 — captures API (FastAPI + MongoDB)
│   └── app/
│       ├── main.py                 #   REST + WebSocket server
│       ├── database.py             #   async Motor client (shared by temporal_rag)
│       ├── ingest.py               #   Processed_Data JSONs → captures collection
│       ├── config.py · crud.py · schemas.py
│
├── 🔎 clinical_guidelines/         # Vector-store builder
│   ├── stg_pdfs/                   #   GOLD 2024, WHO, ICMR cardiology/pulmonology PDFs
│   ├── ingest_guidelines.py        #   PDFs → chunk → embed (mpnet) → ChromaDB
│   └── chroma_db/                  #   persistent vector store (2,700 chunks)
│
├── 🧠 temporal_rag/                # Layers 3 & 4 — drift + Temporal RAG + agents
│   ├── drift_model.py              #   interpretable drift score + exact SHAP
│   ├── build_patient_vitals.py     #   captures → patient_vitals (46 patients)
│   ├── db.py                       #   MongoDB access (7-day fetch, demographics)
│   ├── trajectory.py               #   7-day trend → clinical query
│   ├── retrieval.py                #   ChromaDB top-3 guideline chunks
│   ├── agents.py                   #   3 Groq agents (Analyst → Grounder → Coordinator)
│   ├── pipeline.py                 #   end-to-end orchestration + CLI
│   └── app.py                      #   FastAPI (dashboard, drift-event, retrieve, /metrics)
│
├── 🖥️ frontend/                    # Layer 5 — React clinician dashboard
│   ├── src/
│   │   ├── App.tsx                 #   state + data fetching + layout
│   │   ├── api.ts · types.ts       #   typed API client + contracts
│   │   ├── lib/clinical.ts         #   triage→status, vital abnormality, formatters
│   │   └── components/             #   Header, StatusBanner, VitalsPanel, DriftGauge,
│   │                               #     TrajectoryChart, ShapBars, AssessmentPanel
│   ├── Dockerfile · nginx.conf     #   build → nginx (proxies /api → api:8001)
│   └── vite.config.ts
│
├── 📊 observability/               # Layer 6 — Prometheus + Grafana
│   ├── metrics.py                  #   4 metrics + FastAPI middleware
│   ├── prometheus/                 #   prometheus.yml + alerts.yml
│   └── grafana/                    #   provisioning + chronosense.json dashboard
│
├── 🐳 Dockerfile                   # API image (backend + temporal_rag + baked ChromaDB)
├── 🐳 docker-compose.yaml          # mongo + api + frontend + prometheus + grafana
├── 📄 DOCKER.md                    # full Docker build/seed/run guide
└── 📄 README.md                    # you are here
```

---

## 📡 5. Layer 1 — Radar Signal Processing

The dataset is *FMCW radar-based multi-person vital-sign monitoring data*, captured with a
**TI IWR6843ISK (60 GHz)** radar + **DCA1000EVM**. Two people sit in front of the radar; their
chests move with breathing (~mm) and heartbeats (~0.1 mm). The pipeline extracts each person's
vitals **straight from the raw radar `.bin`** — the reference ECG/PCG logs are *not* used.

```
   adc_*.bin (raw I/Q)
        │  batch_process.py → vital_signs.py
        ▼
   MTI + range-FFT → MVDR DOA → top-2 targets → beamform
        │
        ▼  phase → unwrap → diff → band-pass
   per subject:  respiration (0.1–0.6 Hz)   heartbeat (0.9–2.0 Hz)
        │
        ▼
   <stem>.json  +  <stem>.npz  +  vitals_index.json
```

| Step | Operation | Detail |
|------|-----------|--------|
| 1 | **Virtual array** | keep TX1 + TX3 → 8 virtual RX channels |
| 2 | **MTI + range-FFT** | mean-cancel slow-time clutter, 256-pt range-FFT |
| 3 | **MVDR DOA** | per range bin, Capon range-angle spectrum |
| 4 | **Find subjects** | greedily pick top-2 range-angle peaks (the two people) |
| 5 | **Beamform** | MVDR weights → one complex slow-time signal per target |
| 6 | **Phase → vitals** | `angle → unwrap → diff` → band-pass → FFT peak = rate |

> The DSP is a NumPy port of the dataset authors' MATLAB reference (`Main.m`, `MTI.m`,
> `IWR6843ISK_DOA.m`, `get_heartBreath_rate.m`). Band-pass uses a zero-phase FFT mask (no SciPy).

---

## 🗄️ 6. Layer 2 — Backend & Database

`backend/` serves the radar captures from MongoDB over REST + WebSocket, and its async Motor
client is **reused** by the Temporal RAG pipeline (one connection, one source of truth).

| Collection | Built by | Holds |
|------------|----------|-------|
| `captures` | `backend/app/ingest.py` | 162 radar recordings, 2 subjects each |
| `patient_vitals` | `temporal_rag/build_patient_vitals.py` | 46 patients × 7 days of scored vitals |
| `patients` | `temporal_rag/build_patient_vitals.py` | demographics: condition, age, primary driver |

**REST:** `/captures`, `/captures/{source_file}`, `/summary`, docs at `/docs`.
**WebSocket** (`/ws`): `ping`, `summary`, `list_captures`, `get_capture`.

---

## 📉 7. Layer 3 — Drift Model

A deliberately **transparent, linear-additive** scorer — so the SHAP attribution of each feature
is *exactly* its own term (no sampling, no `shap` library):

```
drift_score = clip( 0.45·HR_abnormality + 0.35·RR_abnormality + 0.20·Move_abnormality , 0, 1 )
```

| Feature | Normal range | Weight | Condition it flags |
|---------|--------------|--------|--------------------|
| ❤️ Heart rate | 60–100 bpm | **0.45** | CHF |
| 🫁 Respiratory rate | 12–20 br/min | **0.35** | COPD |
| 🏃 Movement | baseline ≈ 0.4 | **0.20** | Post-operative recovery |

Each reading yields a **drift score (0–1)**, three **exact SHAP values**, and a **confidence
interval** that widens as radar SNR drops.

---

## 🧠 8. Layer 4 — Temporal RAG + Agents

The heart of the system: 7 days of drift become a clinical query, which retrieves guidelines,
which ground a multi-agent assessment.

**Retrieval** — the trajectory is rendered as a clinical vignette and embedded with
**all-mpnet-base-v2** to fetch the top-3 chunks from ChromaDB (cosine similarity ≈ **0.71**).

**The 3-agent chain (Groq · LLaMA 3.3 70B):**

| # | Agent | Role | Output |
|---|-------|------|--------|
| 1 | 🔬 **ClinicalAnalyst** | Interpret the 7-day trajectory physiologically | 4–6 sentence interpretation |
| 2 | 📚 **GuidelineGrounder** | Map it onto retrieved guidelines, cite `(source, page)` | grounded bullet points |
| 3 | 🧭 **CareCoordinator** | Decide the next action | JSON: triage, rationale, actions, citations, patient message |

**Triage levels:** `routine_monitor` → `teleconsult` → `urgent_referral` → `emergency_escalation`.

---

## 🖥️ 9. Layer 5 — Clinician Dashboard

A **React 18 + TypeScript + Tailwind** single-screen dashboard. Enter a patient ID (`PT010`) and
it fetches a live report from `POST /dashboard`. If the Groq call fails, panels 1–4 still render.

| Panel | Shows | Component |
|-------|-------|-----------|
| 🟠 **Status banner** | Stable / Monitoring / Deteriorating / Critical (from triage) | `StatusBanner` |
| ❤️ **Contactless vitals** | HR, RR, movement — red if out of range | `VitalsPanel` |
| ⏱️ **Drift gauge** | 0–1 drift score, semicircular gauge | `DriftGauge` |
| 📈 **7-day trajectory** | drift line + confidence band | `TrajectoryChart` |
| 📊 **SHAP attribution** | per-feature contribution bars | `ShapBars` |
| ✨ **AI assessment** | rationale, actions, **citations**, patient message | `AssessmentPanel` |

---

## 📊 10. Layer 6 — Observability

Every request, drift event, and Groq call is measured and visualised.

| Question | Prometheus metric | Type |
|----------|-------------------|------|
| How many requests came in? | `chronosense_http_requests_total` | Counter |
| How long did each request take? | `chronosense_http_request_duration_seconds` | Histogram |
| How many drift events fired? | `chronosense_drift_events_total` | Counter |
| How long did Groq take? | `chronosense_groq_request_duration_seconds` | Histogram |

**Grafana dashboard** (auto-provisioned, 5s live refresh): stat tiles, **line charts** (request
rate, latency p95, Groq latency), a **bar graph** (drift events by triage), and **alert panels**
(red when error-rate > 10% or Groq p95 > 10s). Prometheus alert rules fire in parallel.

---

## 🚀 11. Running the Whole Stack

### 🐳 Option A — Docker (one command, everything connected)

```bash
docker compose build          # first build is slow (torch + mpnet download)
docker compose up -d          # start mongo + api + frontend + prometheus + grafana

# one-time data seed:
docker compose exec api python -m backend.app.ingest
docker compose exec api python -m temporal_rag.build_patient_vitals
```

| Service | URL |
|---------|-----|
| 🩺 Dashboard | http://localhost:5173 |
| 🌐 API docs | http://localhost:8001/docs |
| 📈 Prometheus | http://localhost:9090 |
| 📊 Grafana | http://localhost:3000 (admin / admin) |

> See [DOCKER.md](DOCKER.md) for the full guide.

### 💻 Option B — Local (WSL2 + venv, CPU-only)

```bash
# 0. one-time: build vector store + seed Mongo
cd clinical_guidelines && python ingest_guidelines.py --rebuild && cd ..
python -m temporal_rag.build_patient_vitals

# 1. backend (WSL)
uvicorn temporal_rag.app:app --reload --port 8001

# 2. frontend (PowerShell / separate terminal)
cd frontend && npm run dev        # → http://localhost:5173
```

---

## 🔢 12. Key Numbers

| Metric | Value |
|--------|-------|
| Radar captures | **162** (2 subjects each → 324 readings) |
| Synthetic patients built | **46** (× 7 days = 322 readings) |
| Guideline chunks in ChromaDB | **2,700** |
| Embedding model | **all-mpnet-base-v2** (768-dim) |
| Cosine similarity (top chunk) | **~0.71** ⬆ from ~0.47 (MiniLM) |
| LLM | **LLaMA 3.3 70B** via Groq |
| Agents in chain | **3** |
| Drift feature weights | HR 0.45 · RR 0.35 · Move 0.20 |

---

## ✅ 13. Status & Roadmap

**Done**
- [x] Radar `.bin` parser (verified against dataset geometry)
- [x] Radar-only DSP — MTI → range-FFT → MVDR DOA → beamform → phase band-pass
- [x] Dual-subject detection + respiration/heartbeat per subject (162 captures)
- [x] Interpretable drift model with exact SHAP
- [x] Temporal RAG: 7-day trajectory → ChromaDB retrieval (mpnet, ~0.71) → 3 Groq agents
- [x] React clinician dashboard (live, per-patient)
- [x] Prometheus + Grafana observability (metrics, dashboards, alerts)
- [x] One-command Docker Compose stack

**Roadmap**
- [ ] Validate radar rates against the dataset's ECG/PCG references
- [ ] Federated learning + differential privacy (Flower · Opacus · ZenML)
- [ ] Blockchain trust layer (Hyperledger Fabric) — audit, consent, provenance
- [ ] Hybrid retrieval + cross-encoder re-ranking + OCR ingestion for scanned PDFs

<div align="center">

---

*ChronoSense — contactless sensing, interpretable AI, grounded clinical decisions.*

</div>
