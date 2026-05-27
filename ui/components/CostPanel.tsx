import type { RunSummary } from "@/lib/api";

export function CostPanel({ summary }: { summary: RunSummary }) {
  const tokens = summary.total_tokens_in + summary.total_tokens_out;
  return (
    <div
      className="rounded border border-zinc-200 p-3 text-sm dark:border-zinc-800"
      data-testid="cost-panel"
    >
      <div className="text-xs uppercase tracking-wide text-zinc-500">Cost</div>
      <div className="mt-1 text-lg font-semibold">${summary.total_cost_usd.toFixed(3)}</div>
      <div className="mt-1 text-xs text-zinc-500">
        {tokens.toLocaleString()} tokens · {summary.agent_count} agents · {summary.topology ?? "—"}
      </div>
    </div>
  );
}
