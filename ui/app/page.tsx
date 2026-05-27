import Link from "next/link";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const runs = await api.listRuns({ limit: 50 });
  return (
    <section>
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Workspace</h1>
        <Link
          href="/specs"
          className="rounded bg-zinc-900 px-3 py-1.5 text-sm text-white dark:bg-white dark:text-zinc-900"
        >
          New run
        </Link>
      </header>
      <ul
        className="divide-y divide-zinc-200 rounded border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800"
        data-testid="run-list"
      >
        {runs.map((r) => (
          <li
            key={r.run_id}
            className="flex items-center justify-between p-3 hover:bg-zinc-50 dark:hover:bg-zinc-900"
          >
            <Link href={`/runs/${r.run_id}`} className="flex-1 grid grid-cols-5 gap-2 text-sm">
              <span className="font-mono">{r.run_id}</span>
              <span>
                <Badge status={r.status} />
              </span>
              <span className="text-zinc-500">{r.topology ?? "—"}</span>
              <span>{r.agent_count} agents</span>
              <span className="text-right tabular-nums">${r.total_cost_usd.toFixed(3)}</span>
            </Link>
          </li>
        ))}
        {runs.length === 0 && (
          <li className="p-4 text-sm text-zinc-500">No runs yet — start one from the spec editor.</li>
        )}
      </ul>
    </section>
  );
}

function Badge({ status }: { status: string }) {
  const tone: Record<string, string> = {
    succeeded: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300",
    running: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
    failed: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300",
    cancelled: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
    pending: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
  };
  return (
    <span className={`rounded px-2 py-0.5 text-xs ${tone[status] || tone.pending}`}>{status}</span>
  );
}
