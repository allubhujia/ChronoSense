"""Turn 7 days of patient vitals into a natural-language drift trajectory summary.

This is the heart of the Temporal RAG query construction. From the raw vitals it:
  - collapses records into one drift value per calendar day (the daily trajectory),
  - identifies the primary SHAP driver across the window (and a secondary one),
  - decides whether drift is accelerating, decelerating, or fluctuating,
  - emits a clinician-style summary used as the retrieval query.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from . import config


@dataclass
class TrajectoryAnalysis:
    patient_id: str
    daily_drift: list[float]              # one drift value per day, ascending
    daily_primary: list[str]             # dominant SHAP feature per day
    primary_driver: str                  # overall primary driver label (e.g. "SpO2")
    primary_driver_days: int             # # days the primary was dominant
    primary_avg_attribution: float       # avg attribution of the primary driver
    secondary_driver: str | None         # secondary feature label, if notable
    secondary_from_day: int | None       # 1-based day the secondary first appears
    trend: str                           # "accelerating" | "decelerating" | "fluctuating"
    demographics: dict = field(default_factory=dict)
    summary: str = ""           # human-readable summary (shown + fed to agents)
    retrieval_query: str = ""   # clinical vignette used to query the guidelines


# How each drift driver reads as a clinical sign (for the retrieval vignette).
# Keyed by the SHAP_FIELDS label.
_DRIVER_CLINICAL = {
    "HR": "rising heart rate (tachycardia) and cardiovascular strain",
    "RR": "rising respiratory rate, increasing breathlessness and respiratory distress",
    "Movement": "reduced mobility and increased restlessness",
}


def _day_key(ts) -> date:
    return ts.date() if hasattr(ts, "date") else ts


def _aggregate_daily(records: list[dict]) -> list[dict]:
    """Collapse possibly-many records per day into one mean record per day.

    Returns a list of per-day dicts (drift_score + shap_* means), ascending.
    """
    by_day: dict[date, list[dict]] = defaultdict(list)
    for r in records:
        by_day[_day_key(r["timestamp"])].append(r)

    daily: list[dict] = []
    for day in sorted(by_day):
        rows = by_day[day]
        n = len(rows)

        def mean(field_name: str) -> float:
            vals = [float(r[field_name]) for r in rows if r.get(field_name) is not None]
            return sum(vals) / len(vals) if vals else 0.0

        agg = {"day": day, "drift_score": mean("drift_score")}
        for f in config.SHAP_FIELDS:
            agg[f] = mean(f)
        daily.append(agg)
    return daily


def _dominant_feature(day: dict) -> str:
    """The SHAP field with the largest absolute attribution for one day."""
    return max(config.SHAP_FIELDS, key=lambda f: abs(day.get(f, 0.0)))


def _classify_trend(drift: list[float]) -> str:
    if len(drift) < 2:
        return "insufficient data"
    if all(b > a for a, b in zip(drift, drift[1:])):
        return "accelerating"
    if all(b < a for a, b in zip(drift, drift[1:])):
        return "decelerating"
    return "fluctuating"


def analyze(records: list[dict], demographics: dict | None = None) -> TrajectoryAnalysis:
    """Build a TrajectoryAnalysis from sorted vitals records."""
    if not records:
        raise ValueError("No vitals records to analyze.")

    daily = _aggregate_daily(records)
    daily_drift = [round(d["drift_score"], 3) for d in daily]

    # Per-day dominant feature, but only on days with non-trivial attribution
    # (on a zero-drift day every SHAP is 0, so there is no real driver to count).
    field_totals = {
        f: sum(abs(d.get(f, 0.0)) for d in daily) for f in config.SHAP_FIELDS
    }
    daily_primary = [
        _dominant_feature(d)
        if max(abs(d.get(f, 0.0)) for f in config.SHAP_FIELDS) > 1e-9
        else None
        for d in daily
    ]

    # Overall primary driver = feature with the largest total attribution across
    # the window (matches how build_patient_vitals assigns the condition).
    primary_field = max(field_totals, key=field_totals.get)
    primary_label = config.SHAP_FIELDS[primary_field]
    primary_days = sum(1 for f in daily_primary if f == primary_field)
    primary_avg = round(field_totals[primary_field] / len(daily), 3)

    # Secondary driver: next-most-attributed feature overall (excluding primary).
    others_totals = {f: t for f, t in field_totals.items() if f != primary_field}
    secondary_field = max(others_totals, key=others_totals.get) if others_totals else None
    secondary_label = None
    secondary_from = None
    if secondary_field and others_totals.get(secondary_field, 0.0) > 0:
        secondary_label = config.SHAP_FIELDS[secondary_field]
        # First (1-based) day where the secondary feature carries real weight.
        for i, d in enumerate(daily, start=1):
            non_primary = [abs(d.get(f, 0.0)) for f in config.SHAP_FIELDS if f != primary_field]
            val = abs(d.get(secondary_field, 0.0))
            if val > 0 and non_primary and val == max(non_primary):
                secondary_from = i
                break

    trend = _classify_trend(daily_drift)

    analysis = TrajectoryAnalysis(
        patient_id=records[0]["patient_id"],
        daily_drift=daily_drift,
        daily_primary=[config.SHAP_FIELDS[f] if f else None for f in daily_primary],
        primary_driver=primary_label,
        primary_driver_days=primary_days,
        primary_avg_attribution=primary_avg,
        secondary_driver=secondary_label,
        secondary_from_day=secondary_from,
        trend=trend,
        demographics=demographics or {},
    )
    analysis.summary = build_summary(analysis)
    analysis.retrieval_query = build_clinical_query(analysis)
    return analysis


def build_clinical_query(a: TrajectoryAnalysis) -> str:
    """Render a clinical vignette for RETRIEVAL.

    The ML-flavoured summary ("RR-driven drift, avg attribution 0.158") embeds
    close to statistics/reference text. A plain clinical vignette embeds close to
    the guideline sections that actually matter (severity, exacerbation, referral),
    so we query with this instead of the summary.
    """
    cond = a.demographics.get("condition")
    age = a.demographics.get("age")
    who = f"{age}-year-old patient" if age is not None else "patient"
    if cond:
        who += f" with {cond}"

    primary = _DRIVER_CLINICAL.get(a.primary_driver, "worsening vital signs")
    trend_phrase = {
        "accelerating": "progressively worsening over the past 7 days",
        "decelerating": "gradually improving over the past 7 days",
        "fluctuating": "fluctuating over the past 7 days",
    }.get(a.trend, "changing over the past 7 days")

    # Severity hint from the latest drift level.
    latest = a.daily_drift[-1] if a.daily_drift else 0.0
    severity = "severe" if latest >= 0.6 else "moderate" if latest >= 0.3 else "mild"

    parts = [
        f"{who} showing {primary}, {trend_phrase} ({severity} deterioration)."
    ]
    if a.secondary_driver:
        parts.append(
            f"There is also {_DRIVER_CLINICAL.get(a.secondary_driver, 'additional involvement')}."
        )
    if a.trend == "accelerating":
        parts.append(
            "This pattern suggests a possible acute exacerbation requiring escalation."
        )
    parts.append(
        "What does the guideline advise on severity grading, management, "
        "monitoring thresholds, and when to refer or escalate?"
    )
    return " ".join(parts)


def build_summary(a: TrajectoryAnalysis) -> str:
    """Render the clinician-style trajectory summary used as the RAG query.

    Mirrors the spec example, e.g.:
    "Patient with CHF, age 58. 7-day SpO2-driven drift trajectory showing
     acceleration: day1 score 0.31, day2 0.44, day3 0.61, day4 0.81.
     SpO2 primary driver all 4 days (avg attribution 0.72). HR secondary
     involvement from day 3. Drift rate accelerating."
    """
    n = len(a.daily_drift)
    parts: list[str] = []

    # Demographics prefix, if available.
    cond = a.demographics.get("condition")
    age = a.demographics.get("age")
    if cond and age is not None:
        parts.append(f"Patient with {cond}, age {age}.")
    elif cond:
        parts.append(f"Patient with {cond}.")
    else:
        parts.append(f"Patient {a.patient_id}.")

    trend_noun = {
        "accelerating": "acceleration",
        "decelerating": "deceleration",
        "fluctuating": "a fluctuating pattern",
    }.get(a.trend, "an evolving pattern")

    day_scores = ", ".join(
        f"day{i} {'score ' if i == 1 else ''}{v}"
        for i, v in enumerate(a.daily_drift, start=1)
    )
    parts.append(
        f"{n}-day {a.primary_driver}-driven drift trajectory showing "
        f"{trend_noun}: {day_scores}."
    )

    # Primary driver coverage.
    coverage = "all" if a.primary_driver_days == n else f"{a.primary_driver_days} of"
    parts.append(
        f"{a.primary_driver} primary driver {coverage} {n} days "
        f"(avg attribution {a.primary_avg_attribution})."
    )

    if a.secondary_driver and a.secondary_from_day:
        parts.append(
            f"{a.secondary_driver} secondary involvement from day {a.secondary_from_day}."
        )

    parts.append(f"Drift rate {a.trend}.")
    return " ".join(parts)
