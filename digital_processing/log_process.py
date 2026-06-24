"""
Ground-truth label processor for the ChronoSense FMCW radar dataset.

The dataset ships a reference "Log data" CSV for every radar capture. Each CSV
holds two raw biosignal columns sampled synchronously with the radar::

    ECG   - electrocardiogram (electrical, used here to derive heart rate)
    PCG   - phonocardiogram  (heart sound, kept as an auxiliary channel)

These waveforms are the *answer key* (Y) for supervised vital-sign models: the
radar .bin captures (X) are matched against the heart rate extracted from the
ECG here. Note both CSV channels are cardiac - there is **no** respiration
channel in the logs, so respiration ground truth is not produced from them.

What this script does, for every CSV under both position categories:
  - Parses the two-column ECG/PCG waveform.
  - Detects ECG R-peaks with a pure-numpy Pan-Tompkins-style pipeline
    (band-emphasis via derivative -> square -> moving-window integration,
    then an adaptive, refractory-constrained peak pick). No scipy required.
  - Converts R-R intervals into an instantaneous heart-rate series and
    resamples it onto a 1 Hz per-second grid spanning the capture.
  - Saves:
      * <stem>.npz  - three float32 arrays bundled together:
                        ecg            raw ECG waveform        (n_samples,)
                        pcg            raw PCG waveform         (n_samples,)
                        hr_per_second  derived heart rate (bpm) (secs,)
                      Both raw signals are preserved so PCG (heart sound) is not
                      lost; hr_per_second is the primary ECG-derived label.
      * <stem>.json - metadata + HR summary + waveform stats, in the SAME
                      style as batch_process.py's radar summaries, and crucially
                      the matched radar .npy path so X<->Y pairing is explicit.
  - Writes a master log_index.json cataloguing every processed label file.

Sampling rate: the logs run at ~125 Hz (7501 samples over the 60 s capture).
Override with --fs if a future capture differs.

Usage:
    python log_process.py
    python log_process.py --dataset-root ../FMCW_dataset --fs 125
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

# ── Constants ──────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_DATASET_ROOT = _SCRIPT_DIR.parent / "FMCW_dataset"
_OUTPUT_DIR_NAME = "Processed_Data"

_CATEGORY_DIRS = [
    "1_AsymmetricalPosition",
    "2_SymmetricalPosition",
]
_LOG_SUBDIR = "2_Log_data"

# Default ECG/PCG sampling rate: 7501 samples / 60 s capture ~= 125 Hz.
_DEFAULT_LOG_FS = 125.0

# Physiologically plausible heart-rate window (bpm). R-R intervals implying a
# rate outside this band are treated as detection artefacts and discarded.
_HR_MIN_BPM = 30.0
_HR_MAX_BPM = 200.0

_BANDWIDTH_HZ = {"2GHZ": 2.0e9, "2_5GHZ": 2.5e9, "3GHZ": 3.0e9}


# ── File-name / path decoding ──────────────────────────────────────────────
def parse_log_filename(path: str | Path) -> dict | None:
    """Decode ``log_Target<T>_<BW>_position<P>_ (<N>).csv`` into metadata.

    Returns ``None`` if the name does not match the dataset convention.
    """
    name = Path(path).name
    m = re.match(
        r"log_Target(?P<target>\d+)_(?P<bw>2GHZ|2_5GHZ|3GHZ)_positi?on(?P<pos>\d+)_\s*\((?P<test>\d+)\)\.csv",
        name,
        re.IGNORECASE,
    )
    if m is None:
        return None
    bw_token = m.group("bw").upper()
    return {
        "target": int(m.group("target")),
        "bandwidth_token": bw_token,
        "bandwidth_hz": _BANDWIDTH_HZ.get(bw_token, float("nan")),
        "position": int(m.group("pos")),
        "test": int(m.group("test")),
    }


def _infer_category(path: Path) -> str:
    parts_lower = [p.lower() for p in path.parts]
    for part in parts_lower:
        if "asymmetrical" in part:
            return "AsymmetricalPosition"
        if "symmetrical" in part:
            return "SymmetricalPosition"
    return "Unknown"


def _category_dir_for(path: Path) -> str:
    for cat in _CATEGORY_DIRS:
        if any(cat.lower() == p.lower() for p in path.parts):
            return cat
    return "Unknown"


def load_radar_index(dataset_root: Path) -> dict[tuple, str]:
    """Build a lookup of processed radar cubes keyed by capture identity.

    Reads ``Processed_Data/index.json`` (written by batch_process.py) and maps
    ``(category, position, bandwidth_token, test) -> npy_path``. Using the real
    recorded paths is mismatch-proof: some raw .bin files in the dataset are
    misspelled (e.g. ``positon7``), and the radar processor preserves that
    spelling, so a reconstructed template name would not exist on disk.
    """
    index_path = dataset_root / _OUTPUT_DIR_NAME / "index.json"
    if not index_path.is_file():
        print(f"[WARN] Radar index not found ({index_path}); "
              f"falling back to template-based radar pairing.")
        return {}
    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)
    lookup: dict[tuple, str] = {}
    for entry in index.get("files", []):
        key = (entry.get("category"), entry.get("position"),
               entry.get("bandwidth_token"), entry.get("test"))
        if entry.get("npy_path"):
            lookup[key] = entry["npy_path"]
    return lookup


def _matched_radar_npy(
    category: str, category_dir: str, info: dict, radar_lookup: dict[tuple, str]
) -> tuple[str, bool]:
    """Relative path of the radar .npy this log is the ground truth for.

    Prefers the real path recorded in the radar index; falls back to the
    batch_process.py naming template. Returns ``(npy_path, resolved)`` where
    ``resolved`` is True when the path came from the index (i.e. exists).
    """
    key = (category, info["position"], info["bandwidth_token"], info["test"])
    if key in radar_lookup:
        return radar_lookup[key], True
    stem = f"adc_{info['bandwidth_token']}_position{info['position']}_({info['test']})"
    template = f"{_OUTPUT_DIR_NAME}/{category_dir}/position_{info['position']}/{stem}.npy"
    return template, False


# ── CSV parsing ────────────────────────────────────────────────────────────
def load_log_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load an ECG/PCG log CSV into two float arrays.

    The files carry two header rows (``Column1,Column2`` then ``ECG,PCG``)
    before the numeric data; both are skipped.
    """
    data = np.genfromtxt(path, delimiter=",", skip_header=2, dtype=np.float64)
    if data.ndim != 2 or data.shape[1] < 2:
        raise ValueError(f"{path.name}: expected 2 numeric columns, got shape {data.shape}")
    ecg = data[:, 0]
    pcg = data[:, 1]
    # Drop any rows that failed to parse (NaN) to keep downstream maths clean.
    good = ~(np.isnan(ecg) | np.isnan(pcg))
    return ecg[good], pcg[good]


