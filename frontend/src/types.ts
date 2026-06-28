// Mirrors the JSON returned by temporal_rag/app.py. Keeping these in sync with
// the backend is the type contract for the whole dashboard.

export interface Patient {
  patient_id: string;
  condition?: string;
  age?: number;
  primary_driver?: string;
}

export interface SeriesPoint {
  day: number;
  date: string | null;
  heart_rate: number | null;
  respiratory_rate: number | null;
  movement_score: number | null;
  drift_score: number | null;
  lower_ci: number | null;
  upper_ci: number | null;
  shap_hr: number | null;
  shap_rr: number | null;
  shap_movement: number | null;
}

export interface TrajectoryAnalysis {
  patient_id: string;
  daily_drift: number[];
  daily_primary: (string | null)[];
  primary_driver: string;
  primary_driver_days: number;
  primary_avg_attribution: number;
  secondary_driver: string | null;
  secondary_from_day: number | null;
  trend: "accelerating" | "decelerating" | "fluctuating" | string;
  demographics: Record<string, unknown>;
  summary: string;
  retrieval_query: string;
}

export interface GuidelineChunk {
  text: string;
  source_document: string | null;
  specialty: string | null;
  page: number | null;
  chunk_index: number | null;
  distance: number;
  similarity: number;
}

export type TriageLevel =
  | "routine_monitor"
  | "teleconsult"
  | "urgent_referral"
  | "emergency_escalation";

export interface CareCoordination {
  triage_level?: TriageLevel | string;
  rationale?: string;
  recommended_actions?: string[];
  citations?: string[];
  patient_message?: string;
  raw?: string;
}

export interface Assessment {
  model: string;
  clinical_analysis: string;
  guideline_grounding: string;
  care_coordination: CareCoordination;
}

export interface DashboardResponse {
  patient_id: string;
  demographics: Patient;
  records_analyzed: number;
  series: SeriesPoint[];
  latest: SeriesPoint | null;
  trajectory: TrajectoryAnalysis;
  trajectory_summary: string;
  retrieval_query: string;
  retrieved_chunks: GuidelineChunk[];
  assessment: Assessment | null;
  assessment_error: string | null;
}
