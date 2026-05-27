"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { SpecEditor } from "@/components/SpecEditor";

export default function SpecsPage() {
  const specs = useQuery({ queryKey: ["specs"], queryFn: api.listSpecs });
  const [activeId, setActiveId] = useState<string | null>(null);
  const active = useQuery({
    queryKey: ["spec", activeId],
    queryFn: () => api.getSpec(activeId as string),
    enabled: !!activeId,
  });

  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Prompt Shape · Specs</h1>
      <div className="grid grid-cols-4 gap-4">
        <aside className="col-span-1 space-y-1">
          {specs.data?.map((s) => (
            <button
              key={s.id}
              onClick={() => setActiveId(s.id)}
              className={`block w-full rounded px-2 py-1.5 text-left text-sm ${
                activeId === s.id
                  ? "bg-zinc-100 dark:bg-zinc-800"
                  : "hover:bg-zinc-50 dark:hover:bg-zinc-900"
              }`}
              data-testid={`spec-${s.id}`}
            >
              {s.title}
            </button>
          ))}
          {specs.data?.length === 0 && <p className="text-sm text-zinc-500">No specs yet.</p>}
        </aside>
        <div className="col-span-3">
          {active.data ? (
            <SpecEditor spec={active.data} />
          ) : (
            <p className="text-sm text-zinc-500">Pick a spec to edit.</p>
          )}
        </div>
      </div>
    </section>
  );
}
