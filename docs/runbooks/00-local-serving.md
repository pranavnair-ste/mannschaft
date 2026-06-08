# Runbook 0 — Local serving baseline (Phase 0) + Phase 1 live acceptance

> **Operator doc.** Stands up the local MLX serving layer the whole stack points at, and runs the Phase 1 sovereign acceptance check. Target box: the 64GB MacBook Pro (dev). Dev model: `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit`.

## Principle: serving is isolated from the harness

`mlx_lm` is installed as an **isolated `uv tool`**, NOT into the harness venv — installing it into the venv downgrades `typer` and breaks the `ms` CLI. The harness only ever talks to the server over `http://localhost:8080/v1`.

## 1. Install the serving toolchain (once)

```bash
uv tool install mlx-lm          # exposes ~/.local/bin/mlx_lm.server (+ .convert, .benchmark, …)
mlx_lm.server --help | head     # sanity
```

## 2. Download the dev model (once, ~17GB)

```bash
uvx --from "huggingface_hub[cli]" hf download mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit
```
Lands in `~/.cache/huggingface/hub/`. Confirm: `du -sh ~/.cache/huggingface/hub/models--mlx-community--Qwen3-Coder-30B-A3B-Instruct-4bit` (~17GB when complete).

## 3. Run the server

```bash
mlx_lm.server --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit --port 8080
```
Leave it running (its own terminal / background). Default bind is `127.0.0.1:8080`.

## 4. Verify the endpoint + single-stream throughput (≥30 tok/s acceptance)

```bash
curl -s http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit",
       "messages":[{"role":"user","content":"Write a Python function that reverses a string."}],
       "max_tokens":200, "stream":false}' | python3 -m json.tool
```
- Expect a valid OpenAI-shaped completion.
- For tok/s, `mlx_lm.server` logs prompt/generation tokens + timing per request; or use `mlx_lm.generate --model <id> --prompt "…" --max-tokens 256` which prints `Generation: N tokens, X tokens-per-sec`. **Acceptance: ≥ ~30 tok/s single-stream at small context** on the dev model (Qwen3-Coder-30B-A3B clears 60–100+ tok/s on M-class Macs, so this should pass with headroom).

## 5. Offline check (sovereignty)

Disable internet (turn off Wi-Fi / pull the cable — leave loopback up), then re-run step 4. The endpoint must still serve. Weights are local; nothing in the serving path needs the network once downloaded.

## 6. Phase 1 live acceptance (the real gate)

With the server up from step 3 and **no `OPENAI_API_KEY` in the environment**:

```bash
cd ~/Desktop/Personal/mannschaft && source .venv/bin/activate
env -u OPENAI_API_KEY ms launch <path/to/tiny-spec.md>
```

Confirm:
1. The run completes with all agent roles driven by the local model (no external calls; run with internet disabled to prove it).
2. `~/.pi/agent/models.json` contains the `harness-local` provider pointing at `http://localhost:8080/v1` (auto-registered by the launch path — Task 5).
3. The trajectory DB shows per-step `tokens_in/out` + `duration_ms` for the run:
   ```bash
   ms observe <run_id>      # or inspect ~/.pi-harness/trajectory.db
   ```

> **Verify-on-first-run (plan T6 Step 3):** watch how pi's `--provider/--model/--base-url` and the registered ClawTeam profile interact with `agent_wrapper --bucket`. pi 0.73.1 has documented quirks (`stdin=DEVNULL`, no `--` end-of-options). If the profile model and the bucket resolution disagree, fix the normalizer in `agent_wrapper.py` / `clawteam_profile.py` and record what was observed below.

## Observations (first live run — 2026-06-08, dev box, Qwen3-Coder-30B-A3B-4bit)

- **Single-stream tok/s:** ~73 tok/s (400 tokens / 5.48s end-to-end, small ctx) — **passes ≥30 bar with headroom.**
- **`ms decompose` via local model, no key:** ✅ produced a valid 3-task JSON decomposition. Proves config-key-optional + settings-local-default + decomposer-local-client + local serving.
- **Full `ms launch` (ClawTeam team), no key:** ✅ team launched on the local provider, isolated on `run/<id>`; **task 1 completed end-to-end**; trajectory store captured **384 events / 47,620 tok_in / 8,335 tok_out**; provider auto-registered (`harness-local`→`:8080`); team + run-worktree torn down cleanly (no leak).
- **Wiring confirmed:** `agent_wrapper` IS in the ClawTeam execution loop (capture happened). pi resolves the local `harness-local` provider from its `models.json` (baseUrl) — no `--base-url` needed on the pi argv.

### Findings / follow-ups (verify-on-first-run)
1. **Per-step `duration_ms` = 0** in `trajectory_events` (tokens captured fine). The `PiEventParser` normalizer isn't extracting per-event timing from pi 0.73.1's stream. *Fix in Plan B or a focused normalizer patch — the PRD's "verify against the real stream format" mandate.*
2. **`runs` rollup table not populated** by the launch path (events are the source of truth; `query_run_summaries` computes on demand). Confirm Plan D surfaces it.
3. **Throughput:** the 3-task sequential build-test run did not finish within the 420s bound on the local 30B (1 of 3 tasks done). Not a sovereignty failure — a speed observation. Raise the launch `--timeout` or use a smaller task set for local-model demos.
4. **Air-gap nit:** `mlx_lm.server` makes a startup metadata call to `huggingface.co`. For a sealed run, launch it with `HF_HUB_OFFLINE=1` (and `HF_HUB_DISABLE_TELEMETRY=1`).
