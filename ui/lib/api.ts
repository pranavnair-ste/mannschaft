import type { components } from "./api-types";

type S = components["schemas"];

export type RunSummary = S["RunSummaryDTO"];
export type RunDetail = S["RunDetailDTO"];
export type Timeline = S["TimelineDTO"];
export type TrajectoryEvent = S["TrajectoryEventDTO"];
export type Reliability = S["ReliabilityDTO"];
export type CorpusHealth = S["CorpusHealthDTO"];
export type CorpusEntry = S["CorpusEntryDTO"];
export type PromotionCandidate = S["PromotionCandidateDTO"];
export type BranchRequest = S["BranchRequest"];
export type BranchResponse = S["BranchResponse"];
export type Spec = S["Spec"];
export type SpecList = S["SpecList"];
export type LintResult = S["LintResult"];
export type DecomposeResponse = S["DecomposeResponse"];
export type LaunchResponse = S["LaunchResponse"];
export type UpdateSpecBody = S["UpdateSpecBody"];
export type ModelSettings = S["SettingsBody"];

const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8800";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} on ${path}`);
  return res.json() as Promise<T>;
}

export const api = {
  listRuns: (q: { status?: string; limit?: number } = {}) => {
    const params = new URLSearchParams();
    if (q.status) params.set("status", q.status);
    if (q.limit) params.set("limit", String(q.limit));
    const qs = params.toString();
    return json<RunSummary[]>(`/runs${qs ? `?${qs}` : ""}`);
  },
  getRun: (runId: string) => json<RunDetail>(`/runs/${runId}`),
  getTimeline: (runId: string) => json<Timeline>(`/runs/${runId}/timeline`),
  getReliability: (runId: string) => json<Reliability>(`/runs/${runId}/reliability`),
  branchRun: (runId: string, body: BranchRequest) =>
    json<BranchResponse>(`/runs/${runId}/branch`, { method: "POST", body: JSON.stringify(body) }),
  corpusHealth: () => json<CorpusHealth>("/corpus/health"),
  corpusEntries: (q: { classification?: string; record_type?: string; archived?: boolean } = {}) => {
    const params = new URLSearchParams();
    if (q.classification) params.set("classification", q.classification);
    if (q.record_type) params.set("record_type", q.record_type);
    if (q.archived) params.set("archived", "true");
    const qs = params.toString();
    return json<CorpusEntry[]>(`/corpus/entries${qs ? `?${qs}` : ""}`);
  },
  restoreEntry: (entryId: string) =>
    json<CorpusEntry>(`/corpus/entries/${entryId}/restore`, { method: "POST" }),
  promotionCandidates: () => json<PromotionCandidate[]>("/guards/promotion-candidates"),
  // Spec editor (real Plan 7 shapes): list is wrapped in {specs}; spec is structured.
  listSpecs: () => json<SpecList>("/specs").then((r) => r.specs),
  getSpec: (id: string) => json<Spec>(`/specs/${id}`),
  saveSpec: (id: string, body: UpdateSpecBody) =>
    json<Spec>(`/specs/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  lintSpec: (id: string) => json<LintResult>(`/specs/${id}/lint`, { method: "POST" }),
  decomposeSpec: (id: string) =>
    json<DecomposeResponse>(`/specs/${id}/decompose`, { method: "POST" }),
  launchSpec: (id: string) => json<LaunchResponse>(`/specs/${id}/launch`, { method: "POST" }),
  // Model picker (orchestrator/builder bucket selection)
  getModelSettings: () => json<ModelSettings>("/settings/models"),
  putModelSettings: (body: ModelSettings) =>
    json<ModelSettings>("/settings/models", { method: "PUT", body: JSON.stringify(body) }),
  discoverLocalModels: (baseUrl: string) =>
    json<{ models: string[]; error?: string }>(
      `/settings/models/local-models?base_url=${encodeURIComponent(baseUrl)}`,
    ),
};
