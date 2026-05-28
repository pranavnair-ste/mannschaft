import type { CorpusHealth } from "@/lib/api";

export function CorpusHealthGauge({ health }: { health: CorpusHealth }) {
  const pct = Math.min(100, Math.round(health.pct_of_cap * 100));
  const tone = pct > 100 ? "bg-red-500" : pct > 85 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="rounded border border-zinc-200 p-3 dark:border-zinc-800" data-testid="corpus-gauge">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-medium">Token budget</h2>
        <span className="text-2xl font-semibold tabular-nums" data-testid="corpus-pct">
          {pct}%
        </span>
      </div>
      <div className="mt-2 h-2 w-full rounded bg-zinc-100 dark:bg-zinc-800">
        <div className={`h-2 rounded ${tone}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
      <div className="mt-2 text-xs text-zinc-500">
        {health.total_active_tokens.toLocaleString()} / {health.soft_cap_tokens.toLocaleString()}{" "}
        active tokens
      </div>
    </div>
  );
}
