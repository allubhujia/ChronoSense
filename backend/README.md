# ChronoSense Backend

FastAPI + Pydantic + WebSocket service that serves the radar-only vital-sign
dataset from MongoDB.

Each document is one processed radar `.bin` capture holding **respiration and
heartbeat for up to two subjects** (produced by `digital_processing/`). MongoDB
is only the storage layer — this backend reads from it and serves the data over
HTTP and a WebSocket. It does **not** parse `.bin` files; the
`digital_processing/` scripts already did that.

## Folder layout

```
backend/
├── requirements.txt
├── .env.example          # copy to .env
├── app/
│   ├── config.py         # typed settings (Mongo URI, collection)
│   ├── database.py       # async Mongo client (Motor)
│   ├── schemas.py        # Pydantic models: capture documents + WebSocket messages
│   ├── crud.py           # DB query helpers
│   ├── ingest.py         # load the per-capture vital-sign JSONs into MongoDB
│   └── main.py           # FastAPI app: REST + WebSocket endpoints
└── client/
    └── ws_client.py      # demo WebSocket client
```

## Setup

```bash
# from the backend/ folder
pip install -r requirements.txt
cp .env.example .env          # then edit if your Mongo isn't on localhost:27017
```

You also need MongoDB running locally (or set `MONGO_URI` to a remote/Atlas URI).

## 1. Load the dataset into MongoDB (run once)

```bash
python -m app.ingest
```

This walks `Processed_Data/**/<stem>.json` and upserts each capture (162 total)
into the `captures` collection, then creates the indexes the server queries on.
Re-running it is safe (idempotent).

## 2. Start the server

```bash
uvicorn app.main:app --reload --port 8000
```

- REST: `http://localhost:8000/` , `/captures` , `/captures/{source_file}` , `/summary`
- Interactive API docs: `http://localhost:8000/docs`
- WebSocket: `ws://localhost:8000/ws`

## 3. Run the demo client

```bash
python client/ws_client.py
```

## WebSocket protocol

The client sends one JSON command per message (validated by the `WSCommand`
Pydantic model). The server replies with a `WSResponse` envelope
`{ "type": ..., "data": ..., "error": ... }`.

| `action`         | Required fields            | Server replies with                |
|------------------|----------------------------|------------------------------------|
| `ping`           | –                          | `type: pong`                       |
| `summary`        | –                          | `type: summary` (dataset stats)    |
| `list_captures`  | `limit`, `category` (opt.) | `type: captures`                   |
| `get_capture`    | `source_file`              | `type: capture` (both subjects)    |

### Example messages

```jsonc
// client -> server
{ "action": "get_capture", "source_file": "adc_2GHZ_position1_ (1).bin" }

// server -> server reply (abridged)
{
  "type": "capture",
  "data": {
    "source_file": "adc_2GHZ_position1_ (1).bin",
    "num_subjects_detected": 2,
    "subjects": [
      { "subject_index": 1,
        "respiration": { "breathing_rate_bpm": 17, "...": "..." },
        "heartbeat":   { "heart_rate_bpm": 67, "...": "..." } },
      { "subject_index": 2, "...": "..." }
    ]
  }
}
```
