import "./globals.css";
import type { Metadata } from "next";
import Script from "next/script";
import { LeftRail } from "@/components/LeftRail";
import { QueryProvider } from "@/lib/query-client";

export const metadata: Metadata = {
  title: "Pi-Agent Harness",
  description: "Symphony-style dashboard for the Pi-Agent Harness.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <Script
          id="theme-init"
          strategy="beforeInteractive"
        >
          {`try { var theme = localStorage.getItem('theme'); if (theme === 'dark') { document.documentElement.classList.add('dark'); } else if (theme === 'light') { document.documentElement.classList.remove('dark'); } } catch (e) {}`}
        </Script>
      </head>
      <body className="bg-white text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
        <QueryProvider>
          <div className="flex min-h-screen">
            <LeftRail />
            <main className="flex-1 overflow-auto p-6">{children}</main>
          </div>
        </QueryProvider>
      </body>
    </html>
  );
}
