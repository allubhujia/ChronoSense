"""
Radar-only respiration & heartbeat extraction for the ChronoSense FMCW dataset.

This is a NumPy port of the dataset authors' MATLAB reference pipeline
(Code_for_Processing/: Main.m, MTI.m, IWR6843ISK_DOA.m, get_heartBreath_rate.m,
RR_BPF20.m, HR_BPF20.m). It turns one raw radar `.bin` capture into the vital
signs of the (up to two) people in front of the radar - using **only the radar
signal**. No ECG/PCG, no reference logs.

Pipeline, per capture
---------------------
1. Parse `.bin` -> complex cube (frames, TX, RX, adc)            [fmcw_bin_parser]
2. Virtual array: keep TX1 + TX3 -> 8 virtual RX channels        (as in Data_processing.m)
3. MTI: mean-cancellation over slow-time, then 256-pt range-FFT  (MTI.m)
4. MVDR DOA: per range bin, build the range-angle spectrum       (IWR6843ISK_DOA.m)
5. Find the top-2 peaks (the two subjects) in range-angle        (findLocalMaximaInIdx.m)
6. MVDR beamform at each (range, angle) -> one slow-time signal  (Main.m)
7. Phase -> unwrap -> diff -> band-pass into respiration / heart (get_heartBreath_rate.m)
8. FFT peak in each band -> breathing rate & heart rate (per min)

Slow-time sampling rate is 1/frame_period = 1/0.05 s = 20 Hz, so the spectra
resolve breathing (0.1-0.6 Hz) and heartbeat (0.9-2.0 Hz) cleanly over the 60 s
capture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from fmcw_bin_parser import RadarParams, parse_bin, parse_filename

# ── Processing constants (match the MATLAB reference) ───────────────────────
_RANGE_FFT_NUM = 256          # range-FFT length (MTI.m / Main.m)
_SEARCH_ANGLE_DEG = 60        # MVDR azimuth search is +/- this (Main.m)
_ANGLE_STEP_DEG = 1.0         # 1 degree grid -> 121 angles
_MAX_SUBJECTS = 2             # dataset is dual-subject (Target1 + Target2)

# Band edges (Hz). RR_BPF20.m: 0.1-0.6 Hz. HR_BPF20.m: 0.9-2.0 Hz.
_RESP_BAND_HZ = (0.1, 0.6)
_HEART_BAND_HZ = (0.9, 2.0)

# Range bins to consider when locating people. Bin 0 is DC/self-coupling; very
# far bins are noise. ~0.2 m .. ~3 m covers the seated-subject geometry.
_MIN_RANGE_BIN = 4
_MAX_RANGE_M = 3.0

# Peak suppression so the two detected subjects are genuinely distinct, not two
# adjacent cells of the same person.
_SUPPRESS_RANGE_BINS = 4
_SUPPRESS_ANGLE_DEG = 12.0


@dataclass
class SubjectVitals:
    """Respiration + heartbeat for one detected person."""

    subject_index: int
    range_bin: int
    range_m: float
    angle_deg: float
    breathing_rate_bpm: int
    heart_rate_bpm: int
    resp_peak_hz: float
    heart_peak_hz: float
    resp_snr_db: float
    heart_snr_db: float
    # Full-resolution waveforms (go into the .npz; previews go into the .json).
    phase_unwrapped: np.ndarray = field(repr=False)
    phase_diff: np.ndarray = field(repr=False)
    respiration_wave: np.ndarray = field(repr=False)
    heartbeat_wave: np.ndarray = field(repr=False)
    target_complex: np.ndarray = field(repr=False)


@dataclass
class CaptureVitals:
    """Everything extracted from one `.bin` capture."""

    frames: int
    duration_s: float
    slowtime_fs_hz: float
    range_resolution_m: float
    bandwidth_hz: float
    subjects: list[SubjectVitals]
    time_s: np.ndarray = field(repr=False)


# ── Signal-processing helpers ───────────────────────────────────────────────
def virtual_array(cube: np.ndarray) -> np.ndarray:
    """Collapse the (frames, TX, RX, adc) cube to the 8-channel virtual array.

    The reference keeps TX1 and TX3 (drops the middle TX), giving an 8-element
    virtual ULA: [TX1.RX1..4, TX3.RX1..4]. Returns (frames, 8, adc).
    """
    if cube.shape[1] < 3:
        raise ValueError(f"Expected >=3 TX chirps per frame, got {cube.shape[1]}")
    tx1 = cube[:, 0, :, :]   # (frames, RX, adc)
    tx3 = cube[:, 2, :, :]
    return np.concatenate([tx1, tx3], axis=1)  # (frames, 8, adc)


def range_profile(virt: np.ndarray, n_fft: int = _RANGE_FFT_NUM) -> np.ndarray:
    """MTI mean-cancellation + range-FFT (MTI.m, cancelFlag=0).

    Subtracts the slow-time mean of each range/channel (removes static clutter
    and the DC self-term), then FFTs along the ADC (fast-time) axis.
    Returns complex (frames, 8, n_fft).
    """
    mean_cancelled = virt - virt.mean(axis=0, keepdims=True)
    return np.fft.fft(mean_cancelled, n=n_fft, axis=2)


def _steering_matrix(angles_deg: np.ndarray, n_ch: int = 8) -> np.ndarray:
    """ULA steering matrix a_k(theta) = exp(-j k pi sin(theta)), k = 0..n_ch-1.

    d = lambda/2 so the spatial phase per element is pi*sin(theta). Returns
    (n_ch, n_angles).
    """
    k = np.arange(n_ch).reshape(-1, 1)               # (n_ch, 1)
    fai = np.pi * np.sin(np.deg2rad(angles_deg))     # (n_angles,)
    return np.exp(-1j * k * fai)                     # (n_ch, n_angles)


def mvdr_range_angle(
    rp: np.ndarray, angles_deg: np.ndarray
) -> tuple[np.ndarray, list[np.ndarray]]:
    """MVDR (Capon) range-angle spectrum (IWR6843ISK_DOA.m, MVDR mode).

    For each range bin: covariance R = X^H X over the frame snapshots, then
    P(theta) = 1 / (a^H R^-1 a). Returns (spectrum [n_angles, n_range], and the
    list of per-range inverse covariances so beamforming can reuse them).
    """
    n_frames, n_ch, n_range = rp.shape
    steer = _steering_matrix(angles_deg, n_ch)        # (n_ch, n_angles)
    spectrum = np.zeros((len(angles_deg), n_range), dtype=np.float64)
    inv_cov: list[np.ndarray] = []

    for r in range(n_range):
        x = rp[:, :, r]                               # (frames, n_ch)
        cov = x.conj().T @ x                          # (n_ch, n_ch)
        rxv = np.linalg.pinv(cov)
        inv_cov.append(rxv)
        # denom_a = a^H Rxv a for every steering vector at once.
        denom = np.einsum("ia,ij,ja->a", steer.conj(), rxv, steer)
        spectrum[:, r] = 1.0 / np.abs(denom)

    return spectrum, inv_cov


def find_subjects(
    spectrum: np.ndarray,
    angles_deg: np.ndarray,
    range_res_m: float,
    max_subjects: int = _MAX_SUBJECTS,
) -> list[tuple[int, int]]:
    """Pick up to `max_subjects` (angle_idx, range_idx) peaks from the spectrum.

    Greedy: take the global max, suppress a neighbourhood around it so the next
    pick is a different person, repeat. Search is limited to a physically
    plausible range window.
    """
    n_angles, n_range = spectrum.shape
    max_bin = min(n_range - 1, int(_MAX_RANGE_M / range_res_m)) if range_res_m > 0 else n_range - 1

    work = spectrum.copy()
    work[:, :_MIN_RANGE_BIN] = 0.0          # null DC / self-coupling
    work[:, max_bin + 1:] = 0.0             # null far noise

    angle_step = float(np.mean(np.diff(angles_deg))) if len(angles_deg) > 1 else 1.0
    suppress_ang = max(1, int(round(_SUPPRESS_ANGLE_DEG / abs(angle_step))))

    picks: list[tuple[int, int]] = []
    for _ in range(max_subjects):
        if not np.any(work > 0):
            break
        a_idx, r_idx = np.unravel_index(int(np.argmax(work)), work.shape)
        picks.append((int(a_idx), int(r_idx)))
        a0, a1 = max(0, a_idx - suppress_ang), min(n_angles, a_idx + suppress_ang + 1)
        r0, r1 = max(0, r_idx - _SUPPRESS_RANGE_BINS), min(n_range, r_idx + _SUPPRESS_RANGE_BINS + 1)
        work[a0:a1, r0:r1] = 0.0
    return picks


def beamform(rp: np.ndarray, rxv: np.ndarray, angle_deg: float, range_idx: int) -> np.ndarray:
    """MVDR beamform at one (angle, range) -> a single complex slow-time signal.

    Wopt = Rxv a / (a^H Rxv a); signal = X(range) @ Wopt  (Main.m). Returns a
    complex vector of length `frames`.
    """
    n_ch = rp.shape[1]
    a = _steering_matrix(np.array([angle_deg]), n_ch)[:, 0]   # (n_ch,)
    wopt = (rxv @ a) / (a.conj() @ rxv @ a)
    return rp[:, :, range_idx] @ wopt                         # (frames,)


def fft_bandpass(x: np.ndarray, lo_hz: float, hi_hz: float, fs: float) -> np.ndarray:
    """Zero-phase band-pass by masking the rFFT outside [lo, hi]. Real output.

    Stands in for the reference Butterworth IIR filters (RR/HR_BPF20). For
    in-band rate estimation the two are equivalent; this one needs no SciPy and
    is zero-phase (no group delay distorting the waveform).
    """
    n = len(x)
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    spec[(freqs < lo_hz) | (freqs > hi_hz)] = 0.0
    return np.fft.irfft(spec, n=n)


def band_rate(wave: np.ndarray, lo_hz: float, hi_hz: float, fs: float) -> tuple[int, float, float]:
    """Dominant frequency of `wave` within [lo, hi] -> (rate_per_min, peak_hz, snr_db).

    SNR is the in-band peak power over the mean in-band power.
    """
    n = len(wave)
    mag = np.abs(np.fft.rfft(wave))
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    band = (freqs >= lo_hz) & (freqs <= hi_hz)
    if not np.any(band) or not np.any(mag[band] > 0):
        return 0, 0.0, 0.0
    band_mag = mag[band]
    band_freqs = freqs[band]
    peak = int(np.argmax(band_mag))
    peak_hz = float(band_freqs[peak])
    power = band_mag ** 2
    snr = power[peak] / (power.mean() + 1e-12)
    snr_db = float(10.0 * np.log10(snr + 1e-12))
    rate = int(np.ceil(peak_hz * 60.0))
    return rate, peak_hz, snr_db


# ── Top-level driver ────────────────────────────────────────────────────────
def extract_vitals(
    bin_path: str | Path, params: RadarParams | None = None
) -> CaptureVitals:
    """Run the full radar-only vital-sign pipeline on one `.bin` capture."""
    params = params or RadarParams()
    info = parse_filename(bin_path)

    # Actual chirp bandwidth -> range resolution (Main.m). Tc = adc_samples/fs.
    tc = params.num_adc_samples / params.adc_sample_rate
    # Slope picked so the named bandwidth comes out right; fall back to 3 GHz.
    bandwidth_hz = info.bandwidth_hz if (info and np.isfinite(info.bandwidth_hz)) else 3.0e9
    range_res_m = 3e8 / (2.0 * bandwidth_hz)

    fs = 1.0 / params.frame_period                  # slow-time rate, 20 Hz

    cube = parse_bin(bin_path, params)              # (frames, TX, RX, adc)
    n_frames = cube.shape[0]
    duration_s = n_frames * params.frame_period
    time_s = np.arange(n_frames - 1) / fs           # phase-diff drops one sample

    virt = virtual_array(cube)                      # (frames, 8, adc)
    rp = range_profile(virt)                        # (frames, 8, 256)

    angles_deg = np.arange(-_SEARCH_ANGLE_DEG, _SEARCH_ANGLE_DEG + _ANGLE_STEP_DEG, _ANGLE_STEP_DEG)
    spectrum, inv_cov = mvdr_range_angle(rp, angles_deg)
    picks = find_subjects(spectrum, angles_deg, range_res_m)

    subjects: list[SubjectVitals] = []
    for i, (a_idx, r_idx) in enumerate(picks, start=1):
        angle_deg = float(angles_deg[a_idx])
        signal = beamform(rp, inv_cov[r_idx], angle_deg, r_idx)   # (frames,) complex

        phase = np.unwrap(np.angle(signal))
        # Phase difference (prev - next), as in get_heartBreath_rate.m.
        diff = phase[:-1] - phase[1:]
        diff = diff - diff.mean()

        resp_wave = fft_bandpass(diff, *_RESP_BAND_HZ, fs)
        heart_wave = fft_bandpass(diff, *_HEART_BAND_HZ, fs)

        br, br_hz, br_snr = band_rate(resp_wave, *_RESP_BAND_HZ, fs)
        hr, hr_hz, hr_snr = band_rate(heart_wave, *_HEART_BAND_HZ, fs)

        subjects.append(SubjectVitals(
            subject_index=i,
            range_bin=r_idx,
            range_m=round(r_idx * range_res_m, 4),
            angle_deg=round(angle_deg, 2),
            breathing_rate_bpm=br,
            heart_rate_bpm=hr,
            resp_peak_hz=round(br_hz, 4),
            heart_peak_hz=round(hr_hz, 4),
            resp_snr_db=round(br_snr, 2),
            heart_snr_db=round(hr_snr, 2),
            phase_unwrapped=phase[:-1].astype(np.float32),
            phase_diff=diff.astype(np.float32),
            respiration_wave=resp_wave.astype(np.float32),
            heartbeat_wave=heart_wave.astype(np.float32),
            target_complex=signal.astype(np.complex64),
        ))

    return CaptureVitals(
        frames=n_frames,
        duration_s=round(duration_s, 2),
        slowtime_fs_hz=fs,
        range_resolution_m=round(range_res_m, 4),
        bandwidth_hz=bandwidth_hz,
        subjects=subjects,
        time_s=time_s.astype(np.float32),
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: python vital_signs.py <path-to-.bin>")
        raise SystemExit(1)

    result = extract_vitals(sys.argv[1])
    print(f"frames={result.frames}  duration={result.duration_s}s  "
          f"range_res={result.range_resolution_m}m  detected={len(result.subjects)} subject(s)")
    for s in result.subjects:
        print(f"  subject {s.subject_index}: range={s.range_m}m angle={s.angle_deg}deg "
              f"| breathing={s.breathing_rate_bpm}/min (SNR {s.resp_snr_db}dB) "
              f"| heart={s.heart_rate_bpm}/min (SNR {s.heart_snr_db}dB)")
