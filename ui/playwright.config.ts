import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "../tests/ui",
  timeout: 30_000,
  use: { baseURL: "http://localhost:3000", trace: "on-first-retry" },
  webServer: [
    {
      command: "uv run python -m pi_harness.api._fixtures",
      cwd: "../",
      url: "http://127.0.0.1:8800/healthz",
      timeout: 60_000,
      reuseExistingServer: true,
      env: { PI_HARNESS_API_PORT: "8800" },
    },
    {
      command: "pnpm dev",
      cwd: ".",
      url: "http://localhost:3000",
      timeout: 60_000,
      reuseExistingServer: true,
    },
  ],
});
