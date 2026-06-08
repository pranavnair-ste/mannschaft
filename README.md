# mannschaft

Symphony-style multi-agent orchestrator with an expertise loop — launch a spec, a team of coding agents builds it, and every step is captured to a trajectory store for observation, cost/reliability tracking, and replay.

`ms` is the CLI surface (installed in the venv via `uv pip install -e .`; `pi-harness` remains as a legacy alias for the same command). Run `ms --help` for the full command list (`launch`, `spec`, `observe`, `serve`, `up`, `doctor`, …).

## Observability stack

See your runs live in race / swimlane / replay views. One command boots the whole local stack — the fork dashboard, the live event bridge, the FastAPI backend, and the Next.js UI:

```bash
source .venv/bin/activate
export OBS_AUTH_TOKEN=$(openssl rand -hex 16) PI_HARNESS_OBS_ENABLED=1
ms doctor   # preflight: bun, ports, fork checkout, UI deps, token
ms up       # boots all four processes; Ctrl-C to tear down
```

Then open the tokenized fork UI that `up` prints, or the Symphony UI at `http://localhost:3000` and click **"Open in observability ↗"** on any run.

**Full guide:** [`docs/observability-quickstart.md`](docs/observability-quickstart.md) — prerequisites, configuration, a runnable `launch` example, and troubleshooting.
