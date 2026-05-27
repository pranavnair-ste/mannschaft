import type { Reliability } from "@/lib/api";

// Four-dimension reliability per HARNESS_ARCHITECTURE.md §5. Scores are derived
// heuristics from event stats (see backend reliability.py); null renders "—".
const DIMS: (keyof Reliability)[] = ["consistency", "robustness", "predictability", "safety"];

export function ReliabilityGauges({ scores }: { scores: Reliability }) {
  return (
    <div className="grid grid-cols-2 gap-2" data-testid="reliability-gauges">
      {DIMS.map((dim) => {
        const v = scores[dim];
        const pct = v != null ? Math.round(v * 100) : null;
        return (
          <div key={dim} className="rounded border border-zinc-200 p-2 dark:border-zinc-800">
            <div className="text-xs uppercase tracking-wide text-zinc-500">{dim}</div>
            <div className="mt-1 text-lg font-semibold">{pct != null ? `${pct}%` : "—"}</div>
            <div className="mt-1 h-1 w-full rounded bg-zinc-100 dark:bg-zinc-800">
              <div
                className="h-1 rounded bg-emerald-500"
                style={{ width: pct != null ? `${pct}%` : "0%" }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
