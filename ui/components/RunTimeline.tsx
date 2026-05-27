"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Timeline, type TrajectoryEvent } from "@/lib/api";
import { useLiveRun } from "@/lib/use-live-run";
import { GuardIcon } from "./GuardIcon";

function guardMeta(ev: TrajectoryEvent): { allow: boolean; reason?: string } | null {
  // output is untyped JSON; firing events stash the verdict under _guard_meta.
  const meta = (ev.output as Record<string, unknown> | undefined)?.["_guard_meta"] as
    | { allow?: boolean; reason?: string }
    | undefined;
  if (!meta) return null;
  return { allow: meta.allow === true, reason: meta.reason };
}

export function RunTimeline({ runId, initial }: { runId: string; initial: Timeline }) {
  const qc = useQueryClient();
  const { data: timeline } = useQuery({
    queryKey: ["timeline", runId],
    queryFn: () => api.getTimeline(runId),
    initialData: initial,
    refetchInterval: 5000,
  });
  const live = useLiveRun(runId);
  const [selected, setSelected] = useState<TrajectoryEvent | null>(null);
  const branch = useMutation({
    mutationFn: (stepId: string) => api.branchRun(runId, { step_id: stepId, overrides: {} }),
    onSuccess: (resp) => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      window.location.href = `/runs/${resp.run_id}`;
    },
  });

  return (
    <div className="grid grid-cols-3 gap-4">
      <div className="col-span-2 space-y-4" data-testid="timeline">
        {timeline?.agents.map((row) => (
          <div key={row.agent_id} className="rounded border border-zinc-200 dark:border-zinc-800">
            <div className="border-b border-zinc-200 px-3 py-2 text-sm font-mono dark:border-zinc-800">
              {row.agent_id}
            </div>
            <ol className="divide-y divide-zinc-100 dark:divide-zinc-900">
              {row.events.map((ev) => {
                const meta = guardMeta(ev);
                const isFiring =
                  ev.classification === "guide_fired" || ev.classification === "sensor_fired";
                const kind = ev.classification === "sensor_fired" ? "sensor" : "guide";
                return (
                  <li
                    key={`${ev.step_id}-${ev.ts}-${ev.classification}`}
                    className="cursor-pointer px-3 py-2 text-sm hover:bg-zinc-50 dark:hover:bg-zinc-900"
                    onClick={() => setSelected(ev)}
                    data-testid={`step-${ev.step_id}`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-zinc-500">{ev.step_id}</span>
                      <span className="text-zinc-700 dark:text-zinc-300">
                        {ev.tool || ev.classification}
                      </span>
                      {isFiring && meta && (
                        <GuardIcon kind={kind} allow={meta.allow} detail={meta.reason} />
                      )}
                      <span className="ml-auto text-xs text-zinc-500">{ev.duration_ms} ms</span>
                      {!isFiring && (
                        <button
                          className="rounded border border-zinc-300 px-1.5 py-0.5 text-xs hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                          onClick={(e) => {
                            e.stopPropagation();
                            branch.mutate(ev.step_id);
                          }}
                          data-testid={`branch-${ev.step_id}`}
                        >
                          Branch
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>
        ))}
        {live.events.length > 0 && (
          <div className="rounded border border-blue-300 p-3 text-xs text-blue-700 dark:border-blue-700 dark:text-blue-300">
            Live · {live.events.length} new events streamed
          </div>
        )}
      </div>
      <aside className="space-y-3 text-sm">
        <div className="text-xs uppercase tracking-wide text-zinc-500">Inspector</div>
        {selected ? (
          <pre className="overflow-auto rounded border border-zinc-200 bg-zinc-50 p-2 text-xs dark:border-zinc-800 dark:bg-zinc-900">
            {JSON.stringify(selected, null, 2)}
          </pre>
        ) : (
          <div className="text-zinc-500">Select a step to inspect.</div>
        )}
      </aside>
    </div>
  );
}
