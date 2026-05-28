"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Boxes, FileText, Wrench, Layers, Database, Users, MoonStar, SunMedium } from "lucide-react";

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
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    setIsDark(document.documentElement.classList.contains("dark"));
  }, []);

  const toggleTheme = () => {
    setIsDark((current) => {
      const nextTheme = current ? "light" : "dark";
      document.documentElement.classList.toggle("dark", nextTheme === "dark");
      localStorage.setItem("theme", nextTheme);
      return !current;
    });
  };

  return (
    <nav
      aria-label="Audit order"
      className="w-56 shrink-0 border-r border-zinc-200 p-3 dark:border-zinc-800"
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
                    ? "bg-zinc-100 font-medium dark:bg-zinc-800"
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

      <div className="mt-4 border-t border-zinc-200 pt-4 dark:border-zinc-800">
        <button
          type="button"
          onClick={toggleTheme}
          className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm text-zinc-600 hover:bg-zinc-50 dark:text-zinc-300 dark:hover:bg-zinc-800/50"
          aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
          title={isDark ? "Switch to light mode" : "Switch to dark mode"}
        >
          {isDark ? <SunMedium className="h-4 w-4" /> : <MoonStar className="h-4 w-4" />}
          <span>{isDark ? "Light mode" : "Dark mode"}</span>
        </button>
      </div>
    </nav>
  );
}
