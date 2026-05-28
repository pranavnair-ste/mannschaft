"use client";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ModelSettings } from "@/lib/api";

// Curated list of API models the user can pick. Mirrors what
// `pi --list-models openai` exposes; intentionally NOT exhaustive so the
// dropdown stays useful rather than overwhelming.
const API_MODELS = [
  "gpt-5",
  "gpt-5-mini",
  "gpt-5-nano",
  "gpt-4.1",
  "gpt-4.1-mini",
  "gpt-4o",
  "gpt-4o-mini",
];

type Bucket = "orchestrator" | "builder";
type Provider = "api" | "local";

export default function SettingsPage() {
  const qc = useQueryClient();
  const current = useQuery({ queryKey: ["model-settings"], queryFn: api.getModelSettings });
  const [draft, setDraft] = useState<ModelSettings | null>(null);

  // Hydrate the draft when the server's current settings load.
  useEffect(() => {
    if (current.data && !draft) setDraft(current.data);
  }, [current.data, draft]);

  const save = useMutation({
    mutationFn: (body: ModelSettings) => api.putModelSettings(body),
    onSuccess: (saved) => {
      qc.setQueryData(["model-settings"], saved);
      setDraft(saved);
    },
  });

  const discover = useMutation({
    mutationFn: (baseUrl: string) => api.discoverLocalModels(baseUrl),
  });

  if (!draft || current.isPending) {
    return <div className="text-sm text-zinc-500">Loading settings…</div>;
  }

  const setBucket = (key: Bucket, patch: Partial<{ provider: Provider; model: string }>) => {
    setDraft({
      ...draft,
      [key]: { ...draft[key], ...patch },
    });
  };

  const needsLocal = draft.orchestrator.provider === "local" || draft.builder.provider === "local";
  const discoveredModels = discover.data?.models ?? [];
  const dirty = JSON.stringify(draft) !== JSON.stringify(current.data);

  return (
    <section className="max-w-3xl space-y-6">
      <header>
        <h1 className="text-xl font-semibold">Settings · Models</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Pick where each agent bucket gets its model. <span className="font-mono">API</span> uses
          OpenAI directly. <span className="font-mono">Local</span> routes through an
          OpenAI-compatible server (Ollama, LM Studio, vLLM) — the harness registers a
          <span className="font-mono"> harness-local </span>
          provider entry in pi&apos;s models.json when you save.
        </p>
      </header>

      <BucketCard
        title="Orchestrator bucket"
        roles="orchestrator · reviewer · synthesizer"
        provider={draft.orchestrator.provider as Provider}
        model={draft.orchestrator.model}
        onProvider={(p) => setBucket("orchestrator", { provider: p })}
        onModel={(m) => setBucket("orchestrator", { model: m })}
        apiModels={API_MODELS}
        localModels={discoveredModels}
      />

      <BucketCard
        title="Builder bucket"
        roles="builder · scout"
        provider={draft.builder.provider as Provider}
        model={draft.builder.model}
        onProvider={(p) => setBucket("builder", { provider: p })}
        onModel={(m) => setBucket("builder", { model: m })}
        apiModels={API_MODELS}
        localModels={discoveredModels}
      />

      {needsLocal && (
        <div className="rounded border border-zinc-200 p-4 dark:border-zinc-800">
          <h3 className="mb-2 text-sm font-medium">Local server</h3>
          <label className="block">
            <span className="text-xs uppercase tracking-wide text-zinc-500">Base URL</span>
            <input
              type="text"
              value={draft.local_base_url}
              onChange={(e) => setDraft({ ...draft, local_base_url: e.target.value })}
              data-testid="local-base-url"
              className="mt-1 w-full rounded border border-zinc-200 p-2 font-mono text-sm dark:border-zinc-800 dark:bg-zinc-900"
              placeholder="http://localhost:11434/v1"
            />
          </label>
          <p className="mt-2 text-xs text-zinc-500">
            Ollama default: <span className="font-mono">http://localhost:11434/v1</span> · LM Studio:{" "}
            <span className="font-mono">http://localhost:1234/v1</span>
          </p>
          <div className="mt-3 flex items-center gap-2">
            <button
              onClick={() => discover.mutate(draft.local_base_url)}
              disabled={discover.isPending}
              data-testid="discover-btn"
              className="rounded border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-100 disabled:opacity-60 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              {discover.isPending ? "Discovering…" : "Discover available models"}
            </button>
            {discover.data && !discover.data.error && (
              <span className="text-xs text-emerald-600 dark:text-emerald-400">
                {discoveredModels.length} model{discoveredModels.length === 1 ? "" : "s"} found
              </span>
            )}
            {discover.data?.error && (
              <span className="text-xs text-red-600 dark:text-red-400" data-testid="discover-error">
                {discover.data.error}
              </span>
            )}
          </div>
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={() => save.mutate(draft)}
          disabled={save.isPending || !dirty}
          data-testid="save-btn"
          className="rounded bg-zinc-900 px-4 py-2 text-sm text-white disabled:opacity-60 dark:bg-white dark:text-zinc-900"
        >
          {save.isPending ? "Saving…" : dirty ? "Save" : "Saved"}
        </button>
        {save.error && (
          <span className="text-xs text-red-600 dark:text-red-400" data-testid="save-error">
            {String(save.error)}
          </span>
        )}
      </div>
    </section>
  );
}

function BucketCard({
  title,
  roles,
  provider,
  model,
  onProvider,
  onModel,
  apiModels,
  localModels,
}: {
  title: string;
  roles: string;
  provider: Provider;
  model: string;
  onProvider: (p: Provider) => void;
  onModel: (m: string) => void;
  apiModels: string[];
  localModels: string[];
}) {
  const options = provider === "api" ? apiModels : localModels;
  // The currently-saved model might not be in the dropdown (custom Ollama tag,
  // a model we discovered then removed, etc.) — surface it as an extra option
  // so the user doesn't lose their selection.
  const finalOptions = options.includes(model) || !model ? options : [model, ...options];

  return (
    <div className="rounded border border-zinc-200 p-4 dark:border-zinc-800" data-testid={`bucket-${title.toLowerCase().split(" ")[0]}`}>
      <h3 className="text-sm font-medium">{title}</h3>
      <p className="mt-0.5 text-xs text-zinc-500">Applies to roles: {roles}</p>

      <div className="mt-3 grid grid-cols-3 gap-3">
        <fieldset className="col-span-1">
          <legend className="text-xs uppercase tracking-wide text-zinc-500">Provider</legend>
          <label className="mt-1 flex items-center gap-2 text-sm">
            <input
              type="radio"
              checked={provider === "api"}
              onChange={() => onProvider("api")}
              data-testid={`provider-api-${title.toLowerCase().split(" ")[0]}`}
            />
            <span>API (OpenAI)</span>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              checked={provider === "local"}
              onChange={() => onProvider("local")}
              data-testid={`provider-local-${title.toLowerCase().split(" ")[0]}`}
            />
            <span>Local</span>
          </label>
        </fieldset>

        <label className="col-span-2 block">
          <span className="text-xs uppercase tracking-wide text-zinc-500">Model</span>
          {provider === "api" || finalOptions.length > 0 ? (
            <select
              value={model}
              onChange={(e) => onModel(e.target.value)}
              data-testid={`model-${title.toLowerCase().split(" ")[0]}`}
              className="mt-1 w-full rounded border border-zinc-200 p-2 font-mono text-sm dark:border-zinc-800 dark:bg-zinc-900"
            >
              {finalOptions.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              value={model}
              onChange={(e) => onModel(e.target.value)}
              data-testid={`model-${title.toLowerCase().split(" ")[0]}`}
              placeholder="e.g. qwen2.5-coder:7b (click Discover to populate)"
              className="mt-1 w-full rounded border border-zinc-200 p-2 font-mono text-sm dark:border-zinc-800 dark:bg-zinc-900"
            />
          )}
        </label>
      </div>
    </div>
  );
}
