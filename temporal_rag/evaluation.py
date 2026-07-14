"""LLM / RAG output-quality metrics for a single assessment.

Two checks, run after the agents produce a Predictive Care Brief:

1. citation_accuracy (deterministic, free)
   Do the agent's cited (source, page) references actually point at chunks that
   were retrieved? Catches invented citations with no LLM call.

2. groundedness (LLM-as-judge, one Groq call)
   Is every clinical claim in the rationale supported by the retrieved guideline
   excerpts, or did the model go beyond / contradict them? This is the key
   safety metric for a clinical RAG system — it measures hallucination.

Both are import-safe and defensive: any failure returns an error field rather
than raising, so evaluation never breaks the dashboard.
"""

from __future__ import annotations

import json
import re

from . import config


# ── 1. Citation accuracy (deterministic) ─────────────────────────────────────
def _source_stem(name: str | None) -> str:
    if not name:
        return ""
    return re.split(r"\.pdf", name, flags=re.IGNORECASE)[0].lower()


def citation_accuracy(chunks: list[dict], citations: list[str] | None) -> dict:
    """Fraction of the agent's citations that map to an actually-retrieved chunk.

    A citation counts as valid if some retrieved chunk's source filename (or a
    distinctive stem of it) AND its page number both appear in the citation
    string (e.g. "GOLD-2024_..._WMV.pdf p146").
    """
    citations = citations or []
    refs = [(_source_stem(c.get("source_document")), str(c.get("page"))) for c in chunks]

    details = []
    for cit in citations:
        low = cit.lower()
        ok = False
        for stem, page in refs:
            token = stem[:12]  # distinctive leading part of the filename
            if token and token in low and page and page in low:
                ok = True
                break
            # looser fallback: exact page match when the source token is absent
            if page and re.search(rf"\bp\.?\s*{re.escape(page)}\b", low):
                ok = True
                break
        details.append({"citation": cit, "valid": ok})

    n = len(details)
    valid = sum(1 for d in details if d["valid"])
    return {
        "score": round(valid / n, 3) if n else None,  # None → no citations to check
        "valid": valid,
        "total": n,
        "details": details,
    }


# ── 2. Groundedness (LLM-as-judge) ───────────────────────────────────────────
_JUDGE_SYSTEM = (
    "You are a strict clinical fact-checker for a medical AI system. You are given "
    "the EVIDENCE the AI was working from — the PATIENT TRAJECTORY DATA (the "
    "patient's own vitals/drift numbers) and the retrieved GUIDELINE EXCERPTS — and "
    "an AI-generated RATIONALE. Decide whether every clinical claim in the rationale "
    "is supported by that evidence. A claim about the patient's own trend/numbers is "
    "supported if it matches the TRAJECTORY DATA; a claim about management or severity "
    "is supported if it matches the GUIDELINE EXCERPTS. Judge ONLY against the provided "
    "evidence, not outside medical knowledge. Respond with a JSON object with keys: "
    '"groundedness" (float 0.0-1.0, fraction of claims supported), '
    '"verdict" (one of "grounded", "partially_grounded", "unsupported"), and '
    '"unsupported_claims" (array of short strings, empty if all supported).'
)


def groundedness(rationale: str, chunks: list[dict], patient_data: str = "") -> dict:
    """Score how well the rationale is supported by the evidence the agents saw:
    the patient trajectory data AND the retrieved guideline chunks.

    Passing the trajectory data is important — the rationale legitimately cites the
    patient's own numbers ("drift rose day 5 to 7"), which aren't in the guideline
    excerpts; without them the judge wrongly marks those true claims unsupported.

    Uses one Groq call (reusing the agents' client) timed under the "Evaluator"
    label for observability. Returns {error: ...} on any failure.
    """
    if not rationale:
        return {"error": "no rationale to evaluate"}

    excerpts = "\n\n".join(
        f"[{i}] ({c.get('source_document')}, p{c.get('page')})\n{c.get('text', '')}"
        for i, c in enumerate(chunks, 1)
    ) or "(no excerpts)"

    user = (
        f"PATIENT TRAJECTORY DATA:\n{patient_data or '(none provided)'}\n\n"
        f"GUIDELINE EXCERPTS:\n{excerpts}\n\n"
        f"RATIONALE TO CHECK:\n{rationale}"
    )

    try:
        from .agents import _chat  # reuse the Groq client + config
        from observability.metrics import track_groq

        with track_groq("Evaluator"):
            raw = _chat(_JUDGE_SYSTEM, user, temperature=0.0, json_mode=True)
        data = json.loads(raw)
        # Normalise + clamp.
        score = float(data.get("groundedness", 0.0))
        data["groundedness"] = round(max(0.0, min(1.0, score)), 3)
        data.setdefault("verdict", "unknown")
        data.setdefault("unsupported_claims", [])
        return data
    except Exception as exc:  # Groq down / no key / bad JSON
        return {"error": str(exc)}


# ── Combined ─────────────────────────────────────────────────────────────────
def evaluate(
    assessment: dict,
    chunks: list[dict],
    summary: str = "",
    run_judge: bool = True,
) -> dict:
    """Compute citation accuracy (always) + groundedness (if run_judge).

    `summary` is the trajectory summary the agents reasoned over; it's passed to
    the groundedness judge as evidence so claims about the patient's own numbers
    are correctly credited.
    """
    cc = assessment.get("care_coordination", {}) or {}
    rationale = cc.get("rationale") or assessment.get("clinical_analysis", "")
    citations = cc.get("citations", [])

    result = {"citation_accuracy": citation_accuracy(chunks, citations)}
    if run_judge:
        result["groundedness"] = groundedness(rationale, chunks, patient_data=summary)
    return result
