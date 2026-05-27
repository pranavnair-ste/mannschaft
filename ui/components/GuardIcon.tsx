import { Shield, Eye } from "lucide-react";

export function GuardIcon({
  kind,
  allow,
  detail,
}: {
  kind: "guide" | "sensor";
  allow: boolean;
  detail?: string;
}) {
  const tone = allow ? "text-emerald-500" : "text-red-500";
  const Icon = kind === "guide" ? Shield : Eye;
  const verdict = allow ? "allow" : "deny";
  return (
    <span
      title={`${kind}: ${verdict}${detail ? ` — ${detail}` : ""}`}
      data-testid={`${kind}-icon`}
      className={`inline-flex h-4 w-4 ${tone}`}
    >
      <Icon className="h-4 w-4" aria-label={`${kind}-${verdict}`} />
    </span>
  );
}
