"""
Batch processor for the ChronoSense FMCW radar dataset.

Walks through every .bin file in both 1_AsymmetricalPosition and
2_SymmetricalPosition, parses the raw ADC data, and saves:
  - A .npy file with the full complex64 radar cube (frames, chirps, rx, samples)
  - A .json file with metadata and statistical summaries for LLM/RAG consumption

Also generates a master index.json that catalogs all processed files.

Usage:
    python batch_process.py
    python batch_process.py --dataset-root ../FMCW_dataset
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

# ── Resolve imports ────────────────────────────────────────────────────────
# Allow running this script directly from the digital_processing/ folder.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from fmcw_bin_parser import RadarParams, parse_bin, parse_filename  # noqa: E402


# ── Constants ──────────────────────────────────────────────────────────────
_DEFAULT_DATASET_ROOT = _SCRIPT_DIR.parent / "FMCW_dataset"
_OUTPUT_DIR_NAME = "Processed_Data"

_CATEGORY_DIRS = [
    "1_AsymmetricalPosition",
    "2_SymmetricalPosition",
]

# Sub-folder within each category that holds the raw radar .bin files.
_RADAR_SUBDIR = "1_Radar_Raw_Data"


def _discover_bin_files(dataset_root: Path) -> list[Path]:
    """Find every .bin file across all position folders in the dataset.

    Returns a sorted list of absolute paths to .bin files.
    """
    bin_files: list[Path] = []
    for category in _CATEGORY_DIRS:
        radar_dir = dataset_root / category / _RADAR_SUBDIR
        if not radar_dir.is_dir():
            print(f"[WARN] Radar directory not found, skipping: {radar_dir}")
            continue
        # Each position is a sub-folder like "position_ (1)"
        for position_dir in sorted(radar_dir.iterdir()):
            if not position_dir.is_dir():
                continue
            # Grab every .bin file regardless of exact naming
            for bin_file in sorted(position_dir.glob("*.bin")):
                bin_files.append(bin_file)
    return bin_files


def _infer_category(bin_path: Path) -> str:
    """Determine whether a .bin file belongs to Asymmetrical or Symmetrical."""
    parts_lower = [p.lower() for p in bin_path.parts]
    for part in parts_lower:
        if "asymmetrical" in part:
            return "AsymmetricalPosition"
        if "symmetrical" in part:
            return "SymmetricalPosition"
    return "Unknown"


def _infer_position_number(bin_path: Path) -> int | None:
    """Extract the position number from the parent folder name, e.g. 'position_ (3)' -> 3."""
    folder_name = bin_path.parent.name  # e.g. "position_ (3)"
    import re
    m = re.search(r"\((\d+)\)", folder_name)
    return int(m.group(1)) if m else None


def _build_output_path(dataset_root: Path, bin_path: Path) -> Path:
    """Build the output path mirroring the source structure under Processed_Data/.

    Example:
        Input:  .../FMCW_dataset/1_AsymmetricalPosition/1_Radar_Raw_Data/position_ (1)/adc_2GHZ_position1_ (1).bin
        Output: .../FMCW_dataset/Processed_Data/1_AsymmetricalPosition/position_1/adc_2GHZ_position1_(1)
    """
    # Determine category folder
    category = None
    for cat in _CATEGORY_DIRS:
        if cat in bin_path.parts or cat in str(bin_path):
            category = cat
            break
    category = category or "Unknown"

    # Determine position number
    pos_num = _infer_position_number(bin_path)
    pos_folder = f"position_{pos_num}" if pos_num else bin_path.parent.name

    # Clean up the filename: remove spaces for cleaner paths
    clean_stem = bin_path.stem.replace(" ", "")

    output_dir = dataset_root / _OUTPUT_DIR_NAME / category / pos_folder
    return output_dir / clean_stem


def _compute_statistics(cube: np.ndarray, params: RadarParams) -> dict:
    """Compute summary statistics from the radar cube for the JSON summary.

    These statistics give the LLM/RAG system a quick overview of the signal
    characteristics without needing to load the full array.
    """
    amplitudes = np.abs(cube)

    # Per-frame mean amplitude (useful for spotting movement/breathing patterns)
    # Shape: (frames,) — averaged over chirps, rx, and samples
    per_frame_amp = amplitudes.mean(axis=(1, 2, 3))

    # Per-RX antenna mean amplitude (useful for checking antenna health)
    # Shape: (num_rx,)
    per_rx_amp = amplitudes.mean(axis=(0, 1, 3))

    # Per-chirp (TX) mean amplitude
    # Shape: (chirps_per_frame,)
    per_chirp_amp = amplitudes.mean(axis=(0, 2, 3))

    return {
        "amplitude_mean": float(amplitudes.mean()),
        "amplitude_std": float(amplitudes.std()),
        "amplitude_min": float(amplitudes.min()),
        "amplitude_max": float(amplitudes.max()),
        "per_frame_amplitude_mean": per_frame_amp.tolist(),
        "per_rx_amplitude_mean": per_rx_amp.tolist(),
        "per_chirp_amplitude_mean": per_chirp_amp.tolist(),
        "first_5_samples_real": cube[0, 0, 0, :5].real.tolist(),
        "first_5_samples_imag": cube[0, 0, 0, :5].imag.tolist(),
    }


def _build_json_summary(
    bin_path: Path,
    npy_rel_path: str,
    cube: np.ndarray,
    params: RadarParams,
) -> dict:
    """Build the full JSON summary dict for one processed file."""
    file_info = parse_filename(bin_path)
    pos_num = _infer_position_number(bin_path)
    category = _infer_category(bin_path)

    n_frames = cube.shape[0]
    duration_s = n_frames * params.frame_period

    summary = {
        "source_file": bin_path.name,
        "category": category,
        "position": pos_num or (file_info.position if file_info else None),
        "test": file_info.test if file_info else None,
        "bandwidth_ghz": file_info.bandwidth_hz / 1e9 if file_info else None,
        "bandwidth_token": file_info.bandwidth_token if file_info else None,
        "npy_path": npy_rel_path,
        "radar_config": {
            "start_freq_ghz": params.start_freq / 1e9,
            "adc_sample_rate_ksps": params.adc_sample_rate / 1e3,
            "adc_samples_per_chirp": params.num_adc_samples,
            "rx_antennas": params.num_rx,
            "tx_antennas": params.num_tx,
            "chirp_loops_per_frame": params.chirp_loops,
            "frame_period_ms": params.frame_period * 1e3,
        },
        "cube_shape": list(cube.shape),
        "cube_shape_labels": ["frames", "chirps_per_frame", "rx_antennas", "adc_samples"],
        "frames": n_frames,
        "duration_s": round(duration_s, 2),
        "statistics": _compute_statistics(cube, params),
    }
    return summary


def process_all(
    dataset_root: Path | None = None,
    params: RadarParams | None = None,
) -> list[dict]:
    """Discover and process every .bin file in the dataset.

    Returns a list of JSON summary dicts (one per file), and saves:
      - .npy files (radar cubes)
      - .json files (per-file metadata/summaries)
      - index.json (master catalog)
    """
    dataset_root = Path(dataset_root or _DEFAULT_DATASET_ROOT).resolve()
    params = params or RadarParams()

    print(f"Dataset root: {dataset_root}")
    print(f"Output dir:   {dataset_root / _OUTPUT_DIR_NAME}")
    print()

    bin_files = _discover_bin_files(dataset_root)
    total = len(bin_files)
    print(f"Found {total} .bin files to process.\n")

    if total == 0:
        print("[ERROR] No .bin files found. Check the dataset_root path.")
        return []

    all_summaries: list[dict] = []
    processed = 0
    skipped = 0

    for i, bin_path in enumerate(bin_files, 1):
        rel = bin_path.relative_to(dataset_root)
        print(f"[{i}/{total}] Processing: {rel}")

        t0 = time.time()
        try:
            cube = parse_bin(bin_path, params)
        except Exception as e:
            print(f"  [ERROR] Failed to parse: {e}")
            skipped += 1
            continue

        # Build output paths
        out_base = _build_output_path(dataset_root, bin_path)
        npy_path = out_base.with_suffix(".npy")
        json_path = out_base.with_suffix(".json")

        # Ensure output directory exists
        npy_path.parent.mkdir(parents=True, exist_ok=True)

        # Save the radar cube as .npy
        np.save(npy_path, cube)

        # Build and save the JSON summary
        npy_rel = str(npy_path.relative_to(dataset_root))
        summary = _build_json_summary(bin_path, npy_rel, cube, params)
        summary["json_path"] = str(json_path.relative_to(dataset_root))

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        all_summaries.append(summary)
        processed += 1

        elapsed = time.time() - t0
        print(f"  -> Cube shape: {cube.shape} | Duration: {summary['duration_s']}s | Saved in {elapsed:.1f}s")

    # ── Write master index.json ────────────────────────────────────────────
    index_path = dataset_root / _OUTPUT_DIR_NAME / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)

    index_data = {
        "dataset": "ChronoSense FMCW Radar",
        "total_files_processed": processed,
        "total_files_skipped": skipped,
        "total_files_found": total,
        "categories": _CATEGORY_DIRS,
        "files": all_summaries,
    }
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f"DONE: Processed {processed}/{total} files ({skipped} skipped)")
    print(f"Master index: {index_path}")
    print(f"{'=' * 60}")

    return all_summaries


# ── CLI entry point ───────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Batch-process all ChronoSense FMCW radar .bin files."
    )
    ap.add_argument(
        "--dataset-root",
        type=Path,
        default=_DEFAULT_DATASET_ROOT,
        help="Root of the FMCW_dataset directory (default: ../FMCW_dataset relative to this script).",
    )
    args = ap.parse_args()

    process_all(dataset_root=args.dataset_root)
