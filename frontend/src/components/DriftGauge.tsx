import Card from "./Card";
import { GaugeIcon } from "./icons";

const THRESHOLD = 0.5;

/** Semicircular gauge for the 0..1 drift score, matching the mockup. */
export default function DriftGauge({ score }: { score: number | null }) {
  const value = Math.max(0, Math.min(1, score ?? 0));

  // Semicircle: 180° sweep. Radius/geometry for the arc.
  const r = 80;
  const cx = 100;
  const cy = 100;
  const circumference = Math.PI * r; // half circle length
  const dash = circumference * value;

  const exceeded = value >= THRESHOLD;

  return (
    <Card title="Drift Gauge" icon={<GaugeIcon className="h-5 w-5" />}>
      <div className="flex flex-col items-center">
        <svg viewBox="0 0 200 120" className="w-full max-w-[260px]">
          <defs>
            <linearGradient id="driftGrad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#fbbf24" />
              <stop offset="60%" stopColor="#f97316" />
              <stop offset="100%" stopColor="#dc2626" />
            </linearGradient>
          </defs>
          {/* track */}
          <path
            d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
            fill="none"
            stroke="#e5e7eb"
            strokeWidth="16"
            strokeLinecap="round"
          />
          {/* value */}
          <path
            d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
            fill="none"
            stroke="url(#driftGrad)"
            strokeWidth="16"
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circumference}`}
          />
        </svg>
        <div className="-mt-12 text-center">
          <p className="tabular text-4xl font-bold text-slate-900">{value.toFixed(2)}</p>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Drift Score
          </p>
        </div>
        <p className={`mt-4 text-sm ${exceeded ? "text-orange-600" : "text-slate-500"}`}>
          {exceeded ? "Threshold exceeded" : "Within threshold"}: {THRESHOLD.toFixed(2)}
        </p>
      </div>
    </Card>
  );
}
