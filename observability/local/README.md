# Observability — LOCAL mode (no Docker)

Run Prometheus + Grafana directly on your machine, wired to the API on
`localhost`. Docker mode is unchanged and lives one level up
(`docker compose up` uses `../prometheus` + `../grafana`, which target the
Docker service names `api` / `prometheus`).

| | Docker mode | Local mode (this folder) |
|--|-------------|--------------------------|
| Prometheus target | `api:8001` | `localhost:8001` |
| Grafana datasource | `http://prometheus:9090` | `http://localhost:9090` |
| Config used | `../prometheus/prometheus.yml` | `prometheus.local.yml` |
| How to run | `docker compose up -d` | `bash run_local.sh` |
| Alerts + dashboard | shared (`../prometheus/alerts.yml`, `../grafana/dashboards/`) | **same shared files** |

## 1. Install the binaries (once, in WSL)

```bash
# Prometheus + Grafana via apt (Ubuntu/WSL)
sudo apt-get update
sudo apt-get install -y prometheus

# Grafana (official APT repo)
sudo apt-get install -y apt-transport-https software-properties-common
wget -q -O - https://apt.grafana.com/gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/grafana.gpg
echo "deb [signed-by=/usr/share/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt-get update && sudo apt-get install -y grafana
```

> Prefer not to use apt? Download the binaries from prometheus.io/download and
> grafana.com/grafana/download, unzip, and add them to your `PATH`. If Grafana's
> assets aren't at `/usr/share/grafana`, run with
> `GRAFANA_HOME=/path/to/grafana bash run_local.sh`.

## 2. Run

```bash
# Terminal 1 — the API (must be up first, exposes /metrics)
cd /mnt/c/VIT_CHENNAI/Computer_science/Internship/ChronoSense
source .venv/bin/activate
uvicorn temporal_rag.app:app --port 8001

# Terminal 2 — Prometheus + Grafana
bash observability/local/run_local.sh
```

Then open:

| Service | URL |
|---------|-----|
| 📊 Grafana | http://localhost:3000 (admin / admin) |
| 📈 Prometheus | http://localhost:9090 |
| 🔌 API metrics | http://localhost:8001/metrics |

The **"ChronoSense — Observability"** dashboard is auto-provisioned. Generate
traffic from the React dashboard (or hit `/dashboard`) and the panels fill in.

Stop everything with **Ctrl+C** in Terminal 2. All local state is kept under
`observability/local/.data/` (gitignored) — delete it for a clean slate.

## Note on absolute paths

`prometheus.local.yml` and the Grafana dashboard provider reference the shared
`alerts.yml` / dashboards by **absolute path**
(`/mnt/c/VIT_CHENNAI/.../observability/...`). If you move the repo, update those
two paths.
