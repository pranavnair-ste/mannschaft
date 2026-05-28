"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { CorpusHealthGauge } from "@/components/CorpusHealthGauge";

export default function CorpusPage() {
  const qc = useQueryClient();
  const health = useQuery({ queryKey: ["corpus-health"], queryFn: api.corpusHealth });
  const restore = useMutation({
    mutationFn: (id: string) => api.restoreEntry(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["corpus-health"] }),
  });

  if (health.isPending) return <div className="text-zinc-500">Loading corpus…</div>;
  if (health.isError) return <div className="text-red-600">Error: {String(health.error)}</div>;
  const h = health.data;

  return (
    <section className="space-y-6">
      <h1 className="text-xl font-semibold">Context · Corpus</h1>
      <CorpusHealthGauge health={h} />
      <div className="grid grid-cols-3 gap-3 text-sm">
        <Stat label="Foundational" value={h.foundational_count} />
        <Stat label="Tactical" value={h.tactical_count} />
        <Stat label="Observational" value={h.observational_count} />
      </div>
      <div>
        <h2 className="mb-2 text-sm font-medium">Prune candidates</h2>
        <div className="grid grid-cols-5 gap-2 text-sm">
          {Object.entries(h.prune_candidates).map(([trigger, n]) => (
            <div
              key={trigger}
              className="rounded border border-zinc-200 p-2 text-center dark:border-zinc-800"
            >
              <div className="text-xs uppercase tracking-wide text-zinc-500">{trigger}</div>
              <div className="mt-1 text-lg font-semibold">{n}</div>
            </div>
          ))}
        </div>
      </div>
      <div>
        <h2 className="mb-2 text-sm font-medium">Stale entries (top 50)</h2>
        <ul className="space-y-1 text-sm" data-testid="stale-list">
          {h.stale_entries.map((e) => (
            <li key={e.id} className="rounded border border-zinc-200 px-2 py-1 dark:border-zinc-800">
              <span className="font-mono text-xs text-zinc-500">{e.id}</span> ·{" "}
              {e.body_preview || <em>empty</em>}
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h2 className="mb-2 text-sm font-medium">Recently archived</h2>
        <ul className="space-y-1 text-sm" data-testid="archived-list">
          {h.recently_archived.map((e) => (
            <li
              key={e.id}
              className="flex items-center justify-between rounded border border-zinc-200 px-2 py-1 dark:border-zinc-800"
            >
              <span>
                <span className="font-mono text-xs text-zinc-500">{e.id}</span> · {e.body_preview}
              </span>
              <button
                className="rounded border border-zinc-300 px-2 py-0.5 text-xs hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                onClick={() => restore.mutate(e.id)}
                data-testid={`restore-${e.id}`}
              >
                Restore
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}
