# ChronoSense Backend

FastAPI + Pydantic + WebSocket service that serves the processed FMCW dataset
from MongoDB.

- **X (input):** radar captures, from `Processed_Data/index.json`
- **Y (label):** ECG/PCG heart-rate labels, from `Processed_Data/log_index.json`

MongoDB is only the storage layer. This backend reads from it and serves the
data over HTTP and a WebSocket. It does **not** parse `.bin`/`.csv` files — the
`digital_processing/` scripts already did that.

## Folder layout

```
backend/
├── requirements.txt
├── .env.example          # copy to .env
├── app/
│   ├── config.py         # typed settings (Mongo URI, collections)
│   ├── database.py       # async Mongo client (Motor)
│   ├── schemas.py        # Pydantic models: documents + WebSocket messages
│   ├── crud.py           # DB query helpers
│   ├── ingest.py         # load the two index JSONs into MongoDB
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

This upserts 162 radar captures and 324 labels, and creates the indexes the
server queries on. Re-running it is safe (idempotent).

## 2. Start the server

```bash
uvicorn app.main:app --reload --port 8000
```

- REST: `http://localhost:8000/` , `/captures` , `/labels` , `/pair?radar_npy=...`
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

| `action`         | Required fields            | Server replies with            |
|------------------|----------------------------|--------------------------------|
| `ping`           | –                          | `type: pong`                   |
| `list_captures`  | `limit` (optional)         | `type: captures`               |
| `list_labels`    | `limit` (optional)         | `type: labels`                 |
| `get_pair`       | `radar_npy`                | `type: pair` (radar + labels)  |

> **Direction note.** These actions are query traffic (backend → client). The
> intended production use is the *opposite* direction — the **edge device pushes
> live radar/vital data into the backend** over this socket, to be validated
> (Pydantic) and stored. That ingest handler is the next piece to add; the
> `websocket_endpoint` in `app/main.py` marks where it goes.

### Example messages

```jsonc
// client -> server
{ "action": "get_pair", "radar_npy": "Processed_Data/1_AsymmetricalPosition/position_1/adc_2GHZ_position1_(1).npy" }

// server -> client
{ "type": "pair", "data": { "radar": { ... }, "labels": [ { ... }, { ... } ] } }
```
