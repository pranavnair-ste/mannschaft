# Custom Pi-Agent Harness — Research Synthesis & Vision

> Brainstorming notes for designing a reusable, expertise-driven harness — synthesizing patterns from Mulch (Jaymin West), Anthropic's three-agent harness, OpenAI Symphony, and Fowler/Böckeler's control-system framing.
>
> Date: 2026-05-19 · Author: Pranav · Status: Brainstorm

---

## 1. Vision

Build a custom harness on top of Pi-Agent (with adapters for Claude Code and other runtimes) that:

- Is **project-agnostic** — drops into any repo and bootstraps its own context.
- Uses an **append-only expertise corpus** (Mulch-style) as the agent's long-term memory.
- Composes **the best skills available online** as first-class plugins rather than rewriting them.
- Is a real **control system** — combines feedforward guides and feedback sensors, with a clear human-in-the-loop where it matters most.
- Treats **long-running, multi-hour work** as the default mode, not the exception.

The goal isn't another wrapper. It's a layer that makes a raw model loop reliable enough that a single operator can shepherd a multi-day project autonomously.

---

## 2. Source Synthesis

### 2.1 Mulch — Jaymin West

**Core idea.** Expertise is a passive, file-based, git-native layer that lives alongside the codebase and is consumed and produced by agents. Agents *use* Mulch; Mulch doesn't drive them.

**Patterns to adopt:**
- One JSONL file per *domain* (`db`, `api`, `testing`, etc.), append-only, advisory-locked for safe concurrent writes.
- Six built-in record types: convention, pattern, failure, decision, reference, guide.
- Three classifications — foundational / tactical / observational — drive how aggressively records age out.
- `prime` (read into prompt) vs. `record` (write back at session end) as the canonical session bracketing.
- Scope expertise to the active file set so prompts don't drown in unrelated context.
- Lifecycle hooks (pre/post-record, pre-prime, pre-prune) for org-specific filtering or redaction.

**Cautions.**
- File-based concurrency is fine for one operator plus a few agents; at higher fan-out we need a real store.
- "Append-only, then compact" only works if compaction is rigorous; otherwise the corpus rots.

### 2.2 Anthropic — Harness Design for Long-Running Application Development (March 2026)

**Core idea.** Decompose a long-running build into three specialised agents — Planner, Generator, Evaluator — communicating through files, with full context resets at each handoff to avoid coherence loss.

**Patterns to adopt:**
- Three roles, not three of the same agent. Each has its own prompt, tools, and grading frame.
- Context resets beat compaction. When context fills, clear it completely and hand off via a structured artifact.
- Sprint contracts — generator proposes a delivery + success criteria; evaluator approves before code is written.
- Weighted rubrics for subjective work, calibrated with few-shot examples so the evaluator stays consistent.
- Self-evaluation is broken. Always pair a sceptical evaluator against a generator; don't ask the generator to grade itself.

**Cautions.**
- Full three-agent harness is expensive (multi-hour, ~$200/run on Opus 4.5). Strip pieces when the underlying model gets better.
- Evaluator quality is the bottleneck — bad rubric, bad output.

### 2.3 OpenAI Symphony

**Core idea.** Long-running autonomous coding daemon. Treats the issue tracker as the control plane. Polls for work, isolates each task in its own workspace, runs an agent session, lands a PR.

**Patterns to adopt:**
- Poll → Dispatch → Resolve → Land loop as the outermost control surface.
- Issue tracker (Linear / GitHub / equivalent) is the operator's UI — no separate dashboard needed.
- One workspace per task. Hermetic isolation prevents cross-task interference and enables parallel runs.
- Proof-of-work artifacts (CI status, screenshots, traces) attached to the PR before human review.
- Ship a SPEC.md early so external consumers can replicate the daemon without reading source.

**Cautions.**
- Needs a codebase that's already harness-engineered. Without guides/sensors in the repo, agents flail.
- Per-task workspaces are heavy — only worth it if tasks are real units of work, not micro-edits.

