"""Pydantic models (schemas).

Two groups:
  1. Document schemas  - mirror the JSON written by the processing pipeline
                         (radar index.json and log_index.json). They validate
                         what we read out of MongoDB before sending it on.
  2. WebSocket schemas - the request the client sends and the envelope the
                         server replies with over the socket.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# 1. Document schemas (radar capture = X, label = Y)
# ─────────────────────────────────────────────────────────────────────────────
class RadarConfig(BaseModel):
    start_freq_ghz: float
    adc_sample_rate_ksps: float
    adc_samples_per_chirp: int
    rx_antennas: int
    tx_antennas: int
    chirp_loops_per_frame: int
    frame_period_ms: float


class RadarStatistics(BaseModel):
    amplitude_mean: float
    amplitude_std: float
    amplitude_min: float
    amplitude_max: float
    per_frame_amplitude_mean: list[float]
    per_rx_amplitude_mean: list[float]
    per_chirp_amplitude_mean: list[float]
    first_5_samples_real: list[float]
    first_5_samples_imag: list[float]


class RadarCapture(BaseModel):
    """One processed radar .bin capture (the model input, X)."""

    source_file: str
    category: str
    position: int
    test: int
    bandwidth_ghz: float | None = None
    bandwidth_token: str | None = None
    npy_path: str
    json_path: str | None = None
    radar_config: RadarConfig
    cube_shape: list[int]
    cube_shape_labels: list[str]
    frames: int
    duration_s: float
    statistics: RadarStatistics


class LogConfig(BaseModel):
    sampling_rate_hz: float
    channels: list[str]
    n_samples: int
    duration_s: float


class ArraySpec(BaseModel):
    shape: list[int]
    dtype: str
    sampling_rate_hz: float
    units: str
    derived_from: str | None = None


class HRSummary(BaseModel):
    hr_mean_bpm: float | None = None
    hr_std_bpm: float | None = None
    hr_min_bpm: float | None = None
    hr_max_bpm: float | None = None


class Label(BaseModel):
    """One processed ECG/PCG log = the ground-truth label, Y."""

    source_file: str
    category: str
    position: int
    test: int
    target: int
    bandwidth_ghz: float | None = None
    bandwidth_token: str | None = None
    role: str
    label_npz_path: str
    label_json_path: str
    matched_radar_npy: str
    matched_radar_resolved: bool
    log_config: LogConfig
    arrays: dict[str, ArraySpec]
    num_beats_detected: int
    hr_summary: HRSummary
    hr_per_second_bpm: list[float | None]
    ecg_stats: dict[str, float]
    pcg_stats: dict[str, float]


class Pair(BaseModel):
    """A radar capture (X) together with every label (Y) recorded for it."""

    radar: RadarCapture
    labels: list[Label]


# ─────────────────────────────────────────────────────────────────────────────
# 2. WebSocket message schemas
# ─────────────────────────────────────────────────────────────────────────────
WSAction = Literal[
    "ping",            # health check
    "list_captures",   # list radar captures (X)
    "list_labels",     # list labels (Y)
    "get_pair",        # one radar capture + its labels (X <-> Y)
]


class WSCommand(BaseModel):
    """What the client sends over the socket. One typed request per message."""

    action: WSAction
    limit: int = Field(default=20, ge=1, le=500)

    # get_pair: identify the radar capture by its .npy path.
    radar_npy: str | None = None


class WSResponse(BaseModel):
    """The envelope the server sends back. `type` tells the client what `data` is."""

    type: str
    data: Any | None = None
    error: str | None = None
