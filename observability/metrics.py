"""Prometheus instrumentation for the ChronoSense Temporal RAG API.

Exposes four things the project cares about (mirrors the Observability Layer in
the cloud architecture):

  1. How many requests came in        → chronosense_http_requests_total
  2. How long each request took        → chronosense_http_request_duration_seconds
  3. How many drift events fired       → chronosense_drift_events_total
  4. How long Groq took to respond     → chronosense_groq_request_duration_seconds

`setup_metrics(app)` wires an HTTP middleware (count + latency) and a /metrics
endpoint onto the FastAPI app. `record_drift_event()` and `track_groq()` are
called from the pipeline/agents to record the domain-specific metrics.

Import-safe: if prometheus_client is missing, everything degrades to no-ops so
the app still runs.
"""

from __future__ import annotations

import contextlib
import time

from starlette.responses import Response

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _ENABLED = True
except Exception:  # prometheus_client not installed
    _ENABLED = False


if _ENABLED:
    # 1 + 2 — HTTP traffic: count and latency, labelled by endpoint.
    REQUEST_COUNT = Counter(
        "chronosense_http_requests_total",
        "Total HTTP requests processed by the API.",
        ["method", "endpoint", "status"],
    )
    REQUEST_LATENCY = Histogram(
        "chronosense_http_request_duration_seconds",
        "HTTP request latency in seconds.",
        ["method", "endpoint"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 13, 21),
    )

    # 3 — Drift events: one per drift assessment, labelled by resulting triage.
    DRIFT_EVENTS = Counter(
        "chronosense_drift_events_total",
        "Number of drift assessments processed, by triage level.",
        ["triage"],
    )

    # 4 — Groq API: latency + count per agent in the multi-agent chain.
    GROQ_LATENCY = Histogram(
        "chronosense_groq_request_duration_seconds",
        "Groq API call latency in seconds, per agent.",
        ["agent"],
        buckets=(0.25, 0.5, 1, 2, 3, 5, 8, 13, 21, 34),
    )
    GROQ_REQUESTS = Counter(
        "chronosense_groq_requests_total",
        "Total Groq API calls, per agent and outcome.",
        ["agent", "status"],
    )

    # 5 — LLM/RAG output quality: latest groundedness + citation accuracy (0-1).
    GROUNDEDNESS = Gauge(
        "chronosense_groundedness_score",
        "Latest LLM groundedness score (0-1): fraction of rationale claims "
        "supported by the retrieved guideline chunks.",
    )
    CITATION_ACCURACY = Gauge(
        "chronosense_citation_accuracy",
        "Latest citation accuracy (0-1): fraction of the agent's citations that "
        "point at an actually-retrieved chunk.",
    )


def setup_metrics(app) -> None:
    """Attach the request-timing middleware and the /metrics endpoint."""
    if not _ENABLED:
        return

    @app.middleware("http")
    async def _prometheus_middleware(request, call_next):
        # Don't measure the scrape endpoint itself.
        if request.url.path == "/metrics":
            return await call_next(request)

        endpoint = request.url.path
        method = request.method
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            REQUEST_LATENCY.labels(method, endpoint).observe(time.perf_counter() - start)
            REQUEST_COUNT.labels(method, endpoint, "500").inc()
            raise

        REQUEST_LATENCY.labels(method, endpoint).observe(time.perf_counter() - start)
        REQUEST_COUNT.labels(method, endpoint, str(status)).inc()
        return response

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def record_drift_event(triage: str | None = None) -> None:
    """Increment the drift-event counter (labelled by triage level)."""
    if _ENABLED:
        DRIFT_EVENTS.labels(triage or "unknown").inc()


def record_evaluation(groundedness: float | None = None,
                      citation_accuracy: float | None = None) -> None:
    """Record the latest LLM/RAG output-quality scores (0-1)."""
    if not _ENABLED:
        return
    if groundedness is not None:
        GROUNDEDNESS.set(groundedness)
    if citation_accuracy is not None:
        CITATION_ACCURACY.set(citation_accuracy)


@contextlib.contextmanager
def track_groq(agent: str):
    """Time a Groq API call and record its outcome, labelled by agent name."""
    if not _ENABLED:
        yield
        return

    start = time.perf_counter()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        GROQ_LATENCY.labels(agent).observe(time.perf_counter() - start)
        GROQ_REQUESTS.labels(agent, status).inc()