### 2.4 Birgitta Böckeler / Martin Fowler — "Harness Engineering for Coding Agent Users" (April 2026)

**Core idea.** A harness is literally a control system. Guides are feedforward (set expectations up front); sensors are feedback (verify after the act). Use both, across three regulation categories.

**Patterns to adopt:**
- Two control types: guides (feedforward) and sensors (feedback).
- Three regulation domains: maintainability, architecture fitness, behavior.
- Computational vs. inferential trade-off — fast deterministic checks pre-commit, expensive LLM judgments post-integration.
- "Keep quality left" — cheap checks early, expensive ones only when work is ready for them.
- Continuous drift monitoring alongside change-driven checks (dead code, dep advisories).
- Coherence audit — guides and sensors must agree; contradictions are how agents learn bad habits.

**Cautions.**
- Behavior harnesses are the least mature; expect heavy manual involvement.
- Inferential controls are tempting because they handle nuance, but they hide variance.

---

## 3. Cross-Source Building Blocks

| # | Block | Source | Purpose |
|---|-------|--------|---------|
| B1 | Append-only JSONL expertise corpus per domain | Mulch | Long-term agent memory |
| B2 | `prime` / `record` session bracketing | Mulch | Per-session read/write of expertise |
| B3 | Foundational / tactical / observational shelf-life | Mulch | Drives prune/compact |
| B4 | Planner / Generator / Evaluator role split | Anthropic | Long-running coherence |
| B5 | File-based structured handoffs + context resets | Anthropic | No compaction loss between phases |
| B6 | Weighted rubric + few-shot evaluator calibration | Anthropic | Reliable subjective grading |
| B7 | Issue tracker as control plane (poll loop) | Symphony | Operator UI, no bespoke dashboard |
| B8 | Per-task isolated workspace | Symphony | Hermetic, parallel-safe runs |
| B9 | Proof-of-work artifacts attached to PR | Symphony | Human review at the right gate |
| B10 | SPEC.md as the public contract | Symphony | Adoption-friendly |
| B11 | Feedforward guides + feedback sensors | Fowler | Real control loop, not just prompts |
| B12 | Three regulation categories (maintainability, architecture fitness, behavior) | Fowler | Forces full coverage |
| B13 | Computational checks first, inferential checks second | Fowler | Cost + reliability balance |
| B14 | Coherence audit between guides and sensors | Fowler | Don't teach the agent contradictions |

---

## 4. Architecture Sketch

```
                          ┌─────────────────────────────────────┐
                          │     Issue tracker (control plane)   │
                          │   ── source of truth for work ──    │
                          └────────────┬────────────────────────┘
                                       │ poll
                                       ▼
                          ┌─────────────────────────────────────┐
                          │            Harness Daemon            │
                          │   (Pi-Agent runtime adapter layer)   │
                          └────────────┬────────────────────────┘
                                       │ dispatch
                                       ▼
        ┌──────────────────────────────────────────────────────────────┐
        │                Per-task isolated workspace                    │
        │                                                              │
        │   ┌──────────┐    ┌────────────┐    ┌────────────┐           │
        │   │ Planner  │──▶ │ Generator  │──▶ │ Evaluator  │           │
        │   └──────────┘    └────────────┘    └────────────┘           │
        │        ▲                                  │                  │
        │        │  file-based handoff (context reset between phases) │
        │        └──────────────────────────────────┘                  │
        │                                                              │
        │   ┌────────────────────────────────────────────────────┐    │
        │   │           Expertise corpus (per-domain JSONL)       │    │
        │   │       prime ◀──── per-domain ─────▶ record         │    │
        │   └────────────────────────────────────────────────────┘    │
        │                                                              │
        │   ┌────────────────────────────────────────────────────┐    │
        │   │      Guides (feedforward) + Sensors (feedback)     │    │
        │   │       maintainability · arch fitness · behavior     │    │
        │   └────────────────────────────────────────────────────┘    │
        └──────────────────────────────────────────────────────────────┘
                                       │ proof of work
                                       ▼
                          ┌─────────────────────────────────────┐
                          │            PR + artifacts            │
                          │      (CI status, traces, evals)      │
                          └─────────────────────────────────────┘
```

