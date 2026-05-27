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