# ── Pure-numpy R-peak detection ────────────────────────────────────────────
def _moving_average(x: np.ndarray, win: int) -> np.ndarray:
    """Centered moving average via cumulative sum; output matches input length."""
    if win <= 1:
        return x
    kernel = np.ones(win, dtype=np.float64) / win
    return np.convolve(x, kernel, mode="same")


def _find_peaks(x: np.ndarray, height: float, distance: int) -> np.ndarray:
    """Local maxima of ``x`` above ``height``, no two closer than ``distance``.

    Greedy by amplitude (tallest peaks win when two candidates conflict), which
    matches scipy.signal.find_peaks' refractory behaviour closely enough for
    QRS picking.
    """
    if x.size < 3:
        return np.empty(0, dtype=int)
    # Strict rise / non-strict fall -> picks the first sample of a flat top.
    cand = np.where((x[1:-1] > x[:-2]) & (x[1:-1] >= x[2:]))[0] + 1
    cand = cand[x[cand] >= height]
    if cand.size == 0:
        return cand
    order = cand[np.argsort(x[cand])[::-1]]
    accepted: list[int] = []
    acc = np.empty(0, dtype=int)
    for p in order:
        if acc.size == 0 or np.all(np.abs(acc - p) >= distance):
            accepted.append(int(p))
            acc = np.append(acc, p)
    return np.sort(np.asarray(accepted, dtype=int))