The harness is the box in the middle. Pi-Agent is the runtime that drives each cell inside it; the expertise corpus and the guide/sensor layer wrap every cell.

---

## 5. Open Questions

1. **Runtime adapter layout.** Jaymin West's `overstory` already does pluggable adapters for Claude Code and Pi. Fork, depend on, or build fresh? Overstory's licence and footprint matter.

2. **Skill registry.** "Works with all best skills available online" — what's the discovery model? Pull from a `claude-code-marketplace` URL list, or maintain our own curated catalogue? How do we vet a skill before it ships in the harness?

3. **Expertise scope.** Per-project corpus or shared cross-project corpus? Mulch defaults to per-repo. We probably want both — project-local plus a shared org-level corpus that primes everything.

4. **Issue tracker abstraction.** Symphony hardcodes Linear in v1. Make this swappable from day one — operator may want GitHub Issues, Notion, or a flat JSONL file.

5. **Evaluator cost discipline.** Three-agent runs are expensive. When do we *not* run the evaluator? Bypass for trivial tasks (typos, doc edits)? A "diff size triggers evaluator" rule?

6. **Compaction strategy.** Mulch's prune/compact are explicit commands. Do ours run on a schedule (Symphony-style poll) or only on session boundaries?

7. **Behavior harness coverage.** Fowler flags this as least mature. Ship with a default Playwright-based eval like Anthropic, or treat behavior verification as bring-your-own?

8. **Pi-Agent specifics.** What does Pi-Agent expose that Claude Code doesn't (and vice versa)? Design the harness to the intersection, or take a stance on the primary runtime and add adapters later?

---

## 6. First-Cut Roadmap

Cards now live in the Misc table on Notion. Order shown is what unblocks what:

1. **Create 'agent-first' repo** — seed the new harness repo (3h)
2. Audit current harness against Mulch's domain-scoped JSONL pattern (2h)
3. Migrate `expertise.yaml` → per-domain append-only JSONL files (4h)
4. Classify records by Mulch's six types (2h)
5. Tag records with foundational / tactical / observational shelf-life (1h)
6. Switch phase-to-phase handoffs from compaction to context resets (4h)
7. Tighten evaluator with weighted rubric + few-shot calibration (3h)
8. Scoped expertise injection — pull only records relevant to changed files (2h)
9. Add architecture-fitness sensors (perf + dep graph) (4h)

Total: ~25h ≈ 2.5 weeks of part-time effort at ~10h/week target.

Reading-only cards intentionally dropped — research already absorbed.

---

## 7. References

- **Mulch (Jaymin West)** — https://github.com/jayminwest/mulch
- **Anthropic — Harness Design for Long-Running Application Development (Mar 2026)** — https://www.anthropic.com/engineering/harness-design-long-running-apps
- **Anthropic — Effective harnesses for long-running agents (Nov 2025)** — https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents (predecessor; foundational context)
- **OpenAI Symphony** — https://github.com/openai/symphony
- **Birgitta Böckeler / Martin Fowler — Harness Engineering for Coding Agent Users** — https://martinfowler.com/articles/harness-engineering.html
- **Preprints.org — Harness Engineering for Language Agents (supplementary)** — https://www.preprints.org/manuscript/202603.1756
- **Related Jaymin West repos** — `seeds` (issue tracker), `canopy` (prompt management), `overstory` (multi-agent orchestration with runtime adapters)

---

*Next session: pick this up cold, work Section 5 with no rush, and let the answers shape the first sprint of the agent-first repo.*
