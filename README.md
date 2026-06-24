# ChronoSense

**Contactless vital-sign monitoring from FMCW radar.**
A pipeline that turns raw 60 GHz radar captures into model-ready inputs (**X**) and
extracts ground-truth heart rate from reference ECG/PCG signals (**Y**), then serves
the whole dataset through a FastAPI + WebSocket backend backed by MongoDB.

---

## 🧰 Tech Stack

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)
![NumPy](https://img.shields.io/badge/NumPy-013243?style=for-the-badge&logo=numpy&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=for-the-badge&logo=pydantic&logoColor=white)
![Uvicorn](https://img.shields.io/badge/Uvicorn-499848?style=for-the-badge&logo=uvicorn&logoColor=white)
![WebSockets](https://img.shields.io/badge/WebSockets-010101?style=for-the-badge&logo=socketdotio&logoColor=white)
![MongoDB](https://img.shields.io/badge/MongoDB-47A248?style=for-the-badge&logo=mongodb&logoColor=white)
![Motor](https://img.shields.io/badge/Motor%20%2F%20PyMongo-13AA52?style=for-the-badge&logo=mongodb&logoColor=white)
![Ubuntu](https://img.shields.io/badge/WSL2%20Ubuntu%2024.04-E95420?style=for-the-badge&logo=ubuntu&logoColor=white)
![Git](https://img.shields.io/badge/Git-F05032?style=for-the-badge&logo=git&logoColor=white)

| Layer | Technology | Used for |
|-------|-----------|----------|
| Signal processing | **Python · NumPy** | Parsing raw radar ADC `.bin`, decoding ECG/PCG, heart-rate extraction |
| API framework | **FastAPI** | REST + WebSocket server |
| Data validation | **Pydantic** | Typed schemas for documents and every WebSocket message |
| ASGI server | **Uvicorn** | Running the FastAPI app |
| Realtime transport | **WebSockets** | Server ↔ client channel (and future edge → backend ingest) |
| Database | **MongoDB** | Stores dataset metadata/catalog (queryable) |
| DB drivers | **Motor (async) · PyMongo (sync)** | App reads (async) and ingest writes (sync) |
| Runtime | **WSL2 Ubuntu 24.04** | CPU-only dev environment |

---

## 📡 What this project does

The dataset is *FMCW radar-based multi-person vital sign monitoring data*, captured with a
**TI IWR6843ISK (60 GHz)** radar + **DCA1000EVM** capture card. While a person sits in front
of the radar, two things are recorded simultaneously:

- **Radar `.bin`** — raw ADC samples. The chest moves with breathing (large) and heartbeats
  (tiny); the radar captures these micro-movements wirelessly. → **Input features (X)**
- **Log `.csv`** — reference **ECG** (electrical) and **PCG** (heart-sound) waveforms from
  body-worn sensors, recorded at the same time. → **Ground-truth labels (Y)**

The goal is supervised learning: feed the radar signal in, predict the vital signs, and use the
ECG-derived heart rate as the answer key.

```
   Radar (contactless)            Body sensors (reference)
   ┌────────────────┐             ┌────────────────────┐
   │  adc_*.bin (X) │             │  log_*.csv (ECG/PCG)│  (Y)
   └───────┬────────┘             └─────────┬──────────┘
           │ batch_process.py               │ log_process.py
           ▼                                 ▼
   .npy radar cube + .json          .npz (ecg,pcg,hr) + .json
   (1200,3,4,200)                   per-second heart rate
           │                                 │
           └──────────── index.json / log_index.json ───────────┐
                                                                 ▼
                                                    ingest.py → MongoDB
                                                                 ▼
                                              FastAPI + WebSocket backend
                                                                 ▼
                                                     client / edge device
```

---

## 📁 Repository structure

```
ChronoSense/
├── digital_processing/         # signal processing (X and Y generation)
│   ├── fmcw_bin_parser.py      # raw radar .bin → complex64 cube
│   ├── batch_process.py        # all radar .bin → .npy + .json + index.json
│   └── log_process.py          # all ECG/PCG .csv → .npz + .json + log_index.json
│
├── FMCW_dataset/               # (git-ignored — large) raw + processed data
│   ├── 1_AsymmetricalPosition/ # raw radar .bin + log .csv
│   ├── 2_SymmetricalPosition/  # (two people per capture: Target1 + Target2)
│   └── Processed_Data/
│       ├── index.json          # catalog of 162 radar captures
│       └── log_index.json      # catalog of 324 labels
│
├── backend/                    # FastAPI + Pydantic + WebSocket + MongoDB
│   ├── app/
│   │   ├── config.py           # typed settings (Mongo URI, collections)
│   │   ├── database.py         # async Mongo connection (Motor)
│   │   ├── schemas.py          # Pydantic models: documents + WS messages
│   │   ├── crud.py             # DB query helpers
│   │   ├── ingest.py           # load the two index JSONs into MongoDB
│   │   └── main.py             # FastAPI app: REST + WebSocket
│   ├── client/ws_client.py     # demo WebSocket client
│   ├── requirements.txt
│   └── .env.example
│
└── README.md
```

---

## 🔬 1. Digital processing

### Radar parser — `fmcw_bin_parser.py`
Decodes TI's DCA1000 2-lane complex layout (`[I0,I1,Q0,Q1] → 2 complex samples`), verified
against the file geometry:

```
1200 frames × 3 TX × 4 RX × 200 ADC samples × 2 (I+Q) × 2 bytes = 11,520,000 bytes ✓
```

`parse_bin()` returns a `complex64` cube of shape **(frames, chirps, rx, adc_samples)**, inferring
the frame count from the real file size so truncated captures degrade gracefully instead of crashing.

### Radar batch — `batch_process.py`
Walks every radar `.bin` and writes, per file:
- **`.npy`** — the full complex radar cube `(1200, 3, 4, 200)`
- **`.json`** — metadata + amplitude statistics
- plus a master **`index.json`** → **162 captures**

### Label extraction — `log_process.py`
For every ECG/PCG `.csv` (~125 Hz, 60 s):
1. Detects ECG **R-peaks** with a pure-NumPy Pan–Tompkins-style pipeline
   (baseline removal → derivative → squaring → moving-window integration → adaptive peak pick).
2. Converts R-R intervals into a **per-second heart-rate series**.
3. Writes per file:
   - **`.npz`** — three arrays: `ecg`, `pcg` (raw waveforms) and `hr_per_second` (the label)
   - **`.json`** — HR summary, signal stats, and the **matched radar `.npy`** (X↔Y link)
   - plus a master **`log_index.json`** → **324 labels**

> Note: both CSV channels are cardiac (ECG + PCG). Heart rate is the ground truth here;
> respiration is captured only on the radar side.

---

## 🗂️ 2. Data formats

| | Radar input (X) | Label (Y) |
|--|-----------------|-----------|
| Source | `adc_*.bin` | `log_*.csv` (ECG + PCG) |
| Array file | `.npy` cube `(1200,3,4,200)` | `.npz` → `ecg`, `pcg`, `hr_per_second` |
| Metadata | `.json` (config + stats) | `.json` (HR summary + stats) |
| Catalog | `index.json` (162) | `log_index.json` (324) |
| Link | — | `matched_radar_npy` → the paired radar `.npy` |

The big arrays stay on disk; MongoDB stores the JSON catalogs (with paths to the arrays).
One radar capture pairs with **two** labels in the symmetrical case (Target1 + Target2).

---

## 🚀 3. Backend (FastAPI + Pydantic + WebSocket + MongoDB)

The backend reads the dataset catalog from MongoDB and serves it over HTTP and a WebSocket.
It does **not** re-parse raw files — the processing scripts already did that.

**WebSocket actions** (`ws://localhost:8000/ws`) — each client message is validated by the
`WSCommand` Pydantic model; replies use a `WSResponse` envelope `{type, data, error}`:

| `action` | Returns |
|----------|---------|
| `ping` | `pong` |
| `list_captures` | radar captures (X) |
| `list_labels` | labels (Y) |
| `get_pair` | one radar capture **+ its labels** (X↔Y) |

> The same socket is the seam where a future **edge device pushes live data into the backend**.

---

## ⚙️ Setup & run

> Environment: Python runs via **WSL2 + venv** (CPU-only). Activate with
> `source .venv/bin/activate`.

**1. Generate the processed data** (radar + labels):
```bash
cd digital_processing
python batch_process.py     # → .npy/.json + index.json (162)
python log_process.py       # → .npz/.json + log_index.json (324)
```

**2. Start MongoDB** (installed once in WSL):
```bash
sudo systemctl start mongod
sudo systemctl status mongod      # expect "active (running)"
```

**3. Load the dataset into MongoDB:**
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env              # adjust MONGO_URI if needed
python -m app.ingest              # 162 radar + 324 labels (idempotent)
```

**4. Run the backend:**
```bash
uvicorn app.main:app --reload --port 8000
# REST docs:  http://localhost:8000/docs
# WebSocket:  ws://localhost:8000/ws
python client/ws_client.py        # demo client (separate terminal)
```

**Viewing the data:** connect MongoDB Compass / the VS Code extension to the database
(`mongodb://localhost:27017`, or the WSL IP from `hostname -I` if on localhost can't reach WSL)
and open the **`chronosense`** database → `radar_captures` + `labels`.

---

## ✅ Status

- [x] Radar `.bin` parser (verified against dataset geometry)
- [x] Radar batch processing → `.npy` + `.json` + `index.json` (162)
- [x] ECG/PCG heart-rate extraction → `.npz` + `.json` + `log_index.json` (324)
- [x] X↔Y pairing (robust to misspelled source filenames)
- [x] MongoDB ingestion (idempotent upserts + indexes)
- [x] FastAPI + Pydantic + WebSocket backend
- [ ] Edge → backend live ingest handler
- [ ] Vital-sign model (radar X → heart rate Y)
- [ ] Frontend dashboard client
```
