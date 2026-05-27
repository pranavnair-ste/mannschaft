"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Boxes, FileText, Wrench, Layers, Database, Users } from "lucide-react";

// 6-component audit order from HARNESS_ARCHITECTURE.md §5
const NAV = [
  { href: "/", label: "Workspace", icon: Boxes },
  { href: "/specs", label: "Prompt Shape", icon: FileText },
  { href: "/guards", label: "Tools", icon: Wrench },
  { href: "/corpus", label: "Context", icon: Layers },
  { href: "/memory", label: "Memory", icon: Database },
  { href: "/subagents", label: "Subagents", icon: Users },
];

export function LeftRail() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Audit order"
      className="w-56 shrink-0 border-r border-zinc-200 dark:border-zinc-800 p-3"
    >
      <div className="mb-4 text-xs font-mono uppercase tracking-wider text-zinc-500">
        Pi-Agent Harness
      </div>
      <ul className="space-y-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || (href !== "/" && pathname.startsWith(href));
          return (
            <li key={href}>
              <Link
                href={href}
                className={`flex items-center gap-2 rounded px-2 py-1.5 text-sm ${
                  active
                    ? "bg-zinc-100 dark:bg-zinc-800 font-medium"
                    : "text-zinc-600 hover:bg-zinc-50 dark:text-zinc-300 dark:hover:bg-zinc-800/50"
                }`}
              >
                <Icon className="h-4 w-4" />
                <span>{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
