import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import type { SeriesPoint } from "../types";
import { dayLabel } from "../lib/clinical";
import Card from "./Card";
import { TrendIcon } from "./icons";

export default function TrajectoryChart({ series }: { series: SeriesPoint[] }) {
  // Recharts wants the CI band as a [low, high] tuple per point ("range area").
  const data = series.map((p) => ({
    label: dayLabel(p),
    drift: p.drift_score ?? 0,
    band: [p.lower_ci ?? p.drift_score ?? 0, p.upper_ci ?? p.drift_score ?? 0],
  }));

  return (
    <Card
      title="7-Day Drift Trajectory"
      icon={<TrendIcon className="h-5 w-5" />}
      action={
        <div className="flex items-center gap-4 text-xs font-medium text-slate-500">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-blue-700" /> Drift
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-sky-200" /> Confidence
          </span>
        </div>
      }
    >
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid vertical={false} strokeDasharray="4 4" stroke="#e5e7eb" />
            <XAxis
              dataKey="label"
              tickLine={false}
              axisLine={false}
              tick={{ fill: "#94a3b8", fontSize: 12 }}
            />
            <YAxis
              domain={[0, 1]}
              tickLine={false}
              axisLine={false}
              tick={{ fill: "#cbd5e1", fontSize: 11 }}
            />
            <Area
              type="monotone"
              dataKey="band"
              stroke="none"
              fill="#bae6fd"
              fillOpacity={0.5}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="drift"
              stroke="#1d4ed8"
              strokeWidth={3}
              dot={{ r: 3, fill: "#1d4ed8" }}
              activeDot={{ r: 5 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
