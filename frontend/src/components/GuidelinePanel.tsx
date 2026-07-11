import { useEffect, useState } from "react";
import { sendChunkFeedback } from "../api";
import type { ChunkRating, GuidelineChunk } from "../types";
import Card from "./Card";
import { BookIcon, ThumbDownIcon, ThumbUpIcon } from "./icons";

interface Props {
  chunks: GuidelineChunk[];
  patientId: string;
  triageLevel: string | null;
}

/** Retrieved guideline chunks with a doctor feedback loop: 👍 relevant /
 * 👎 not relevant per chunk. Ratings are stored per (chunk, patient) and later
 * folded into retrieval weights by update_chunk_weights.py. */
export default function GuidelinePanel({ chunks, patientId, triageLevel }: Props) {
  // chunk_id → rating chosen in this session (re-click overwrites server-side).
  const [rated, setRated] = useState<Record<string, ChunkRating>>({});
  const [busy, setBusy] = useState<string | null>(null);

  // New patient/report → clear the local rating highlights.
  useEffect(() => setRated({}), [patientId, chunks]);

  const rate = async (chunk: GuidelineChunk, rating: ChunkRating) => {
    setBusy(chunk.chunk_id);
    try {
      await sendChunkFeedback({
        chunk_id: chunk.chunk_id,
        rating,
        patient_id: patientId,
        triage_level: triageLevel,
        similarity_at_retrieval: chunk.similarity,
        source_document: chunk.source_document,
        page: chunk.page,
      });
      setRated((r) => ({ ...r, [chunk.chunk_id]: rating }));
    } catch {
      // Swallow — feedback is best-effort; the demo must not break on it.
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card
      title="Retrieved Guidelines"
      icon={<BookIcon className="h-5 w-5" />}
      action={
        <span className="text-xs font-medium text-slate-400">
          Rate each chunk's clinical relevance — your feedback tunes retrieval
        </span>
      }
    >
      <div className="space-y-4">
        {chunks.length === 0 && (
          <p className="text-sm text-slate-400">No guideline chunks retrieved.</p>
        )}
        {chunks.map((c, i) => {
          const choice = rated[c.chunk_id];
          return (
            <div
              key={c.chunk_id}
              className="rounded-xl bg-slate-50 p-4 ring-1 ring-slate-200/60"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2 text-xs font-medium">
                    <span className="rounded bg-blue-100 px-1.5 py-0.5 text-blue-700">
                      #{i + 1}
                    </span>
                    <span className="text-slate-600">
                      {c.source_document ?? "guideline"} · p.{c.page ?? "?"}
                    </span>
                    <span className="tabular text-slate-400">
                      similarity {c.similarity.toFixed(2)}
                    </span>
                    {c.weight !== 1 && (
                      <span
                        className={`tabular rounded px-1.5 py-0.5 ${
                          c.weight < 1
                            ? "bg-orange-100 text-orange-700"
                            : "bg-emerald-100 text-emerald-700"
                        }`}
                        title="Feedback-learned retrieval weight"
                      >
                        weight {c.weight.toFixed(2)}
                      </span>
                    )}
                  </div>
                  <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-slate-600">
                    {c.text}
                  </p>
                </div>

                {/* 👍 / 👎 — was this chunk clinically relevant here? */}
                <div className="flex shrink-0 items-center gap-1.5">
                  <button
                    onClick={() => void rate(c, "up")}
                    disabled={busy === c.chunk_id}
                    title="Clinically relevant"
                    className={`rounded-lg p-2 ring-1 transition-colors ${
                      choice === "up"
                        ? "bg-emerald-100 text-emerald-700 ring-emerald-300"
                        : "bg-white text-slate-400 ring-slate-200 hover:text-emerald-600"
                    }`}
                  >
                    <ThumbUpIcon className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => void rate(c, "down")}
                    disabled={busy === c.chunk_id}
                    title="Not relevant for this patient"
                    className={`rounded-lg p-2 ring-1 transition-colors ${
                      choice === "down"
                        ? "bg-red-100 text-red-700 ring-red-300"
                        : "bg-white text-slate-400 ring-slate-200 hover:text-red-600"
                    }`}
                  >
                    <ThumbDownIcon className="h-4 w-4" />
                  </button>
                </div>
              </div>
              {choice && (
                <p className="mt-2 text-xs font-medium text-slate-400">
                  Recorded — thank you. Click the other thumb to change it.
                </p>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
