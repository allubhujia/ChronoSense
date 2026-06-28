import { useCallback, useEffect, useState } from "react";
import { fetchDashboard, fetchPatients } from "./api";
import type { DashboardResponse, Patient } from "./types";
import { deriveStatus, normalizePatientId, prettyDriver } from "./lib/clinical";
import Header from "./components/Header";
import StatusBanner from "./components/StatusBanner";
import VitalsPanel from "./components/VitalsPanel";
import DriftGauge from "./components/DriftGauge";
import TrajectoryChart from "./components/TrajectoryChart";
import ShapBars from "./components/ShapBars";
import AssessmentPanel from "./components/AssessmentPanel";
import { RefreshIcon } from "./components/icons";

export default function App() {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState(""); // free-text patient id box

  // Load the patient list once on mount, default to the first patient.
  useEffect(() => {
    fetchPatients()
      .then((list) => {
        setPatients(list);
        if (list.length > 0) setSelected(list[0].patient_id);
      })
      .catch((e) => setError(`Could not load patients: ${e.message}`));
  }, []);

  const load = useCallback(async (patientId: string) => {
    if (!patientId) return;
    setLoading(true);
    setError(null);
    try {
      setData(await fetchDashboard(patientId, true));
    } catch (e) {
      setError((e as Error).message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // Re-fetch whenever the selected patient changes (live on every click).
  useEffect(() => {
    if (selected) void load(selected);
  }, [selected, load]);

  // Submit the typed patient id (Enter or "Get Report"): normalize → select.
  const submitQuery = useCallback(() => {
    const id = normalizePatientId(query);
    if (!id) return;
    setSelected(id); // triggers the effect above → loads the report
  }, [query]);

  const status = data ? deriveStatus(data) : null;
  const demo = data?.demographics;

  return (
    <div className="min-h-screen">
      <Header />

      <main className="mx-auto max-w-7xl space-y-6 px-6 py-6">
        {/* Sub-header: title + patient selector + re-run */}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Clinician Dashboard</h1>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <span className="text-sm text-slate-500">Patient ID:</span>

              {/* Type any id (PT010, 10, 0010) → Enter or Get Report */}
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submitQuery()}
                placeholder="e.g. PT010"
                className="tabular w-32 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-semibold text-slate-800 outline-none focus:ring-2 focus:ring-blue-400"
              />
              <button
                onClick={submitQuery}
                className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-blue-700"
              >
                Get Report
              </button>

              <span className="text-sm text-slate-400">or pick:</span>
              <select
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
                className="tabular rounded-lg bg-slate-200 px-3 py-1.5 text-sm font-semibold text-slate-800 outline-none ring-1 ring-slate-300 focus:ring-blue-400"
              >
                {patients.map((p) => (
                  <option key={p.patient_id} value={p.patient_id}>
                    {p.patient_id}
                    {p.condition ? ` · ${p.condition}` : ""}
                    {p.age ? `, ${p.age}y` : ""}
                  </option>
                ))}
              </select>

              {selected && (
                <span className="text-sm text-slate-500">
                  Showing <span className="font-semibold text-slate-700">{selected}</span>
                </span>
              )}
            </div>
          </div>

          <button
            onClick={() => void load(selected)}
            disabled={loading || !selected}
            className="flex items-center gap-2 rounded-lg bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 shadow-sm ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-60"
          >
            <RefreshIcon className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            {loading ? "ASSESSING…" : "RE-RUN ASSESSMENT"}
          </button>
        </div>

        {/* Hard error (no data at all) */}
        {error && !data && (
          <div className="rounded-xl bg-red-50 p-4 text-red-700 ring-1 ring-red-200">
            {error}
          </div>
        )}

        {/* Loading skeleton on first load */}
        {loading && !data && (
          <div className="rounded-2xl bg-white p-10 text-center text-slate-500 shadow-sm">
            Analyzing 7-day trajectory… retrieving guidelines… consulting AI agents…
          </div>
        )}

        {data && status && (
          <>
            <StatusBanner
              status={status}
              lastAssessed={
                demo?.condition
                  ? `${demo.condition} · primary driver ${prettyDriver(
                      data.trajectory.primary_driver
                    )}`
                  : "just now"
              }
            />

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
              <div className="lg:col-span-2">
                <VitalsPanel latest={data.latest} />
              </div>
              <DriftGauge score={data.latest?.drift_score ?? null} />
            </div>

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
              <div className="lg:col-span-2">
                <TrajectoryChart series={data.series} />
              </div>
              <ShapBars latest={data.latest} />
            </div>

            <AssessmentPanel
              assessment={data.assessment}
              error={data.assessment_error}
              chunks={data.retrieved_chunks}
              onRetry={() => void load(selected)}
            />
          </>
        )}
      </main>
    </div>
  );
}
