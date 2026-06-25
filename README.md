# ChronoSense

**Contactless dual-subject vital-sign monitoring from FMCW radar.**
A pipeline that turns each raw 60 GHz radar `.bin` capture directly into the
**respiration and heartbeat** of the (up to two) people in front of the radar —
using only the radar signal. No body-worn sensors, no reference logs.

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
**TI IWR6843ISK (60 GHz)** radar + **DCA1000EVM** capture card. Two people sit in front of the
radar; their chests move with breathing (large, ~mm) and heartbeats (tiny, ~0.1 mm), and the
radar captures these micro-movements wirelessly in the raw `.bin` ADC samples.

This pipeline extracts each person's **respiration** and **heartbeat** straight from that radar
signal. The reference ECG/PCG `.csv` logs in the dataset are **not used** — the whole point is
contactless estimation.

```
   Radar (contactless, dual-subject)
   ┌─────────────────────┐
   │  adc_*.bin  (raw I/Q)│
   └──────────┬──────────┘
              │ batch_process.py → vital_signs.py
              ▼
   MTI + range-FFT → MVDR DOA → top-2 targets → beamform
              │
              ▼  phase → unwrap → diff → band-pass
   per subject:  respiration (0.1–0.6 Hz)   heartbeat (0.9–2.0 Hz)
              │
              ▼
   <stem>.json  (rates, geometry, SNR, previews)
   <stem>.npz   (full-resolution waveforms)
   vitals_index.json  (master summary of all captures)
```

The DSP is a NumPy port of the dataset authors' own MATLAB reference
(`FMCW_dataset/Code_for_Processing/`: `Main.m`, `MTI.m`, `IWR6843ISK_DOA.m`,
`get_heartBreath_rate.m`, `RR_BPF20.m`, `HR_BPF20.m`).

---

## 📁 Repository structure

```
ChronoSense/
├── digital_processing/         # radar-only vital-sign extraction
│   ├── fmcw_bin_parser.py      # raw radar .bin → complex64 cube
│   ├── vital_signs.py          # cube → per-subject respiration & heartbeat (the DSP)
│   └── batch_process.py        # all radar .bin → .json + .npz + vitals_index.json
│
├── FMCW_dataset/               # (git-ignored — large) raw + processed data
│   ├── 1_AsymmetricalPosition/ # raw radar .bin (two people per capture)
│   ├── 2_SymmetricalPosition/  # Target1 + Target2
│   ├── Code_for_Processing/    # the authors' reference MATLAB (ported here)
│   └── Processed_Data/
│       ├── <category>/position_*/<stem>.json   # per-capture vital signs
│       ├── <category>/position_*/<stem>.npz    # per-capture waveforms
│       └── vitals_index.json                   # master summary (162 captures)
│
├── backend/                    # legacy FastAPI + MongoDB browsing layer (not used
│                               #   by the radar-only pipeline; kept for reference)
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

### Vital-sign extraction — `vital_signs.py`
The core DSP. For one capture (slow-time rate = 1/50 ms = **20 Hz**, 60 s):
1. **Virtual array** — keep TX1 + TX3 → 8 virtual RX channels.
2. **MTI + range-FFT** — mean-cancel the slow-time DC/clutter, then 256-pt range-FFT.
3. **MVDR DOA** — per range bin, build the Capon range-angle spectrum.
4. **Find subjects** — greedily pick the **top-2** range-angle peaks (the two people),
   suppressing a neighbourhood so they're genuinely distinct.
5. **Beamform** — MVDR weights at each target's (range, angle) → one complex slow-time signal.
6. **Phase → vital signs** — `angle → unwrap → diff`, then band-pass into
   **respiration (0.1–0.6 Hz)** and **heartbeat (0.9–2.0 Hz)**; the FFT peak in each band gives
   the rate (×60 → per minute).

> Band-pass is a zero-phase FFT mask (no SciPy needed) standing in for the reference
> Butterworth filters; equivalent for in-band rate estimation.

### Radar batch — `batch_process.py`
Walks every radar `.bin` and writes, per file:
- **`.json`** — per-subject breathing & heart rate, detection geometry (range, angle), in-band
  SNR, and a per-second waveform preview.
- **`.npz`** — full-resolution waveforms: `subjectN_target_complex`, `subjectN_phase_unwrapped`,
  `subjectN_phase_diff`, `subjectN_respiration`, `subjectN_heartbeat`, plus `time_s`.
- plus a master **`vitals_index.json`** summarising all **162 captures**.

---

## 🗂️ 2. Data formats

Per capture, two files (heavy waveforms in the `.npz`, everything human-readable in the `.json`):

| | Per-capture JSON | Per-capture NPZ |
|--|------------------|------------------|
| Source | `adc_*.bin` (radar only) | `adc_*.bin` (radar only) |
| Holds | rates, range/angle, SNR, per-second previews | full-res waveforms per subject |
| Subjects | up to **2** (`subjects[]`) | `subject1_*`, `subject2_*` arrays |
| Catalog | — | — |

Master catalog: **`vitals_index.json`** (one entry per capture, with each subject's
breathing/heart rate and geometry). One capture yields **two** subjects (Target1 + Target2).

---

## ⚙️ Setup & run

> Environment: Python runs via **WSL2 + venv** (CPU-only, NumPy only — no SciPy).
> Activate with `source .venv/bin/activate`.

**Generate the vital-sign data** from every radar `.bin`:
```bash
cd digital_processing
python batch_process.py        # → <stem>.json + <stem>.npz + vitals_index.json (162)
```

**Inspect a single capture** (prints detected subjects and their rates):
```bash
python vital_signs.py "../FMCW_dataset/1_AsymmetricalPosition/1_Radar_Raw_Data/position_ (1)/adc_3GHZ_position1_ (1).bin"
```

Outputs land in `FMCW_dataset/Processed_Data/`, mirroring the dataset's
`<category>/position_*/` layout, plus a top-level `vitals_index.json` summary.

---

## 🚀 3. Backend (FastAPI + Pydantic + WebSocket + MongoDB)

The `backend/` folder serves the vital-sign captures from MongoDB over HTTP and a WebSocket.
It reads the per-capture JSONs (one document per `.bin`, both subjects' respiration + heartbeat)
— it does **not** re-parse radar files.

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # adjust MONGO_URI if needed
python -m app.ingest          # load Processed_Data/**/*.json → captures collection (162)
uvicorn app.main:app --reload --port 8000
python client/ws_client.py    # demo client (separate terminal)
```

**WebSocket actions** (`ws://localhost:8000/ws`) — each reply is a `WSResponse` `{type, data, error}`:

| `action` | Returns |
|----------|---------|
| `ping` | `pong` |
| `summary` | dataset-wide rate statistics |
| `list_captures` | captures (optional `category` filter) |
| `get_capture` | one capture by `source_file` (both subjects' vitals) |

REST mirrors this: `/captures`, `/captures/{source_file}`, `/summary`, and docs at `/docs`.

---

## ✅ Status

- [x] Radar `.bin` parser (verified against dataset geometry)
- [x] Radar-only vital-sign DSP — MTI → range-FFT → MVDR DOA → beamform → phase band-pass
- [x] Dual-subject detection (top-2 range-angle peaks)
- [x] Respiration (0.1–0.6 Hz) + heartbeat (0.9–2.0 Hz) per subject
- [x] Batch processing → `.json` + `.npz` + `vitals_index.json` (162 captures)
- [ ] Validate radar rates against the dataset's ECG/PCG references
- [ ] Vital-sign dashboard / live edge ingest
```
