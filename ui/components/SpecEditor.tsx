"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, type Spec } from "@/lib/api";

function toLines(s: string): string[] {
  return s
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
}

function Field({
  label,
  value,
  onChange,
  onBlur,
  testid,
  rows = 4,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  onBlur: () => void;
  testid: string;
  rows?: number;
}) {
  return (
    <label className="block">
      <span className="text-xs uppercase tracking-wide text-zinc-500">{label}</span>
      <textarea
        className="mt-1 w-full rounded border border-zinc-200 p-2 font-mono text-sm dark:border-zinc-800 dark:bg-zinc-900"
        rows={rows}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onBlur}
        data-testid={testid}
      />
    </label>
  );
}

export function SpecEditor({ spec }: { spec: Spec }) {
  const [goal, setGoal] = useState(spec.goal);
  const [acceptance, setAcceptance] = useState((spec.acceptance_criteria ?? []).join("\n"));
  const [constraints, setConstraints] = useState((spec.constraints ?? []).join("\n"));
  const [nonGoals, setNonGoals] = useState((spec.non_goals ?? []).join("\n"));

  const save = useMutation({
    mutationFn: () =>
      api.saveSpec(spec.id, {
        goal,
        acceptance_criteria: toLines(acceptance),
        constraints: toLines(constraints),
        non_goals: toLines(nonGoals),
      }),
  });
  const lint = useMutation({ mutationFn: () => api.lintSpec(spec.id) });
  const decompose = useMutation({ mutationFn: () => api.decomposeSpec(spec.id) });
  const launch = useMutation({
    mutationFn: () => api.launchSpec(spec.id),
    onSuccess: (resp) => {
      window.location.href = `/runs/${resp.run_id}`;
    },
  });

  return (
    <div className="grid grid-cols-3 gap-4">
      <div className="col-span-2 space-y-3">
        <Field label="Goal" value={goal} onChange={setGoal} onBlur={() => save.mutate()} testid="spec-goal" rows={2} />
        <Field label="Acceptance criteria (one per line)" value={acceptance} onChange={setAcceptance} onBlur={() => save.mutate()} testid="spec-acceptance" />
        <Field label="Constraints (one per line)" value={constraints} onChange={setConstraints} onBlur={() => save.mutate()} testid="spec-constraints" />
        <Field label="Non-goals (one per line)" value={nonGoals} onChange={setNonGoals} onBlur={() => save.mutate()} testid="spec-nongoals" />
        <div className="flex gap-2">
          <button
            onClick={() => lint.mutate()}
            data-testid="lint-btn"
            className="rounded border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Lint
          </button>
          <button
            onClick={() => decompose.mutate()}
            data-testid="decompose-btn"
            className="rounded border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Decompose
          </button>
          <button
            onClick={() => launch.mutate()}
            data-testid="launch-btn"
            className="rounded bg-zinc-900 px-3 py-1.5 text-sm text-white dark:bg-white dark:text-zinc-900"
          >
            Launch
          </button>
        </div>
      </div>
      <aside className="space-y-3 text-sm">
        {lint.data && (
          <div data-testid="lint-results">
            <h3 className="mb-1 text-xs uppercase tracking-wide text-zinc-500">
              Lint · score {lint.data.score}
            </h3>
            {(lint.data.errors ?? []).length === 0 && (lint.data.warnings ?? []).length === 0 ? (
              <p className="text-emerald-600">Clean.</p>
            ) : (
              <ul className="space-y-1">
                {[...(lint.data.errors ?? []), ...(lint.data.warnings ?? [])].map((v, i) => (
                  <li
                    key={i}
                    className="rounded border border-amber-200 bg-amber-50 px-2 py-1 dark:border-amber-800 dark:bg-amber-900/20"
                  >
                    <span className="font-mono text-xs">{v.rule_name}</span> · {v.message}
                    <span className="text-zinc-500"> ({v.location})</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {decompose.data && (
          <div data-testid="decompose-results">
            <h3 className="mb-1 text-xs uppercase tracking-wide text-zinc-500">Decomposed tasks</h3>
            <ul className="space-y-1">
              {decompose.data.tasks.map((t) => (
                <li key={t.id} className="rounded border border-zinc-200 px-2 py-1 dark:border-zinc-800">
                  <span className="font-mono text-xs text-zinc-500">{t.id}</span> · {t.name}
                  {(t.blocked_by ?? []).length > 0 && (
                    <span className="ml-2 text-xs text-zinc-500">
                      blocked-by: {(t.blocked_by ?? []).join(", ")}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </aside>
    </div>
  );
}
