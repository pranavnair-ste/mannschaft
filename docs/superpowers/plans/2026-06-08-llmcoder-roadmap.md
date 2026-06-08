# LLMCoder Build Roadmap — decomposition of `PRD-LLM-in-a-Box-v1.md`

> **For agentic workers:** This is the program-level decomposition. Each **code plan** below is its own document under `docs/superpowers/plans/` and is executed with `superpowers:subagent-driven-development` or `superpowers:executing-plans`. **Runbooks** are operator docs (the human runs them on real hardware); they are not auto-executed.

**Source spec:** `~/Desktop/Work/BoxLLM/PRD-LLM-in-a-Box-v1.md` (full scope, per Pranav 2026-06-08).
**Workspace:** `~/Desktop/Personal/mannschaft` (package stays `pi_harness`); seed `LLMCoder` from a green checkpoint later.
**Scope decision:** Full PRD (all 6 UCs, full optimization matrix). The independent review's compression is *not* applied.

---

## Why this is multiple plans, not one

The PRD spans four independent subsystems (serving infra, harness adaptation, measurement, evidence) plus the use-case execution. Per planning discipline each must produce working, testable software on its own. The split also tracks a hard reality: **about half the PRD is operator work on hardware (install MLX, download weights, run servers, build products, scale to the Studio) that an agent cannot fully execute autonomously.** Those become runbooks; the code becomes plans.

## Cross-cutting decisions (apply to every plan)

1. **Serving is isolated from the harness.** `mlx_lm` lives in an isolated `uv tool` install (`~/.local/bin/mlx_lm.server`), never the harness venv (it downgrades `typer` and breaks the CLI). The harness only ever talks to it over `http://localhost:8080/v1`.
2. **Two model-selection layers must both default local** (see Plan A): `config.py`+`clawteam_profile.py` (ClawTeam profile registration) and `settings.py`+`agent_wrapper.py` (per-agent `--provider/--model`).
3. **Sovereignty is the prime directive.** No runtime-path external calls. The only sanctioned online steps are the OpenRouter quality sanity-check (UC1) and weight downloads before sealing — both explicitly flagged.
4. **Branch + checkpoint hygiene.** Work each plan on its own branch off `main`; the pre-existing `ms`-rename WIP is checkpointed first. Run tests with `-m "not smoke"` (smoke launches a real ClawTeam team that commits to your branch).
5. **Dev model:** `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit` on this 64GB MacBook Pro. **Scale model:** REAP-`Qwen3-Coder-246B-A35B` 4-bit on the 512GB Studio (Plan/runbook F) — confirm/convert the MLX build first.

---

## Plan / Runbook sequence

| # | Item | Type | PRD phase | Produces |
|---|---|---|---|---|
| **0** | **Local serving baseline** | Runbook | Phase 0 | `docs/runbooks/00-local-serving.md` — install, download, serve, curl ≥30 tok/s, offline check. *(Model download already kicked off.)* |
| **A** | **Sovereign harness adaptation** (cloud→local default) | **Code plan** | Phase 1 | `2026-06-08-phase1-sovereign-local-default.md`. Harness boots + runs with **no `OPENAI_API_KEY`**, all roles on the local MLX model. **Foundation — build first.** |
| **B** | **Tool-calling reliability + reviewer gate** | **Code plan** | Phase 2 | Schema-validate/repair/retry on tool calls, loop/stall detection, post-step reviewer re-dispatch, tool-call-success metric in the trajectory store. |
| **C** | **UC1 benchmark runner** | **Code plan** | Phase 3 | New `pi_harness/bench/`: single-stream (prefill/decode split), concurrency sweep 1/2/4/5/8, peak-memory, optimization matrix, pass/fail vs §3 bar, comparison-table emitter. *Running it needs Runbook 0 live.* |
| **D** | **Evidence / results system** | **Code plan** | Phase 5 | `results/` tree (UC→harness→model→sub-case), experiment-record template, per-run wall-clock + tool-call-success rollup (extends `trajectory/runs.py`), comprehensive-results generator + dashboard export. |
| **E** | **Agent entry points + UC3/UC4/one-shot** | Runbook + thin code | Phase 4 | `docs/runbooks/04-uc-comparison.md`: lock reference product; Claude Code via vllm-mlx `/v1/messages`; run UC4 sub-cases (4a–4e) on mannschaft; one-shot baseline; UC2/UC5/UC6 IDE tracks. Mostly operating the harness Plans A–D produce. |
| **F** | **Mac Studio scale-up** | Runbook | Phase 6 | `docs/runbooks/06-studio-scaleup.md`: register REAP-246B as the local provider, re-run Plan C bench + Plan E comparison. Different machine. |

**Dependency order:** Runbook 0 → **A** → (B, C, D can parallelize after A) → E → F.
B needs A. C needs A + Runbook 0. D needs A. E needs A+B+C+D + Runbook 0. F needs E on Studio hardware.

## Status

- [x] Runbook 0 written; mlx-lm isolated; dev model downloading. Live serve + ≥30 tok/s check pending download.
- [x] **Plan A — Phase 1: code complete, 633 tests green, no-key air-gap unit proof passes.** Remaining: live `ms launch` e2e (Task 6 Step 3), gated on Runbook 0 server.
- [ ] Plan B / Plan C / Plan D
- [ ] Runbook E / Runbook F
