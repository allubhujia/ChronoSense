"""
Batch radar-only vital-sign processing for the ChronoSense FMCW dataset.

Walks every radar `.bin` file (both AsymmetricalPosition and SymmetricalPosition)
and, using **only the radar signal**, extracts each person's respiration and
heartbeat (see vital_signs.py for the DSP). For every capture it writes:

  - <stem>.json  - the vital signs: per-subject breathing/heart rate, detection
                   geometry (range, angle), in-band SNR, and a per-second
                   waveform preview. This is the primary, human/LLM-readable
                   output.
  - <stem>.npz   - the full-resolution waveforms (complex beamformed signal,
                   unwrapped phase, respiration & heartbeat waveforms) for any
                   later modelling.

Plus a master vitals_index.json summarising every capture's rates.

The reference ECG/PCG `.csv` logs are intentionally ignored - this pipeline is
purely contactless (radar in, vital signs out).

Usage (from digital_processing/):
    python batch_process.py
    python batch_process.py --dataset-root ../FMCW_dataset
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from fmcw_bin_parser import RadarParams, parse_filename  # noqa: E402
from vital_signs import CaptureVitals, SubjectVitals, extract_vitals  # noqa: E402

_DEFAULT_DATASET_ROOT = _SCRIPT_DIR.parent / "FMCW_dataset"
_OUTPUT_DIR_NAME = "Processed_Data"
_CATEGORY_DIRS = ["1_AsymmetricalPosition", "2_SymmetricalPosition"]
_RADAR_SUBDIR = "1_Radar_Raw_Data"


# ── Discovery / paths ───────────────────────────────────────────────────────
def _discover_bin_files(dataset_root: Path) -> list[Path]:
    bin_files: list[Path] = []
    for category in _CATEGORY_DIRS:
        radar_dir = dataset_root / category / _RADAR_SUBDIR
        if not radar_dir.is_dir():
            print(f"[WARN] Radar directory not found, skipping: {radar_dir}")
            continue
        for position_dir in sorted(radar_dir.iterdir()):
            if position_dir.is_dir():
                bin_files.extend(sorted(position_dir.glob("*.bin")))
    return bin_files


def _category_dir_for(bin_path: Path) -> str:
    for cat in _CATEGORY_DIRS:
        if any(cat.lower() == p.lower() for p in bin_path.parts):
            return cat
    return "Unknown"


def _infer_category(bin_path: Path) -> str:
    parts_lower = [p.lower() for p in bin_path.parts]
    for part in parts_lower:
        if "asymmetrical" in part:
            return "AsymmetricalPosition"
        if "symmetrical" in part:
            return "SymmetricalPosition"
    return "Unknown"


def _infer_position_number(bin_path: Path) -> int | None:
    import re
    m = re.search(r"\((\d+)\)", bin_path.parent.name)
    return int(m.group(1)) if m else None


def _output_base(dataset_root: Path, bin_path: Path) -> Path:
    category_dir = _category_dir_for(bin_path)
    pos_num = _infer_position_number(bin_path)
    pos_folder = f"position_{pos_num}" if pos_num else bin_path.parent.name
    clean_stem = bin_path.stem.replace(" ", "")
    return dataset_root / _OUTPUT_DIR_NAME / category_dir / pos_folder / clean_stem


# ── Output building ─────────────────────────────────────────────────────────
def _per_second_preview(wave: np.ndarray, fs: float) -> list[float]:
    """Average a slow-time waveform into one value per second for the JSON."""
    n_secs = max(1, int(round(len(wave) / fs)))
    samples_per_sec = max(1, int(round(fs)))
    out: list[float] = []
    for s in range(n_secs):
        seg = wave[s * samples_per_sec:(s + 1) * samples_per_sec]
        out.append(round(float(seg.mean()), 5) if seg.size else 0.0)
    return out


def _subject_json(s: SubjectVitals, fs: float) -> dict:
    return {
        "subject_index": s.subject_index,
        "detection": {
            "range_bin": s.range_bin,
            "range_m": s.range_m,
            "angle_deg": s.angle_deg,
        },
        "respiration": {
            "breathing_rate_bpm": s.breathing_rate_bpm,
            "peak_freq_hz": s.resp_peak_hz,
            "band_hz": [0.1, 0.6],
            "snr_db": s.resp_snr_db,
            "waveform_npz_key": f"subject{s.subject_index}_respiration",
            "waveform_samples": [round(float(v), 5) for v in s.respiration_wave],
            "per_second_preview": _per_second_preview(s.respiration_wave, fs),
        },
        "heartbeat": {
            "heart_rate_bpm": s.heart_rate_bpm,
            "peak_freq_hz": s.heart_peak_hz,
            "band_hz": [0.9, 2.0],
            "snr_db": s.heart_snr_db,
            "waveform_npz_key": f"subject{s.subject_index}_heartbeat",
            "waveform_samples": [round(float(v), 5) for v in s.heartbeat_wave],
            "per_second_preview": _per_second_preview(s.heartbeat_wave, fs),
        },
    }


def _build_json(bin_path: Path, vitals: CaptureVitals, params: RadarParams,
                npz_rel: str, json_rel: str) -> dict:
    info = parse_filename(bin_path)
    return {
        "source_file": bin_path.name,
        "category": _infer_category(bin_path),
        "position": _infer_position_number(bin_path),
        "test": info.test if info else None,
        "bandwidth_ghz": round(vitals.bandwidth_hz / 1e9, 4),
        "bandwidth_token": info.bandwidth_token if info else None,
        "modality": "radar_only",
        "vital_signs": ["respiration", "heartbeat"],
        "radar_config": {
            "start_freq_ghz": params.start_freq / 1e9,
            "adc_sample_rate_ksps": params.adc_sample_rate / 1e3,
            "adc_samples_per_chirp": params.num_adc_samples,
            "rx_antennas": params.num_rx,
            "tx_antennas": params.num_tx,
            "chirp_loops_per_frame": params.chirp_loops,
            "frame_period_ms": params.frame_period * 1e3,
            "slowtime_fs_hz": vitals.slowtime_fs_hz,
            "range_resolution_m": vitals.range_resolution_m,
        },
        "frames": vitals.frames,
        "duration_s": vitals.duration_s,
        "num_subjects_detected": len(vitals.subjects),
        "subjects": [_subject_json(s, vitals.slowtime_fs_hz) for s in vitals.subjects],
        "npz_path": npz_rel,
        "json_path": json_rel,
    }


def _save_npz(npz_path: Path, vitals: CaptureVitals) -> None:
    arrays: dict[str, np.ndarray] = {"time_s": vitals.time_s}
    for s in vitals.subjects:
        p = f"subject{s.subject_index}"
        arrays[f"{p}_target_complex"] = s.target_complex
        arrays[f"{p}_phase_unwrapped"] = s.phase_unwrapped
        arrays[f"{p}_phase_diff"] = s.phase_diff
        arrays[f"{p}_respiration"] = s.respiration_wave
        arrays[f"{p}_heartbeat"] = s.heartbeat_wave
    np.savez_compressed(npz_path, **arrays)


# ── Driver ──────────────────────────────────────────────────────────────────
def process_all(dataset_root: Path | None = None, params: RadarParams | None = None) -> list[dict]:
    dataset_root = Path(dataset_root or _DEFAULT_DATASET_ROOT).resolve()
    params = params or RadarParams()

    print(f"Dataset root: {dataset_root}")
    print(f"Output dir:   {dataset_root / _OUTPUT_DIR_NAME}\n")

    bin_files = _discover_bin_files(dataset_root)
    total = len(bin_files)
    print(f"Found {total} .bin files to process.\n")
    if total == 0:
        print("[ERROR] No .bin files found. Check the dataset_root path.")
        return []

    summaries: list[dict] = []
    processed = skipped = 0

    for i, bin_path in enumerate(bin_files, 1):
        rel = bin_path.relative_to(dataset_root)
        print(f"[{i}/{total}] {rel}")
        t0 = time.time()
        try:
            vitals = extract_vitals(bin_path, params)
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR] {e}")
            skipped += 1
            continue

        out_base = _output_base(dataset_root, bin_path)
        out_base.parent.mkdir(parents=True, exist_ok=True)
        npz_path = out_base.with_suffix(".npz")
        json_path = out_base.with_suffix(".json")

        _save_npz(npz_path, vitals)
        summary = _build_json(
            bin_path, vitals, params,
            str(npz_path.relative_to(dataset_root)),
            str(json_path.relative_to(dataset_root)),
        )
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        summaries.append(summary)
        processed += 1
        rates = " ; ".join(
            f"S{s['subject_index']}: br {s['respiration']['breathing_rate_bpm']}/min, "
            f"hr {s['heartbeat']['heart_rate_bpm']}/min"
            for s in summary["subjects"]
        )
        print(f"  -> {summary['num_subjects_detected']} subject(s) | {rates} "
              f"| {time.time() - t0:.2f}s")

    # ── Master index (rates only; the heavy data stays in the per-file files) ─
    index = {
        "dataset": "ChronoSense FMCW Radar - radar-only vital signs",
        "modality": "radar_only",
        "vital_signs": ["respiration", "heartbeat"],
        "slowtime_fs_hz": 1.0 / params.frame_period,
        "total_files_processed": processed,
        "total_files_skipped": skipped,
        "total_files_found": total,
        "categories": _CATEGORY_DIRS,
        "files": [
            {
                "source_file": s["source_file"],
                "category": s["category"],
                "position": s["position"],
                "test": s["test"],
                "bandwidth_ghz": s["bandwidth_ghz"],
                "json_path": s["json_path"],
                "num_subjects_detected": s["num_subjects_detected"],
                "subjects": [
                    {
                        "subject_index": subj["subject_index"],
                        "range_m": subj["detection"]["range_m"],
                        "angle_deg": subj["detection"]["angle_deg"],
                        "breathing_rate_bpm": subj["respiration"]["breathing_rate_bpm"],
                        "heart_rate_bpm": subj["heartbeat"]["heart_rate_bpm"],
                    }
                    for subj in s["subjects"]
                ],
            }
            for s in summaries
        ],
    }
    index_path = dataset_root / _OUTPUT_DIR_NAME / "vitals_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f"DONE: processed {processed}/{total} ({skipped} skipped)")
    print(f"Master index: {index_path}")
    print(f"{'=' * 60}")
    return summaries


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Extract radar-only respiration & heartbeat from all ChronoSense .bin files."
    )
    ap.add_argument("--dataset-root", type=Path, default=_DEFAULT_DATASET_ROOT,
                    help="Root of the FMCW_dataset directory.")
    args = ap.parse_args()
    process_all(dataset_root=args.dataset_root)
