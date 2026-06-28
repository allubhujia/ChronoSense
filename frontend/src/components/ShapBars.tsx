import type { SeriesPoint } from "../types";
import Card from "./Card";
import { BarsIcon } from "./icons";

interface Row {
  label: string;
  value: number;
}

/** Diverging horizontal bars for the latest per-feature SHAP attribution.
 * Positive (pushes drift up) renders red; negative (protective) renders teal. */
export default function ShapBars({ latest }: { latest: SeriesPoint | null }) {
  const rows: Row[] = [
    { label: "Respiratory Rate", value: latest?.shap_rr ?? 0 },
    { label: "Heart Rate", value: latest?.shap_hr ?? 0 },
    { label: "Movement", value: latest?.shap_movement ?? 0 },
  ];

  const maxAbs = Math.max(0.001, ...rows.map((r) => Math.abs(r.value)));

  return (
    <Card title="SHAP Attribution" icon={<BarsIcon className="h-5 w-5" />}>
      <div className="space-y-5">
        {rows.map((r) => {
          const positive = r.value >= 0;
          const width = (Math.abs(r.value) / maxAbs) * 100;
          return (
            <div key={r.label}>
              <div className="mb-1.5 flex items-center justify-between text-sm">
                <span className="font-medium text-slate-700">{r.label}</span>
                <span
                  className={`tabular font-semibold ${
                    positive ? "text-red-600" : "text-teal-600"
                  }`}
                >
                  {positive ? "+" : "−"}
                  {Math.abs(r.value).toFixed(2)}
                </span>
              </div>
              {/* center line; bar grows right (positive) or left (negative) */}
              <div className="relative h-2.5 w-full rounded-full bg-slate-200">
                <div className="absolute left-1/2 top-0 h-full w-px bg-slate-300" />
                <div
                  className={`absolute top-0 h-full rounded-full ${
                    positive ? "left-1/2 bg-red-500" : "right-1/2 bg-teal-500"
                  }`}
                  style={{ width: `${width / 2}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
      <p className="mt-5 text-sm italic text-slate-500">
        Impact on total drift score contribution.
      </p>
    </Card>
  );
}
