"""Multi-agent clinical reasoning layer over Groq.

Three specialist agents run in sequence, each consuming the previous one's
output plus the shared context (trajectory summary + retrieved guideline chunks):

  1. ClinicalAnalyst   — interprets the 7-day drift trajectory physiologically.
  2. GuidelineGrounder — maps that interpretation onto the retrieved Ayushman
                         Bharat guideline chunks, citing source + page.
  3. CareCoordinator   — issues an actionable, PM-JAY-aligned recommendation
                         (monitor / teleconsult / refer / escalate) in JSON.

Designed to be import-safe even when the `groq` package or GROQ_API_KEY is
absent: construction is lazy, so ingest/retrieval can be used without Groq.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from . import config


@lru_cache(maxsize=1)
def _client():
    from groq import Groq

    if not config.GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Add it to your environment or .env file."
        )
    return Groq(api_key=config.GROQ_API_KEY)


def _chat(system: str, user: str, temperature: float = 0.2, json_mode: bool = False) -> str:
    kwargs = {
        "model": config.GROQ_MODEL,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = _client().chat.completions.create(**kwargs)
    return resp.choices[0].message.content.strip()


def _format_chunks(chunks: list[dict]) -> str:
    blocks = []
    for i, c in enumerate(chunks, 1):
        blocks.append(
            f"[Guideline {i}] (source: {c['source_document']}, page {c['page']}, "
            f"similarity {c.get('similarity')})\n{c['text']}"
        )
    return "\n\n".join(blocks) if blocks else "(no guideline chunks retrieved)"


# ── Agent definitions ────────────────────────────────────────────────────────
@dataclass
class Agent:
    name: str
    system_prompt: str
    temperature: float = 0.2
    json_mode: bool = False

    def run(self, user_prompt: str) -> str:
        return _chat(self.system_prompt, user_prompt, self.temperature, self.json_mode)


CLINICAL_ANALYST = Agent(
    name="ClinicalAnalyst",
    system_prompt=(
        "You are a clinical analyst for a remote patient-monitoring system in India. "
        "You receive a 7-day physiological drift trajectory derived from contactless "
        "radar vitals (SpO2, heart rate, respiratory rate, movement) with SHAP "
        "attributions. Explain, in 4-6 sentences, what the trajectory and its primary "
        "driver physiologically suggest, how concerning the trend is, and what the "
        "differential considerations are. Be precise and clinical; do not invent vitals "
        "that were not provided."
    ),
)

GUIDELINE_GROUNDER = Agent(
    name="GuidelineGrounder",
    system_prompt=(
        "You are a clinical-guidelines specialist. Given a clinical interpretation and "
        "retrieved chunks from the Ayushman Bharat Digital Mission guidelines, map the "
        "patient's situation onto the guidelines. Quote or paraphrase the specific "
        "applicable directives and ALWAYS cite them as (source_document, page N). If the "
        "retrieved guidelines do not cover something, say so explicitly rather than "
        "guessing. Output 3-6 grounded bullet points."
    ),
)

CARE_COORDINATOR = Agent(
    name="CareCoordinator",
    system_prompt=(
        "You are a care coordinator for an Ayushman Bharat (PM-JAY) telemedicine "
        "program. Using the clinical interpretation and the guideline grounding, decide "
        "the next action. Respond ONLY with a JSON object with keys: "
        '"triage_level" (one of "routine_monitor", "teleconsult", "urgent_referral", '
        '"emergency_escalation"), "rationale" (string), "recommended_actions" (array of '
        'strings), "citations" (array of strings like "doc.pdf p3"), and '
        '"patient_message" (a short, plain-language message for the patient/caregiver in '
        "simple English). Base the decision strictly on the provided context."
    ),
    json_mode=True,
)


def run_pipeline(trajectory_summary: str, chunks: list[dict]) -> dict:
    """Run all three agents in sequence; return each agent's output."""
    context = (
        f"PATIENT DRIFT TRAJECTORY:\n{trajectory_summary}\n\n"
        f"RETRIEVED AYUSHMAN BHARAT GUIDELINES:\n{_format_chunks(chunks)}"
    )

    analysis = CLINICAL_ANALYST.run(context)

    grounding = GUIDELINE_GROUNDER.run(
        f"{context}\n\nCLINICAL INTERPRETATION:\n{analysis}"
    )

    coordination = CARE_COORDINATOR.run(
        f"{context}\n\nCLINICAL INTERPRETATION:\n{analysis}\n\n"
        f"GUIDELINE GROUNDING:\n{grounding}"
    )

    import json

    try:
        coordination_obj = json.loads(coordination)
    except json.JSONDecodeError:
        coordination_obj = {"raw": coordination}

    return {
        "model": config.GROQ_MODEL,
        "clinical_analysis": analysis,
        "guideline_grounding": grounding,
        "care_coordination": coordination_obj,
    }
