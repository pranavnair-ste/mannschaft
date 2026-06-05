import { api } from "@/lib/api";
import { RunTimeline } from "@/components/RunTimeline";
import { ReliabilityGauges } from "@/components/ReliabilityGauges";
import { CostPanel } from "@/components/CostPanel";

export const dynamic = "force-dynamic";

export default async function RunPage({ params }: { params: { runId: string } }) {
  const [detail, timeline, reliability] = await Promise.all([
    api.getRun(params.runId),
    api.getTimeline(params.runId),
    api.getReliability(params.runId),
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
          <a
            href={`${process.env.NEXT_PUBLIC_OBS_URL ?? "http://127.0.0.1:43190"}/?token=${process.env.NEXT_PUBLIC_OBS_TOKEN ?? "devtoken"}#view=race&pool=${detail.summary.run_id}&hide_after=never&show_hidden=1`}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded border border-zinc-300 px-2 py-1 text-sm hover:border-zinc-500"
          >
            Open in observability ↗
          </a>
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
