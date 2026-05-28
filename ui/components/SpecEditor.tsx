"use client";
import { useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, type Spec } from "@/lib/api";
import type { components } from "@/lib/api-types";

type DecomposedTask = components["schemas"]["DecomposedTask"];

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

function ActionButton({
  label,
  pendingLabel,
  pending,
  onClick,
  primary,
  testid,
}: {
  label: string;
  pendingLabel?: string;
  pending: boolean;
  onClick: () => void;
  primary?: boolean;
  testid: string;
}) {
  const base =
    "rounded px-3 py-1.5 text-sm transition disabled:cursor-not-allowed disabled:opacity-60";
  const variant = primary
    ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
    : "border border-zinc-300 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800";
  return (
    <button
      onClick={onClick}
      disabled={pending}
      className={`${base} ${variant}`}
      data-testid={testid}
      aria-busy={pending}
    >
      {pending ? pendingLabel ?? `${label}…` : label}
    </button>
  );
}

function ErrorBox({ label, error, testid }: { label: string; error: unknown; testid: string }) {
  return (
    <div
      className="rounded border border-red-200 bg-red-50 p-2 text-xs dark:border-red-800 dark:bg-red-900/20"
      data-testid={testid}
    >
      <div className="font-medium text-red-700 dark:text-red-300">{label}</div>
      <div className="mt-1 break-all text-red-600 dark:text-red-400">{String(error)}</div>
    </div>
  );
}

function Section({ title, children, testid }: { title: string; children: ReactNode; testid?: string }) {
  return (
    <div data-testid={testid}>
      <h3 className="mb-1 text-xs uppercase tracking-wide text-zinc-500">{title}</h3>
      {children}
    </div>
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
    onSuccess: () => {
      // Editing invalidates any prior decomposition; clear the local mutation
      // caches so the right pane doesn't show stale results.
      lint.reset();
      decompose.reset();
    },
  });
  const lint = useMutation({ mutationFn: () => api.lintSpec(spec.id) });
  const decompose = useMutation({ mutationFn: () => api.decomposeSpec(spec.id) });
  const launch = useMutation({
    mutationFn: () => api.launchSpec(spec.id),
    onSuccess: (resp) => {
      window.location.href = `/runs/${resp.run_id}`;
    },
  });

  // Tasks to render in the right pane: fresh decompose result wins; otherwise
  // show what the backend has persisted on the spec.
  const persisted = (spec.decomposed_tasks ?? null) as DecomposedTask[] | null;
  const tasksToShow: DecomposedTask[] | null = decompose.data?.tasks ?? persisted;

  return (
    <div className="grid grid-cols-3 gap-4">
      <div className="col-span-2 space-y-3">
        <Field label="Goal" value={goal} onChange={setGoal} onBlur={() => save.mutate()} testid="spec-goal" rows={2} />
        <Field label="Acceptance criteria (one per line)" value={acceptance} onChange={setAcceptance} onBlur={() => save.mutate()} testid="spec-acceptance" />
        <Field label="Constraints (one per line)" value={constraints} onChange={setConstraints} onBlur={() => save.mutate()} testid="spec-constraints" />
        <Field label="Non-goals (one per line)" value={nonGoals} onChange={setNonGoals} onBlur={() => save.mutate()} testid="spec-nongoals" />
        <div className="flex items-center gap-2">
          <ActionButton
            label="Lint"
            pending={lint.isPending}
            pendingLabel="Linting…"
            onClick={() => lint.mutate()}
            testid="lint-btn"
          />
          <ActionButton
            label="Decompose"
            pending={decompose.isPending}
            pendingLabel="Decomposing… (30–60s)"
            onClick={() => decompose.mutate()}
            testid="decompose-btn"
          />
          <ActionButton
            label="Launch"
            pending={launch.isPending}
            pendingLabel="Launching…"
            onClick={() => launch.mutate()}
            primary
            testid="launch-btn"
          />
          <span className="ml-2 text-xs text-zinc-500" data-testid="spec-status">
            status: <span className="font-mono">{spec.status}</span>
            {spec.linter_score !== null && (
              <> · score {spec.linter_score.toFixed(2)}</>
            )}
          </span>
        </div>
      </div>
      <aside className="space-y-3 text-sm">
        {lint.error && <ErrorBox label="Lint failed" error={lint.error} testid="lint-error" />}
        {decompose.error && <ErrorBox label="Decompose failed" error={decompose.error} testid="decompose-error" />}
        {launch.error && <ErrorBox label="Launch failed" error={launch.error} testid="launch-error" />}

        {lint.data && (
          <Section title={`Lint · score ${lint.data.score}`} testid="lint-results">
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
          </Section>
        )}

        {tasksToShow && tasksToShow.length > 0 && (
          <Section
            title={
              decompose.data
                ? "Decomposed tasks"
                : "Decomposed tasks (persisted)"
            }
            testid="decompose-results"
          >
            <ul className="space-y-1">
              {tasksToShow.map((t) => (
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
          </Section>
        )}
      </aside>
    </div>
  );
}
