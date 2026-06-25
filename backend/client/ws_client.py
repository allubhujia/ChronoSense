"""A small WebSocket client that exercises the ChronoSense backend.

It connects to the server's /ws endpoint and runs a short demo:
  1. ping
  2. dataset-wide vital-sign summary
  3. list a few captures
  4. fetch one capture and print both subjects' respiration + heartbeat

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

        # 2. dataset summary -------------------------------------------------
        print(">> summary")
        reply = await _request(ws, {"action": "summary"})
        s = reply.get("data", {})
        print(f"   captures: {s.get('total_captures')} | subjects: {s.get('total_subjects')}")
        print(f"   breathing/min: avg {s.get('avg_breathing_bpm')} "
              f"({s.get('min_breathing_bpm')}–{s.get('max_breathing_bpm')})")
        print(f"   heart/min    : avg {s.get('avg_heart_bpm')} "
              f"({s.get('min_heart_bpm')}–{s.get('max_heart_bpm')})\n")

        # 3. list captures ---------------------------------------------------
        print(">> list_captures (limit 3)")
        reply = await _request(ws, {"action": "list_captures", "limit": 3})
        captures = reply.get("data", [])
        for c in captures:
            print(f"   {c['source_file']}  ({c['num_subjects_detected']} subjects)")
        print()

        if not captures:
            print("No captures in DB. Run the ingest script first.")
            return

        # 4. get one capture + print its vital signs -------------------------
        source_file = captures[0]["source_file"]
        print(f">> get_capture  source_file={source_file}")
        reply = await _request(ws, {"action": "get_capture", "source_file": source_file})
        capture = reply.get("data", {})
        print(f"   duration: {capture['duration_s']}s | "
              f"bandwidth: {capture['bandwidth_ghz']} GHz")
        for subj in capture.get("subjects", []):
            det = subj["detection"]
            br = subj["respiration"]["breathing_rate_bpm"]
            hr = subj["heartbeat"]["heart_rate_bpm"]
            print(f"     - subject {subj['subject_index']} "
                  f"@ {det['range_m']}m / {det['angle_deg']}°: "
                  f"breathing {br}/min, heart {hr}/min")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Demo WebSocket client for the backend.")
    ap.add_argument("--url", default="ws://localhost:8000/ws",
                    help="WebSocket URL (default: ws://localhost:8000/ws)")
    args = ap.parse_args()
    asyncio.run(demo(args.url))
