import type { SeriesPoint } from "../types";
import { vitalViews } from "../lib/clinical";
import Card from "./Card";
import { RadarIcon } from "./icons";

export default function VitalsPanel({ latest }: { latest: SeriesPoint | null }) {
  const vitals = vitalViews(latest);

  return (
    <Card
      title="Latest Contactless Vitals"
      icon={<RadarIcon className="h-5 w-5" />}
      action={
        <span className="rounded-md bg-teal-50 px-2.5 py-1 text-xs font-semibold text-teal-700">
          Contactless Radar
        </span>
      }
    >
      <div className="grid grid-cols-3 gap-4">
        {vitals.map((v) => (
          <div key={v.label} className="rounded-xl bg-slate-50 p-4 ring-1 ring-slate-200/60">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              {v.label}
            </p>
            <p className="mt-2 flex items-baseline gap-1">
              <span
                className={`tabular text-4xl font-bold ${
                  v.abnormal ? "text-red-600" : "text-slate-900"
                }`}
              >
                {v.value}
              </span>
              {v.unit && <span className="text-sm text-slate-500">{v.unit}</span>}
            </p>
            <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
              <div
                className={`h-full rounded-full ${v.abnormal ? "bg-red-500" : "bg-blue-600"}`}
                style={{ width: `${Math.round(v.fill * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
