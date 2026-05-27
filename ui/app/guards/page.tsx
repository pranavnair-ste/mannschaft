"use client";
import { useQuery } from "@tanstack/react-query";
import { Shield } from "lucide-react";
import { api } from "@/lib/api";

export default function GuardsPage() {
  const candidates = useQuery({
    queryKey: ["promotion-candidates"],
    queryFn: api.promotionCandidates,
  });
  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Tools · Guards &amp; Sensors</h1>
      <div>
        <h2 className="mb-2 text-sm font-medium">Promotion candidates</h2>
        {candidates.isPending && <p className="text-zinc-500">Loading…</p>}
        {candidates.data?.length === 0 && (
          <p className="text-sm text-zinc-500">No inferential sensors are ready to promote.</p>
        )}
        <ul className="space-y-2" data-testid="promotion-list">
          {candidates.data?.map((c) => (
            <li
              key={`${c.sensor_name}-${c.sensor_criterion}`}
              className="rounded border border-zinc-200 p-3 dark:border-zinc-800"
            >
              <div className="flex items-center gap-2 text-sm">
                <Shield className="h-4 w-4 text-amber-500" />
                <span className="font-medium">{c.sensor_name}</span>
                <span className="text-zinc-500">{c.sensor_criterion}</span>
                <span className="ml-auto text-xs text-zinc-500">
                  fired {c.fires}× · allow {Math.round(c.allow_fraction * 100)}%
                </span>
              </div>
              <pre className="mt-2 overflow-auto rounded bg-zinc-50 p-2 text-xs dark:bg-zinc-900">
                {c.suggested_stub_code}
              </pre>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
