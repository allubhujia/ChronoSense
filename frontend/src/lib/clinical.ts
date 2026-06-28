import type { DashboardResponse, SeriesPoint } from "../types";

// ── Triage / status mapping ──────────────────────────────────────────────────
export type StatusKind = "stable" | "monitoring" | "deteriorating" | "critical";

export interface StatusInfo {
  kind: StatusKind;
  label: string;
  // Tailwind classes for the banner.
  bar: string; // left accent bar
  bg: string; // banner background
  text: string; // heading text colour
  iconBg: string;
}

const STATUS: Record<StatusKind, StatusInfo> = {
  stable: {
    kind: "stable",
    label: "Stable",
    bar: "bg-emerald-500",
    bg: "bg-emerald-50",
    text: "text-emerald-700",
    iconBg: "bg-emerald-100 text-emerald-600",
  },
  monitoring: {
    kind: "monitoring",
    label: "Monitoring",
    bar: "bg-sky-500",
    bg: "bg-sky-50",
    text: "text-sky-700",
    iconBg: "bg-sky-100 text-sky-600",
  },
  deteriorating: {
    kind: "deteriorating",
    label: "Deteriorating",
    bar: "bg-orange-500",
    bg: "bg-orange-50",
    text: "text-orange-600",
    iconBg: "bg-orange-100 text-orange-600",
  },
  critical: {
    kind: "critical",
    label: "Critical",
    bar: "bg-red-600",
    bg: "bg-red-50",
    text: "text-red-700",
    iconBg: "bg-red-100 text-red-600",
  },
};

const TRIAGE_TO_STATUS: Record<string, StatusKind> = {
  routine_monitor: "stable",
  teleconsult: "monitoring",
  urgent_referral: "deteriorating",
  emergency_escalation: "critical",
};

/** Prefer the agents' triage_level; fall back to the latest drift score. */
export function deriveStatus(data: DashboardResponse): StatusInfo {
  const triage = data.assessment?.care_coordination?.triage_level;
  if (triage && TRIAGE_TO_STATUS[triage]) return STATUS[TRIAGE_TO_STATUS[triage]];

  const drift = data.latest?.drift_score ?? 0;
  if (drift >= 0.6) return STATUS.critical;
  if (drift >= 0.4) return STATUS.deteriorating;
  if (drift >= 0.2) return STATUS.monitoring;
  return STATUS.stable;
}

// ── Vital-sign abnormality (drives bar fill + colour) ────────────────────────
const HR_RANGE: [number, number] = [60, 100];
const RR_RANGE: [number, number] = [12, 20];

export function abnormality(value: number, [low, high]: [number, number], scale: number): number {
  if (value < low) return Math.min(1, (low - value) / scale);
  if (value > high) return Math.min(1, (value - high) / scale);
  return 0;
}

export interface VitalView {
  label: string;
  value: string;
  unit: string;
  /** 0..1 bar fill */
  fill: number;
  /** true when out of normal range → render red */
  abnormal: boolean;
}

export function vitalViews(latest: SeriesPoint | null): VitalView[] {
  const hr = latest?.heart_rate ?? 0;
  const rr = latest?.respiratory_rate ?? 0;
  const mv = latest?.movement_score ?? 0;

  const hrAb = abnormality(hr, HR_RANGE, 40);
  const rrAb = abnormality(rr, RR_RANGE, 12);
  const mvLevel = Math.min(1, mv / 1.0);

  return [
    {
      label: "Heart Rate",
      value: hr ? hr.toFixed(0) : "—",
      unit: "bpm",
      fill: Math.max(0.15, hr ? Math.min(1, hr / 140) : 0),
      abnormal: hrAb > 0,
    },
    {
      label: "Resp Rate",
      value: rr ? rr.toFixed(0) : "—",
      unit: "br/m",
      fill: Math.max(0.15, rr ? Math.min(1, rr / 35) : 0),
      abnormal: rrAb > 0,
    },
    {
      label: "Movement",
      value: movementLabel(mv),
      unit: "",
      fill: Math.max(0.1, mvLevel),
      abnormal: false,
    },
  ];
}

export function movementLabel(mv: number): string {
  if (mv >= 0.7) return "High";
  if (mv >= 0.4) return "Moderate";
  return "Low";
}

// ── Misc formatters ──────────────────────────────────────────────────────────
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function dayLabel(point: SeriesPoint): string {
  if (point.date) {
    const d = new Date(point.date);
    if (!Number.isNaN(d.getTime())) return WEEKDAYS[d.getDay()].toUpperCase();
  }
  return `DAY ${point.day}`;
}

/** Normalize free-text patient input into the canonical PTxxx id.
 *  "10" → "PT010", "0010" → "PT010", "pt10" → "PT010", "PT010" → "PT010". */
export function normalizePatientId(raw: string): string {
  const trimmed = raw.trim().toUpperCase();
  if (!trimmed) return "";
  const digits = trimmed.replace(/[^0-9]/g, "");
  if (!digits) return trimmed; // no number → return as-is (let backend 404)
  return `PT${digits.padStart(3, "0")}`;
}

export function prettyDriver(driver?: string | null): string {
  if (!driver) return "—";
  const map: Record<string, string> = {
    HR: "Heart Rate",
    RR: "Respiratory Rate",
    Movement: "Movement",
  };
  return map[driver] ?? driver;
}
