# Pre-captured fallback run

A real run of `docs/demo/uc4-todo-api.spec.md` driven by **Qwen3.6-35B-A3B-MLX-4bit**
on the Mac Studio, captured for the dashboard so the demo always has rich content
even if you don't want to risk a live local build on stage.

**What it shows:** the team's agents driving the local model — **114 trajectory
events** (35 messages, 33 tool calls, 33 tool results, 13 task transitions). The
three endpoint tasks (`POST`, `GET`, `DELETE /todos`) completed in ~2.5 minutes;
the run was stopped before the scout/test tasks drained (the honest local-model
convergence finding — full autonomous builds are the UC3/UC4 / T&E frontier).

`run-id`: `run-34301807-0b17-4ddb-9d5f-72e9dcb8b050`

## Load it into a trajectory store and view it

```bash
# Import into your local store (it must already exist — any prior `ms` run creates it):
sqlite3 ~/.pi-harness/trajectory.db < docs/demo/fallback-run/run.sql
sqlite3 ~/.pi-harness/trajectory.db < docs/demo/fallback-run/events.sql

# Push it into the live dashboard:
ms observe run-34301807-0b17-4ddb-9d5f-72e9dcb8b050
```

Then open the dashboard (`ms up`) and select the run to narrate Beat 4 of `DEMO.md`
without a live launch. The same agents-in-worktrees + tool-call stream is visible.

> If the import errors on a duplicate key, the run is already loaded — just run
> `ms observe`.
