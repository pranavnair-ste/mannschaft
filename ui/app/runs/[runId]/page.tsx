import { api } from "@/lib/api";
import { RunTimeline } from "@/components/RunTimeline";
import { ReliabilityGauges } from "@/components/ReliabilityGauges";
import { CostPanel } from "@/components/CostPanel";

export const dynamic = "force-dynamic";

export default async function RunPage({ params }: { params: { runId: string } }) {
  const [detail, timeline, reliability, obs] = await Promise.all([
    api.getRun(params.runId),
    api.getTimeline(params.runId),
    api.getReliability(params.runId),
    // The deep-link is a non-essential adornment — a failed fetch must hide the
    // button, not crash the whole run page.
    api.obsLink(params.runId).catch(() => ({ enabled: false, base: "", url: "" })),
  ]);
  return (
    <section className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Run {detail.summary.run_id}</h1>
          <p className="text-sm text-zinc-500">
            {detail.summary.topology ?? "—"} · {detail.summary.status}
            {detail.summary.parent_run_id && (
              <> · branched from {detail.summary.parent_run_id}</>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {obs.enabled && (
            <a
              href={obs.url}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded border border-zinc-300 px-2 py-1 text-sm hover:border-zinc-500"
            >
              Open in observability ↗
            </a>
          )}
          <CostPanel summary={detail.summary} />
        </div>
      </header>
      <RunTimeline runId={params.runId} initial={timeline} />
      <div className="max-w-md">
        <ReliabilityGauges scores={reliability} />
      </div>
    </section>
  );
}
