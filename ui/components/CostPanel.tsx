import type { RunSummary } from "@/lib/api";

export function CostPanel({ summary }: { summary: RunSummary }) {
  const tokens = summary.total_tokens_in + summary.total_tokens_out;
  // A fully-local run cost $0 EXTERNALLY — but pi reports $0.000 for local
  // models because they aren't in the price table, which reads as "free /
  // unknown" on stage. Label it honestly as sovereign instead of $0.000.
  const wallClock =
    summary.wall_clock_s != null ? `${summary.wall_clock_s.toFixed(1)}s` : "—";
  return (
    <div
      className="rounded border border-zinc-200 p-3 text-sm dark:border-zinc-800"
      data-testid="cost-panel"
    >
      <div className="text-xs uppercase tracking-wide text-zinc-500">Cost</div>
      {summary.sovereign ? (
        <div className="mt-1 text-lg font-semibold" data-testid="cost-amount">
          Local · sovereign · $0 external
        </div>
      ) : (
        <div className="mt-1 text-lg font-semibold" data-testid="cost-amount">
          ${summary.total_cost_usd.toFixed(3)}
        </div>
      )}
      <div className="mt-1 text-xs text-zinc-500">
        {tokens.toLocaleString()} tokens · <span data-testid="wall-clock">{wallClock}</span> ·{" "}
        {summary.agent_count} agents · {summary.topology ?? "—"}
      </div>
    </div>
  );
}
