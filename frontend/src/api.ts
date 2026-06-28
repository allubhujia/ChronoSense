import type { DashboardResponse, Patient } from "./types";

// All requests go through Vite's /api proxy → FastAPI on :8001 (see vite.config.ts).
const BASE = "/api";

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function fetchPatients(): Promise<Patient[]> {
  const res = await fetch(`${BASE}/patients`);
  const data = await jsonOrThrow<{ patients: Patient[] }>(res);
  return data.patients;
}

export async function fetchDashboard(
  patientId: string,
  runAgents = true
): Promise<DashboardResponse> {
  const res = await fetch(`${BASE}/dashboard`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patient_id: patientId, run_agents: runAgents }),
  });
  return jsonOrThrow<DashboardResponse>(res);
}
