"""FastAPI application: REST + WebSocket for the ChronoSense vital-sign dataset.

Run it with:
    uvicorn app.main:app --reload --port 8000

The dataset must already be in MongoDB (see app/ingest.py). This server only
reads from Mongo and serves it; it does not parse radar `.bin` files itself.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from . import crud
from .database import close_mongo_connection, connect_to_mongo
from .schemas import Capture, WSCommand, WSResponse


# ── App lifespan: open/close Mongo with the server ──────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    yield
    await close_mongo_connection()


app = FastAPI(
    title="ChronoSense Backend",
    description="Serves radar-only respiration & heartbeat for two subjects per capture.",
    version="0.2.0",
    lifespan=lifespan,
)


# ── Plain REST endpoints (handy for quick checks in the browser/curl) ────────
@app.get("/")
async def root() -> dict:
    return {"service": "ChronoSense Backend", "status": "ok"}


# `response_model=...` makes FastAPI validate and serialise each response through
# the Pydantic schema. If a stored document doesn't match the schema, FastAPI
# raises a server-side validation error — so these routes also exercise Pydantic.
@app.get("/captures", response_model=list[Capture])
async def http_list_captures(limit: int = 20, category: str | None = None):
    return await crud.list_captures(limit, category)


@app.get("/captures/{source_file}", response_model=Capture)
async def http_get_capture(source_file: str):
    capture = await crud.get_capture(source_file)
    if capture is None:
        raise HTTPException(
            status_code=404,
            detail=f"No capture with source_file={source_file!r}",
        )
    return capture


@app.get("/summary")
async def http_summary() -> dict:
    return await crud.summary()


# ── WebSocket endpoint ──────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """One persistent connection; the client sends WSCommand JSON messages.

    Supported actions: ping, list_captures, get_capture, summary.
    Every reply is a WSResponse envelope: {type, data, error}.

    NOTE: this currently handles query traffic (backend -> client). A future
    edge device pushing live vital-sign data into the backend would add its own
    action/handler here.
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
        data = await crud.list_captures(cmd.limit, cmd.category)
        await _send(ws, WSResponse(type="captures", data=data))

    elif cmd.action == "get_capture":
        if not cmd.source_file:
            await _send(ws, WSResponse(type="error", error="get_capture needs 'source_file'"))
            return
        capture = await crud.get_capture(cmd.source_file)
        if capture is None:
            await _send(ws, WSResponse(type="error",
                                       error=f"unknown source_file: {cmd.source_file}"))
            return
        await _send(ws, WSResponse(type="capture", data=capture))

    elif cmd.action == "summary":
        await _send(ws, WSResponse(type="summary", data=await crud.summary()))


async def _send(ws: WebSocket, response: WSResponse) -> None:
    """Serialise a WSResponse to JSON and send it down the socket."""
    await ws.send_json(response.model_dump())
