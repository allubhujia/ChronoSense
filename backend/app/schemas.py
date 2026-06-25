"""Pydantic models (schemas).

Two groups:
  1. Document schemas  - mirror the per-capture vital-sign JSON written by
                         digital_processing/batch_process.py (radar-only
                         respiration + heartbeat for up to two subjects). They
                         validate what we read out of MongoDB before serving it.
  2. WebSocket schemas - the request the client sends and the envelope the
                         server replies with over the socket.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# 1. Document schemas (one processed radar .bin capture)
# ─────────────────────────────────────────────────────────────────────────────
class RadarConfig(BaseModel):
    start_freq_ghz: float
    adc_sample_rate_ksps: float
    adc_samples_per_chirp: int
    rx_antennas: int
    tx_antennas: int
    chirp_loops_per_frame: int
    frame_period_ms: float
    slowtime_fs_hz: float
    range_resolution_m: float


class Detection(BaseModel):
    """Where in the scene the subject was located (range bin + MVDR angle)."""

    range_bin: int
    range_m: float
    angle_deg: float


class Respiration(BaseModel):
    """The subject's breathing, extracted from the radar phase (0.1-0.6 Hz)."""

    breathing_rate_bpm: int
    peak_freq_hz: float
    band_hz: list[float]
    snr_db: float
    waveform_npz_key: str
    waveform_samples: list[float] = Field(default_factory=list)  # full bandpassed waveform (~1199 samples at 20 Hz)
    per_second_preview: list[float]     # 60-value per-second average for quick display


class Heartbeat(BaseModel):
    """The subject's heartbeat, extracted from the radar phase (0.9-2.0 Hz)."""

    heart_rate_bpm: int
    peak_freq_hz: float
    band_hz: list[float]
    snr_db: float
    waveform_npz_key: str
    waveform_samples: list[float] = Field(default_factory=list)  # full bandpassed waveform (~1199 samples at 20 Hz)
    per_second_preview: list[float]     # 60-value per-second average for quick display


class Subject(BaseModel):
    """One detected person: where they are + their two vital signs."""

    subject_index: int
    detection: Detection
    respiration: Respiration
    heartbeat: Heartbeat


class Capture(BaseModel):
    """One processed radar .bin capture, with both subjects' vital signs."""

    source_file: str
    category: str
    position: int | None = None
    test: int | None = None
    bandwidth_ghz: float
    bandwidth_token: str | None = None
    modality: str
    vital_signs: list[str]
    radar_config: RadarConfig
    frames: int
    duration_s: float
    num_subjects_detected: int
    subjects: list[Subject]
    npz_path: str
    json_path: str


# ─────────────────────────────────────────────────────────────────────────────
# 2. WebSocket message schemas
# ─────────────────────────────────────────────────────────────────────────────
WSAction = Literal[
    "ping",            # health check
    "list_captures",   # list captures (optionally filtered by category)
    "get_capture",     # one capture by its source_file
    "summary",         # dataset-wide vital-sign statistics
]


class WSCommand(BaseModel):
    """What the client sends over the socket. One typed request per message."""

    action: WSAction
    limit: int = Field(default=20, ge=1, le=500)

    # list_captures: optional category filter.
    category: str | None = None
    # get_capture: identify the capture by its source .bin file name.
    source_file: str | None = None


class WSResponse(BaseModel):
    """The envelope the server sends back. `type` tells the client what `data` is."""

    type: str
    data: Any | None = None
    error: str | None = None
