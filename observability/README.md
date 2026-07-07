# ChronoSense — Observability (Prometheus + Grafana)

The Observability Layer from the cloud architecture: the API exports Prometheus
metrics, Prometheus scrapes + alerts on them, and Grafana visualises them with
live line charts, bar graphs, stat tiles, and threshold-based alert panels.

```
FastAPI /metrics ──scrape──▶ Prometheus :9090 ──query──▶ Grafana :3000
 (metrics.py)                (+ alert rules)              (dashboards)
```

## The four metrics

| Question | Metric | Type |
|----------|--------|------|
| How many requests came in? | `chronosense_http_requests_total{method,endpoint,status}` | Counter |
| How long did each request take? | `chronosense_http_request_duration_seconds{method,endpoint}` | Histogram |
| How many drift events fired? | `chronosense_drift_events_total{triage}` | Counter |
| How long did Groq take? | `chronosense_groq_request_duration_seconds{agent}` | Histogram |

Plus `chronosense_groq_requests_total{agent,status}` for Groq call counts/errors.

Instrumentation lives in [`metrics.py`](metrics.py):
- `setup_metrics(app)` — HTTP middleware (count + latency) and the `/metrics` route. Called in `temporal_rag/app.py`.
- `record_drift_event(triage)` — called in the `/dashboard` handler after each assessment.
- `track_groq(agent)` — context manager wrapping each agent's Groq call in `temporal_rag/agents.py`.

All of it is import-safe: if `prometheus_client` is absent, it no-ops.

## Grafana dashboard

`grafana/dashboards/chronosense.json` (auto-provisioned) has 9 panels:

- **Stat tiles** — Total Requests, Drift Events Fired
- **Alert panels** (red/green thresholds) — Error Rate (>10%), Groq p95 latency (>10s)
- **Line charts** — Requests/sec by endpoint, Request latency p95, Groq latency p95 by agent
- **Bar graph** — Drift events by triage level
- **Bar gauge** — Groq calls by agent

Live (5s refresh). Datasource + dashboards are provisioned automatically — zero manual setup.

## Alert rules

`prometheus/alerts.yml` fires alerts (visible at http://localhost:9090/alerts):
`HighRequestLatency`, `HighErrorRate`, `SlowGroqResponses`, `GroqCallFailures`.

## Run it (via Docker)

Prometheus and Grafana are services in the root `docker-compose.yaml`:

```bash
docker compose up -d
```

| Service | URL | Login |
|---------|-----|-------|
| Grafana | http://localhost:3000 | admin / admin (anonymous viewing on) |
| Prometheus | http://localhost:9090 | — |
| API metrics | http://localhost:8001/metrics | — |

The **"ChronoSense — Observability"** dashboard appears automatically in Grafana.
Generate traffic by using the dashboard at :5173 (or hitting `/dashboard`), and
the panels fill in within seconds.

## Run locally (without Docker)

Metrics work as soon as the API runs — the endpoint is at
`http://localhost:8001/metrics`. To see the Grafana UI you still need Prometheus
+ Grafana running (Docker is easiest); point Prometheus at `host.docker.internal:8001`
instead of `api:8001` if the API is on the host.
