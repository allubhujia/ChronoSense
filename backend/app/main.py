"""FastAPI application: REST + WebSocket for the ChronoSense dataset.

Run it with:
    uvicorn app.main:app --reload --port 8000

The dataset must already be in MongoDB (see app/ingest.py). This server only
reads from Mongo and serves it; it does not parse radar/CSV files itself.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from . import crud
from .database import close_mongo_connection, connect_to_mongo
from .schemas import Label, Pair, RadarCapture, WSCommand, WSResponse


# ── App lifespan: open/close Mongo with the server ──────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    yield
    await close_mongo_connection()


app = FastAPI(
    title="ChronoSense Backend",
    description="Serves FMCW radar captures (X) and ECG/PCG heart-rate labels (Y).",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Plain REST endpoints (handy for quick checks in the browser/curl) ────────
@app.get("/")
async def root() -> dict:
    return {"service": "ChronoSense Backend", "status": "ok"}


# `response_model=...` makes FastAPI validate and serialise each response through
# the Pydantic schema. If a stored document doesn't match the schema, FastAPI
# raises a server-side validation error — so these routes also exercise Pydantic.
@app.get("/captures", response_model=list[RadarCapture])
async def http_list_captures(limit: int = 20):
    return await crud.list_captures(limit)


@app.get("/labels", response_model=list[Label])
async def http_list_labels(limit: int = 20):
    return await crud.list_labels(limit)


@app.get("/pair", response_model=Pair)
async def http_get_pair(radar_npy: str):
    pair = await crud.get_pair(radar_npy)
    if pair is None:
        raise HTTPException(
            status_code=404,
            detail=f"No radar capture with npy_path={radar_npy!r}",
        )
    return pair


# ── WebSocket endpoint ──────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """One persistent connection; the client sends WSCommand JSON messages.

    Supported actions: ping, list_captures, list_labels, get_pair.
    Every reply is a WSResponse envelope: {type, data, error}.

    NOTE: this currently handles query traffic (backend -> client). The edge
    ingestion direction (edge device -> backend, pushing live radar/vital data
    to be validated and stored) will be added here as its own action/handler.
    """
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_json()

            # Validate the incoming message against our Pydantic command schema.
            try:
                cmd = WSCommand(**raw)
            except ValidationError as exc:
                await _send(ws, WSResponse(type="error", error=exc.errors().__str__()))
                continue

            await _dispatch(ws, cmd)
    except WebSocketDisconnect:
        # Client went away; nothing to clean up beyond letting the task end.
        return


async def _dispatch(ws: WebSocket, cmd: WSCommand) -> None:
    """Route one validated command to its handler."""
    if cmd.action == "ping":
        await _send(ws, WSResponse(type="pong", data={"ok": True}))

    elif cmd.action == "list_captures":
        data = await crud.list_captures(cmd.limit)
        await _send(ws, WSResponse(type="captures", data=data))

    elif cmd.action == "list_labels":
        data = await crud.list_labels(cmd.limit)
        await _send(ws, WSResponse(type="labels", data=data))

    elif cmd.action == "get_pair":
        if not cmd.radar_npy:
            await _send(ws, WSResponse(type="error", error="get_pair needs 'radar_npy'"))
            return
        pair = await crud.get_pair(cmd.radar_npy)
        if pair is None:
            await _send(ws, WSResponse(type="error",
                                       error=f"unknown radar_npy: {cmd.radar_npy}"))
            return
        await _send(ws, WSResponse(type="pair", data=pair))


async def _send(ws: WebSocket, response: WSResponse) -> None:
    """Serialise a WSResponse to JSON and send it down the socket."""
    await ws.send_json(response.model_dump())