def detect_r_peaks(ecg: np.ndarray, fs: float) -> np.ndarray:
    """Detect ECG R-peak sample indices using a Pan-Tompkins-style pipeline.

    Steps: baseline removal -> derivative -> squaring -> moving-window
    integration -> adaptive, refractory-constrained peak pick. Pure numpy.
    """
    if ecg.size < int(fs):
        return np.empty(0, dtype=int)

    # 1. Remove baseline wander with a ~0.6 s moving-average high-pass.
    baseline = _moving_average(ecg, max(3, int(0.6 * fs)))
    sig = ecg - baseline

    # 2. Derivative emphasises the steep QRS slope.
    deriv = np.gradient(sig)

    # 3. Square to make everything positive and boost large slopes.
    squared = deriv ** 2

    # 4. Moving-window integration over ~120 ms (QRS energy envelope).
    integrated = _moving_average(squared, max(3, int(0.12 * fs)))

    # 5. Adaptive threshold + 300 ms refractory (=> <= 200 bpm ceiling).
    thresh = integrated.mean() + 0.5 * integrated.std()
    distance = max(1, int(0.30 * fs))
    env_peaks = _find_peaks(integrated, height=thresh, distance=distance)
    if env_peaks.size == 0:
        return env_peaks

    # 6. Snap each envelope peak to the true ECG R-peak within a +/-60 ms window.
    half = max(1, int(0.06 * fs))
    r_peaks = []
    for p in env_peaks:
        lo, hi = max(0, p - half), min(ecg.size, p + half + 1)
        r_peaks.append(lo + int(np.argmax(ecg[lo:hi])))
    return np.unique(np.asarray(r_peaks, dtype=int))


def heart_rate_series(
    r_peaks: np.ndarray, fs: float, duration_s: float
) -> tuple[np.ndarray, np.ndarray]:
    """Build a 1 Hz per-second heart-rate series from R-peak indices.

    Returns ``(seconds_grid, hr_bpm)``. Instantaneous HR is computed from R-R
    intervals, filtered to a physiological band, and linearly interpolated onto
    integer-second timestamps spanning the capture.
    """
    n_secs = max(1, int(round(duration_s)))
    grid = np.arange(n_secs, dtype=np.float64)
    if r_peaks.size < 2:
        return grid, np.full(n_secs, np.nan, dtype=np.float64)

    peak_times = r_peaks / fs
    rr = np.diff(peak_times)
    inst_hr = 60.0 / rr
    # Timestamp each instantaneous HR at the midpoint of its R-R interval.
    hr_times = peak_times[:-1] + rr / 2.0

    ok = (inst_hr >= _HR_MIN_BPM) & (inst_hr <= _HR_MAX_BPM)
    hr_times, inst_hr = hr_times[ok], inst_hr[ok]
    if inst_hr.size == 0:
        return grid, np.full(n_secs, np.nan, dtype=np.float64)

    hr_grid = np.interp(grid, hr_times, inst_hr, left=inst_hr[0], right=inst_hr[-1])
    return grid, hr_grid


# ── Stats / summary ────────────────────────────────────────────────────────
def _waveform_stats(name: str, x: np.ndarray) -> dict:
    return {
        f"{name}_mean": float(np.mean(x)),
        f"{name}_std": float(np.std(x)),
        f"{name}_min": float(np.min(x)),
        f"{name}_max": float(np.max(x)),
    }


