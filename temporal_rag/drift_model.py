"""Interpretable physiological drift model for ChronoSense.

Drift = how far a patient's vitals have moved from healthy clinical baselines.
We use a deliberately transparent **linear-additive** scorer:

    drift_score = clip( Σ_i  w_i * abnormality_i , 0, 1 )

where each feature's `abnormality_i` is its normalized deviation from a normal
clinical range, and `w_i` is its clinical weight. Because the score is a simple
weighted sum of independent per-feature terms, the **exact Shapley value of each
feature is its own term** `w_i * abnormality_i` (base value 0). So the SHAP
attributions stored in `patient_vitals` are analytic and exact — no sampling,
no `shap` library, fully reproducible.

Features (all derivable from the radar `captures` collection):
  - heart_rate        (bpm)  — heartbeat.heart_rate_bpm
  - respiratory_rate  (bpm)  — respiration.breathing_rate_bpm
  - movement_score    (a.u.) — chest-movement amplitude proxy (see builder)
"""

from __future__ import annotations

from dataclasses import dataclass

# Clinical weights (sum to 1.0); HR weighted highest for cardiac monitoring.
WEIGHTS = {"hr": 0.45, "rr": 0.35, "movement": 0.20}

# Normal ranges (low, high) outside which a feature starts contributing drift,
# and the scale (span) over which the abnormality ramps from 0 → 1.
_HR_NORMAL = (60.0, 100.0)
_HR_SCALE = 40.0
_RR_NORMAL = (12.0, 20.0)
_RR_SCALE = 12.0
# Movement is a unitless restlessness proxy; baseline ~0.4, ramps over 0.6.
_MOVEMENT_BASELINE = 0.4
_MOVEMENT_SCALE = 0.6


@dataclass
class DriftResult:
    drift_score: float
    shap_hr: float
    shap_rr: float
    shap_movement: float
    lower_ci: float
    upper_ci: float


def _range_abnormality(value: float, low: float, high: float, scale: float) -> float:
    """0 inside [low, high]; ramps toward 1 as `value` leaves the range."""
    if value < low:
        dev = (low - value) / scale
    elif value > high:
        dev = (value - high) / scale
    else:
        return 0.0
    return max(0.0, min(1.0, dev))


def _movement_abnormality(value: float) -> float:
    dev = (value - _MOVEMENT_BASELINE) / _MOVEMENT_SCALE
    return max(0.0, min(1.0, dev))


def score(
    heart_rate: float,
    respiratory_rate: float,
    movement_score: float,
    snr_db: float | None = None,
) -> DriftResult:
    """Compute drift score + exact per-feature SHAP attributions + CI band.

    `snr_db` (radar signal quality) widens the confidence interval when low:
    a noisier measurement → less certain drift estimate.
    """
    ab_hr = _range_abnormality(heart_rate, *_HR_NORMAL, _HR_SCALE)
    ab_rr = _range_abnormality(respiratory_rate, *_RR_NORMAL, _RR_SCALE)
    ab_mv = _movement_abnormality(movement_score)

    shap_hr = round(WEIGHTS["hr"] * ab_hr, 4)
    shap_rr = round(WEIGHTS["rr"] * ab_rr, 4)
    shap_mv = round(WEIGHTS["movement"] * ab_mv, 4)

    drift = max(0.0, min(1.0, shap_hr + shap_rr + shap_mv))

    # Confidence band: ~±0.03 at high SNR, widening as SNR drops.
    if snr_db is None:
        half = 0.05
    else:
        half = min(0.15, max(0.02, 1.2 / (snr_db + 1.0)))

    return DriftResult(
        drift_score=round(drift, 4),
        shap_hr=shap_hr,
        shap_rr=shap_rr,
        shap_movement=shap_mv,
        lower_ci=round(max(0.0, drift - half), 4),
        upper_ci=round(min(1.0, drift + half), 4),
    )
