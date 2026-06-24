"""A small WebSocket client that exercises the ChronoSense backend.

It connects to the server's /ws endpoint and runs a short demo:
  1. ping
  2. list a few radar captures (X)
  3. fetch one capture + its labels (X <-> Y pairing)

Usage (server must be running on :8000):
    python client/ws_client.py
    python client/ws_client.py --url ws://localhost:8000/ws
"""

from __future__ import annotations

import argparse
import asyncio
import json

import websockets


async def _request(ws, command: dict) -> dict:
    """Send one command and wait for a single reply."""
    await ws.send(json.dumps(command))
    reply = json.loads(await ws.recv())
    return reply


async def demo(url: str) -> None:
    async with websockets.connect(url) as ws:
        print(f"Connected to {url}\n")

        # 1. ping ------------------------------------------------------------
        print(">> ping")
        print("<<", await _request(ws, {"action": "ping"}), "\n")

        # 2. list captures ---------------------------------------------------
        print(">> list_captures (limit 3)")
        reply = await _request(ws, {"action": "list_captures", "limit": 3})
        captures = reply.get("data", [])
        for c in captures:
            print(f"   {c['source_file']}  npy={c['npy_path']}")
        print()

        if not captures:
            print("No captures in DB. Run the ingest script first.")
            return

        # 3. get one capture + its labels -----------------------------------
        radar_npy = captures[0]["npy_path"]
        print(f">> get_pair  radar_npy={radar_npy}")
        reply = await _request(ws, {"action": "get_pair", "radar_npy": radar_npy})
        pair = reply.get("data", {})
        labels = pair.get("labels", [])
        print(f"   radar duration: {pair['radar']['duration_s']}s")
        print(f"   labels paired : {len(labels)}")
        for lab in labels:
            print(f"     - {lab['source_file']} "
                  f"(mean HR {lab['hr_summary']['hr_mean_bpm']} bpm)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Demo WebSocket client for the backend.")
    ap.add_argument("--url", default="ws://localhost:8000/ws",
                    help="WebSocket URL (default: ws://localhost:8000/ws)")
    args = ap.parse_args()
    asyncio.run(demo(args.url))