def _nan_summary(hr: np.ndarray) -> dict:
    valid = hr[~np.isnan(hr)]
    if valid.size == 0:
        return {"hr_mean_bpm": None, "hr_std_bpm": None,
                "hr_min_bpm": None, "hr_max_bpm": None}
    return {
        "hr_mean_bpm": round(float(np.mean(valid)), 2),
        "hr_std_bpm": round(float(np.std(valid)), 2),
        "hr_min_bpm": round(float(np.min(valid)), 2),
        "hr_max_bpm": round(float(np.max(valid)), 2),
    }


def _build_summary(
    csv_path: Path,
    category_dir: str,
    info: dict,
    fs: float,
    ecg: np.ndarray,
    pcg: np.ndarray,
    r_peaks: np.ndarray,
    hr_grid: np.ndarray,
    npz_rel: str,
    json_rel: str,
    radar_lookup: dict[tuple, str],
) -> dict:
    n_samples = ecg.size
    duration_s = n_samples / fs
    category = _infer_category(csv_path)
    radar_npy, radar_resolved = _matched_radar_npy(
        category, category_dir, info, radar_lookup
    )
    return {
        "source_file": csv_path.name,
        "category": category,
        "position": info["position"],
        "test": info["test"],
        "target": info["target"],
        "bandwidth_ghz": info["bandwidth_hz"] / 1e9,
        "bandwidth_token": info["bandwidth_token"],
        "role": "ground_truth_label",
        "label_npz_path": npz_rel,
        "label_json_path": json_rel,
        # The radar capture this label supervises (X <-> Y pairing).
        "matched_radar_npy": radar_npy,
        "matched_radar_resolved": radar_resolved,
        "log_config": {
            "sampling_rate_hz": fs,
            "channels": ["ECG", "PCG"],
            "n_samples": int(n_samples),
            "duration_s": round(duration_s, 2),
        },
        # Arrays bundled inside the .npz, with how to interpret each.
        "arrays": {
            "ecg": {"shape": [int(n_samples)], "dtype": "float32",
                    "sampling_rate_hz": fs, "units": "raw_adc"},
            "pcg": {"shape": [int(n_samples)], "dtype": "float32",
                    "sampling_rate_hz": fs, "units": "raw_adc"},
            "hr_per_second": {"shape": [int(hr_grid.size)], "dtype": "float32",
                              "sampling_rate_hz": 1.0, "units": "bpm",
                              "derived_from": "ecg"},
        },
        "num_beats_detected": int(r_peaks.size),
        "hr_summary": _nan_summary(hr_grid),
        # Small enough (~60 values) to embed for quick LLM/RAG inspection.
        "hr_per_second_bpm": [None if np.isnan(v) else round(float(v), 2)
                              for v in hr_grid],
        "ecg_stats": _waveform_stats("ecg", ecg),
        "pcg_stats": _waveform_stats("pcg", pcg),
    }


# ── Discovery / driver ─────────────────────────────────────────────────────
def _discover_log_csvs(dataset_root: Path) -> list[Path]:
    csvs: list[Path] = []
    for category in _CATEGORY_DIRS:
        log_dir = dataset_root / category / _LOG_SUBDIR
        if not log_dir.is_dir():
            print(f"[WARN] Log directory not found, skipping: {log_dir}")
            continue
        csvs.extend(sorted(log_dir.rglob("*.csv")))
    return csvs


def _output_base(dataset_root: Path, category_dir: str, info: dict, stem: str) -> Path:
    out_dir = dataset_root / _OUTPUT_DIR_NAME / category_dir / f"position_{info['position']}"
    return out_dir / stem


