import type { Assessment, GuidelineChunk } from "../types";
import Card from "./Card";
import { CheckIcon, ChatIcon, SparkleIcon, SendIcon } from "./icons";

interface Props {
  assessment: Assessment | null;
  error: string | null;
  chunks: GuidelineChunk[];
  onRetry: () => void;
}

export default function AssessmentPanel({ assessment, error, chunks, onRetry }: Props) {
  const cc = assessment?.care_coordination;

  // Citations: prefer the agent's own list, else derive from retrieved chunks.
  const citations =
    cc?.citations && cc.citations.length > 0
      ? cc.citations
      : chunks.slice(0, 3).map((c) => `${c.source_document ?? "guideline"} p.${c.page ?? "?"}`);

  const rationale = cc?.rationale ?? assessment?.clinical_analysis;
  const actions = cc?.recommended_actions ?? [];
  const patientMessage = cc?.patient_message;

  return (
    <Card
      title="AI Clinical Assessment"
      icon={<SparkleIcon className="h-5 w-5" />}
      className="border-t-4 border-blue-100"
    >
      {error ? (
        <div className="flex flex-col items-start gap-3 rounded-xl bg-amber-50 p-5 text-amber-800">
          <p className="font-medium">AI assessment unavailable.</p>
          <p className="text-sm text-amber-700">{error}</p>
          <button
            onClick={onRetry}
            className="rounded-lg bg-amber-600 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-700"
          >
            Retry assessment
          </button>
        </div>
      ) : !assessment ? (
        <p className="text-slate-400">No assessment yet.</p>
      ) : (
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
          {/* Left: rationale + actions */}
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Rationale
            </p>
            <p className="mt-2 leading-relaxed text-slate-700">{rationale}</p>

            {citations.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {citations.map((c, i) => (
                  <span
                    key={i}
                    className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 ring-1 ring-slate-200"
                  >
                    {c}
                  </span>
                ))}
              </div>
            )}

            {actions.length > 0 && (
              <>
                <p className="mt-6 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Recommended Actions
                </p>
                <ul className="mt-3 space-y-2.5">
                  {actions.map((a, i) => (
                    <li key={i} className="flex items-start gap-2.5 text-slate-700">
                      <CheckIcon className="mt-0.5 h-5 w-5 shrink-0 text-blue-600" />
                      <span>{a}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>

          {/* Right: patient-friendly message */}
          {patientMessage && (
            <div className="rounded-xl bg-sky-50/70 p-5">
              <div className="flex items-center gap-2 text-teal-700">
                <ChatIcon className="h-5 w-5" />
                <h3 className="font-semibold">Patient-Friendly Message</h3>
              </div>
              <p className="mt-3 italic leading-relaxed text-slate-600">“{patientMessage}”</p>
              <button className="mt-5 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-teal-700 hover:text-teal-800">
                <SendIcon className="h-4 w-4" />
                Send to patient tablet
              </button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
