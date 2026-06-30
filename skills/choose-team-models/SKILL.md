---
name: choose-team-models
description: >
  Use right before dispatching an agentic team (after shape-spec, or when the
  pi-harness skill offers it) to choose which model is orchestrator and which is
  builder for this run. Surfaces the sovereign-vs-mixed trade-off and the
  single-local-server constraint, then applies the choice with `ms models set`.
version: 1.0.0
---

# choose-team-models — pick orchestrator & builder before a team runs

## Protocol

1. **Show the current roster + options** with Bash:
   `ms models list`
   This prints the current orchestrator/builder buckets, the available local
   models (at the configured base_url), and cloud models if a key is stored.

2. **Recommend, then ask.** Explain the trade-off:
   - **Sovereign (default):** orchestrator + builder both local — $0, offline,
     fully private. Caveat: a fully-local autonomous team on a ~30B model may
     struggle to converge on complex decompositions.
   - **Mixed (most reliable):** orchestrator = an API model (e.g. gpt-5.x) for
     dependable decomposition + review; builder = local for sovereign,
     cost-free code generation. This is the proven config.
   Ask the user which orchestrator model and which builder model they want.

3. **Encode the single-local-server constraint.** `mlx_lm.server` serves ONE
   model. So "orchestrator = local model A AND builder = local model B (a
   DIFFERENT local model)" is NOT servable from one local server. Allow only:
   same local model for both buckets, OR a mixed API/local split. Warn and
   re-ask if they pick two different local models.

4. **Apply (sticky)** with Bash, once per bucket:
   `ms models set --bucket orchestrator --provider <local|api> --model <id>`
   `ms models set --bucket builder --provider <local|api> --model <id>`
   These persist as the new defaults. (If a key is needed for `api`, point them
   to `ms models key`.)

5. **Hand off** to the `pi-harness` dispatch skill to launch the team.

## Do NOT
- Do not set two DIFFERENT local models across buckets (unservable).
- Do not change models while a run is active (`ms models set` will refuse).
