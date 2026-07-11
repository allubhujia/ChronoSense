#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Run Prometheus + Grafana LOCALLY (no Docker), wired to the API on localhost.
#
# Prereq: the API must be running first  (uvicorn temporal_rag.app:app --port 8001)
#         and the prometheus + grafana binaries must be installed (see README).
#
# Usage:  bash observability/local/run_local.sh
# Stop:   Ctrl+C  (kills both)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="$HERE/.data"                      # local, writable state (gitignored)
mkdir -p "$DATA/prometheus" "$DATA/grafana/data" "$DATA/grafana/logs"

# apt installs Prometheus/Grafana as auto-starting SYSTEM SERVICES that grab
# ports 9090/3000 — which collides with the instances we launch here. Stop them
# so this script owns the ports. (Harmless if they aren't running.)
if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-active --quiet prometheus 2>/dev/null \
     || systemctl is-active --quiet grafana-server 2>/dev/null; then
    echo "ℹ Stopping the apt-installed prometheus/grafana services (need sudo once)..."
    sudo systemctl stop prometheus grafana-server 2>/dev/null || true
    sudo systemctl disable prometheus grafana-server 2>/dev/null || true
  fi
fi

# ── 1. Prometheus ────────────────────────────────────────────────────────────
if ! command -v prometheus >/dev/null 2>&1; then
  echo "❌ prometheus binary not found. Install it (see observability/local/README.md)."
  exit 1
fi
echo "▶ Starting Prometheus on http://localhost:9090 ..."
prometheus \
  --config.file="$HERE/prometheus.local.yml" \
  --storage.tsdb.path="$DATA/prometheus" \
  --web.listen-address="0.0.0.0:9090" &
PROM_PID=$!

# ── 2. Grafana ───────────────────────────────────────────────────────────────
# Grafana reads these env vars; we point provisioning at the LOCAL folder and
# keep all state under .data so nothing needs root.
export GF_PATHS_PROVISIONING="$HERE/grafana/provisioning"
export GF_PATHS_DATA="$DATA/grafana/data"
export GF_PATHS_LOGS="$DATA/grafana/logs"
export GF_PATHS_PLUGINS="$DATA/grafana/plugins"       # writable → no /var/lib denial
export GF_PLUGINS_PREINSTALL_DISABLED="true"          # skip the Loki-explore auto-install
mkdir -p "$DATA/grafana/plugins"
export GF_SECURITY_ADMIN_USER="admin"
export GF_SECURITY_ADMIN_PASSWORD="admin"
export GF_AUTH_ANONYMOUS_ENABLED="true"
export GF_AUTH_ANONYMOUS_ORG_ROLE="Viewer"

# Homepath is where Grafana's static assets live (default for apt install).
GRAFANA_HOME="${GRAFANA_HOME:-/usr/share/grafana}"

start_grafana() {
  # --config points Grafana at OUR ini so it never reads the root-owned
  # /etc/grafana/grafana.ini (permission denied for a normal user).
  if command -v grafana >/dev/null 2>&1; then
    grafana server --homepath "$GRAFANA_HOME" --config "$HERE/grafana.ini" &   # Grafana 10+
  elif command -v grafana-server >/dev/null 2>&1; then
    grafana-server --homepath "$GRAFANA_HOME" --config "$HERE/grafana.ini" &   # older
  else
    echo "❌ grafana binary not found. Install it (see observability/local/README.md)."
    kill "$PROM_PID" 2>/dev/null || true
    exit 1
  fi
}
echo "▶ Starting Grafana on http://localhost:3000  (admin / admin) ..."
start_grafana
GRAF_PID=$!

# ── Cleanup on exit ──────────────────────────────────────────────────────────
cleanup() {
  echo -e "\n⏹  Stopping Prometheus + Grafana ..."
  kill "$PROM_PID" "$GRAF_PID" 2>/dev/null || true
}
trap cleanup INT TERM

echo ""
echo "  📈 Prometheus : http://localhost:9090"
echo "  📊 Grafana    : http://localhost:3000   (dashboard: ChronoSense — Observability)"
echo "  🔌 API metrics: http://localhost:8001/metrics"
echo ""
echo "Press Ctrl+C to stop both."
wait
