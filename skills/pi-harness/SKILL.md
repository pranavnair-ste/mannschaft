---
name: pi-harness
description: Launch a Pi-Agent Harness run from a spec file. Use when the user types `/pi-harness <spec-id-or-path>` to kick off a multi-agent build via the pi-harness CLI; this skill shells out to `pi-harness launch` via Bash and surfaces the output so the user can watch the run.
---

# pi-harness

**Use when:** The user invokes `/pi-harness <arg>` where `<arg>` is either
- A spec file path (`/path/to/spec.md`), or
- A spec ID (resolved to `~/.pi-harness/specs/<id>.md`).

## What to do

1. **Resolve the spec path.** If the argument is an absolute or relative path that exists, use it. Otherwise treat it as a spec_id and resolve to `~/.pi-harness/specs/<id>.md`. Verify the file exists with `ls -la <path>` via Bash before launching; if it doesn't, ask the user to clarify or offer to scaffold one with `pi-harness spec new <id> --title "..."`.

2. **Lint first.** Run `pi-harness lint <path>` via Bash. If the exit code is non-zero, surface the output and STOP — offer to help fix the violations rather than launching a flawed spec.

3. **Launch.** If lint passes, run `pi-harness launch <path>` via Bash. The CLI prints the run_id and (unless `--detach`) waits for completion, printing terminal task statuses. The skill's job is to start it and pass the output through.

4. **Don't add flags the user didn't ask for.** No `--detach`, no `--allow-warnings`. If the user wants a persistent session, pass `--session <id>`. If they explicitly ask for any flag, pass it through.

5. **On non-zero exit,** report the run_id (if printed) and the tail of the output so the user can inspect the trajectory store or branch from a partial run.

## What NOT to do

- Don't try to fix a failing spec by editing it yourself; ask the user.
- Don't run `pi-harness decompose` first — `pi-harness launch` already does that, and running it twice burns OpenAI credit.
- Don't run `pi-harness spec new` without the user asking; that's a separate intent.
- Don't shell out to `clawteam` directly — the whole point of this CLI is that the orchestration is hidden behind one command.

## Installation

To register this skill with Claude Code, symlink the directory into your plugins cache:

```bash
mkdir -p ~/.claude/plugins/local
ln -sfn /Users/pranavnair/Desktop/Personal/mannschaft/skills/pi-harness ~/.claude/plugins/local/pi-harness
```

Then restart Claude Code; `/pi-harness <arg>` appears in the slash-command menu.