def process_all(dataset_root: Path | None = None, fs: float = _DEFAULT_LOG_FS) -> list[dict]:
    dataset_root = Path(dataset_root or _DEFAULT_DATASET_ROOT).resolve()
    print(f"Dataset root: {dataset_root}")
    print(f"Output dir:   {dataset_root / _OUTPUT_DIR_NAME}")
    print(f"Log sampling rate assumed: {fs} Hz\n")

    csvs = _discover_log_csvs(dataset_root)
    total = len(csvs)
    print(f"Found {total} log .csv files to process.\n")
    if total == 0:
        print("[ERROR] No log CSVs found. Check the dataset_root path.")
        return []

    radar_lookup = load_radar_index(dataset_root)
    print(f"Radar index entries available for pairing: {len(radar_lookup)}\n")

    summaries: list[dict] = []
    processed = skipped = unresolved = 0

    for i, csv_path in enumerate(csvs, 1):
        rel = csv_path.relative_to(dataset_root)
        print(f"[{i}/{total}] Processing: {rel}")

        info = parse_log_filename(csv_path)
        if info is None:
            print(f"  [SKIP] Name does not match log convention: {csv_path.name}")
            skipped += 1
            continue

        t0 = time.time()
        try:
            ecg, pcg = load_log_csv(csv_path)
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR] Failed to parse: {e}")
            skipped += 1
            continue

        duration_s = ecg.size / fs
        r_peaks = detect_r_peaks(ecg, fs)
        _, hr_grid = heart_rate_series(r_peaks, fs, duration_s)

        category_dir = _category_dir_for(csv_path)
        stem = csv_path.stem.replace(" ", "")
        out_base = _output_base(dataset_root, category_dir, info, stem)
        out_base.parent.mkdir(parents=True, exist_ok=True)
        npz_path = out_base.with_suffix(".npz")
        json_path = out_base.with_suffix(".json")

        # Bundle both raw waveforms and the derived label in one .npz:
        #   ecg / pcg       - raw signals at fs Hz, float32, shape (n_samples,)
        #   hr_per_second   - derived heart rate, float32, shape (duration_s,)
        np.savez_compressed(
            npz_path,
            ecg=ecg.astype(np.float32),
            pcg=pcg.astype(np.float32),
            hr_per_second=hr_grid.astype(np.float32),
        )

        # Remove a stale .npy from older runs so outputs stay unambiguous.
        old_npy = out_base.with_suffix(".npy")
        if old_npy.exists():
            old_npy.unlink()

        summary = _build_summary(
            csv_path, category_dir, info, fs, ecg, pcg, r_peaks, hr_grid,
            str(npz_path.relative_to(dataset_root)),
            str(json_path.relative_to(dataset_root)),
            radar_lookup,
        )
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        summaries.append(summary)
        processed += 1
        if not summary["matched_radar_resolved"]:
            unresolved += 1
            print(f"  [WARN] No radar match in index for {csv_path.name}")

        hr = summary["hr_summary"]["hr_mean_bpm"]
        print(f"  -> {r_peaks.size} beats | mean HR {hr} bpm "
              f"| {duration_s:.1f}s | {time.time() - t0:.2f}s")

    index_path = dataset_root / _OUTPUT_DIR_NAME / "log_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump({
            "dataset": "ChronoSense FMCW Radar - Ground-truth labels (ECG/PCG)",
            "label_type": "per_second_heart_rate_bpm",
            "sampling_rate_hz": fs,
            "total_files_processed": processed,
            "total_files_skipped": skipped,
            "total_files_found": total,
            "categories": _CATEGORY_DIRS,
            "files": summaries,
        }, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f"DONE: Processed {processed}/{total} files ({skipped} skipped)")
    print(f"Radar pairings resolved: {processed - unresolved}/{processed} "
          f"({unresolved} unresolved)")
    print(f"Master label index: {index_path}")
    print(f"{'=' * 60}")
    return summaries


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Extract per-second heart-rate ground-truth labels from "
                    "ChronoSense ECG/PCG log CSVs."
    )
    ap.add_argument("--dataset-root", type=Path, default=_DEFAULT_DATASET_ROOT,
                    help="Root of the FMCW_dataset directory.")
    ap.add_argument("--fs", type=float, default=_DEFAULT_LOG_FS,
                    help=f"ECG/PCG sampling rate in Hz (default: {_DEFAULT_LOG_FS}).")
    args = ap.parse_args()
    process_all(dataset_root=args.dataset_root, fs=args.fs)
