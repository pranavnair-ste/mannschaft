# pi (pi-coding-agent) NDJSON event format — verified 2026-05-28

Captured from `pi --print --mode json --tools read,ls "List files in /tmp..." < /dev/null`
against pi 0.73.1 with provider=openai, model=gpt-5.4-mini (user's defaults).
Raw sample: [`docs/captures/pi-stdout-json.ndjson`](../../docs/captures/pi-stdout-json.ndjson) (~300KB, 132 events).

> **Key takeaway:** the real format is **fundamentally different** from the format
> assumed in `pi_harness/guards/runner.py`'s docstring (`{"type":"tool_call",id,name,input}` /
> `{"type":"tool_result",id,output,exit_code}`). The Phase 6 parser must be designed
> against this real schema; the planned parser tasks need to be revised.

---

## 1. Top-level event types (`o.type`)

Frequency (from one tool-using turn):

| type                    | count | meaning                                            |
|-------------------------|------:|----------------------------------------------------|
| `message_update`        |   115 | streaming deltas (text / thinking / tool-call args)|
| `message_start`         |     4 | full message envelope at start                     |
| `message_end`           |     4 | full message envelope at end                       |
| `turn_start`            |     2 | start of one assistant turn                        |
| `turn_end`              |     2 | end of turn; final message with **usage/cost**     |
| `session`               |     1 | session metadata (id, version, cwd, timestamp)    |
| `agent_start`           |     1 | session begins                                     |
| `agent_end`             |     1 | session ends with full message list                |
| `tool_execution_start`  |     1 | pi has begun running a tool                        |
| `tool_execution_end`    |     1 | pi finished the tool                               |

No `tool_call` / `tool_result` events at the top level. Tool invocations are split:
- The LLM *emits* the call as streaming deltas inside `message_update`.
- pi *runs* the tool and emits `tool_execution_start` / `tool_execution_end` separately.

## 2. `message_update.assistantMessageEvent.type` (streaming sub-types)

```
text_start, text_delta, text_end
thinking_start, thinking_delta, thinking_end
toolcall_start, toolcall_delta, toolcall_end
```

So three streams (text / thinking / tool-call args) each have start/delta/end deltas.
For the capture wrapper, the actionable events are the *_end variants (full content
known) plus the standalone `tool_execution_*` events.

## 3. Verified shapes

### `session`
```json
{"type":"session","version":3,"id":"019e6d17-...","timestamp":"2026-05-28T05:39:04.186Z","cwd":"/.../mannschaft"}
```

### `tool_execution_start`
```json
{"type":"tool_execution_start",
 "toolCallId":"call_AYsM0WJwgmVXOc8oI5M8zhXh|fc_07c7428d6c0badf2016a17d4fa141c8199b53fe7cd53c8a283",
 "toolName":"ls",
 "args":{"path":"/tmp","limit":500}}
```
Note: `toolCallId` is composite (`call_<openai-id>|fc_<pi-side-id>`). `args` is a dict.

### `tool_execution_end`
```json
{"type":"tool_execution_end",
 "toolCallId":"call_...|fc_...",
 "toolName":"ls",
 "result":{"content":[{"type":"text","text":"file1\nfile2\n..."}]},
 "isError":false}
```
`result.content` is a list of typed parts (just `{type:"text",text}` for the ls
sample — other tools may produce different parts).

### `turn_end` — carries final usage + cost
```json
{"type":"turn_end",
 "message":{
   "role":"assistant",
   "model":"gpt-5.4-mini",
   "provider":"openai",
   "api":"openai-responses",
   "stopReason":"toolUse",     // or "stop", "tool_use"...
   "usage":{
     "input":642,
     "output":35,
     "cacheRead":0,
     "cacheWrite":0,
     "totalTokens":677,
     "cost":{"input":0.0004815,"output":0.0001575,"cacheRead":0,"cacheWrite":0,"total":0.000639}
   },
   "timestamp": 1779946744277,
   "responseId": "resp_...",
   "content":[ ... full content array (thinking/text/tool calls) ... ]
 }
}
```
**pi already computes per-turn USD cost.** We can use these numbers directly
instead of (or as a cross-check against) our `cost.py` model price table.

### `agent_end`
Carries the FULL conversation as a `messages` array — useful for a final
session-snapshot event but redundant with the streaming events.

---

## 4. Mapping to `TrajectoryEvent.classification`

Best-fit mapping for Phase 6 wrapper:

| pi event                         | TrajectoryEvent                       | notes                       |
|----------------------------------|---------------------------------------|-----------------------------|
| `tool_execution_start`           | `classification="tool_call"`          | input=args, tool=toolName   |
| `tool_execution_end`             | `classification="tool_result"`        | output=result, outcome=`isError ? "error" : "success"` |
| `turn_end` (assistant)           | `classification="message"`            | model, tokens_in=usage.input, tokens_out=usage.output, attach cost.total to a new field OR override event_cost via this value |
| `message_end` (user)             | (skip, or `classification="message"`) | low value                   |
| `message_update.text_end`        | (skip — covered by message_end)       | redundant streaming         |
| `thinking_*`                     | (skip in v1)                          | encrypted reasoning content |
| `session`/`agent_start`/`agent_end` | (skip)                             | wrapper-level housekeeping  |

`step_id`: use `toolCallId` for tool events; synthesize for messages (e.g. `msg-<timestamp>`).
`ts`: pi gives unix-ms (`timestamp` in messages) and ISO (`session.timestamp`); normalize to UTC datetime.

---

## 5. Discrepancies with the assumed format (`guards/runner.py` docstring)

The docstring assumes pi emits:
```
{"type":"tool_call","id":str,"name":str,"input":dict}
{"type":"tool_result","id":str,"output":dict,"exit_code"?:int}
```

Reality:
- No `tool_call` / `tool_result` top-level types.
- Tool invocations: `tool_execution_start`/`_end`, keyed by `toolCallId` (composite).
- `args` (not `input`), `result.content[].text` (not `output` dict; not `exit_code`).
- `isError` boolean (not `exit_code` int).

**Impact on Phase 6 plan:**
- Task 6.2 parser must consume the real schema above.
- Tasks 6.3/6.4 wrapper must read `OPENAI_API_KEY` from env (or accept `--api-key`) and pass through pi's flags; it can pipe pi's stdout (with `< /dev/null` to avoid the stdin-block bug) to its parser.
- `cost.py` is still useful as a fallback for events without per-turn pi usage, but the primary cost source for live runs is now pi's own `usage.cost.total`.
- Provider/model in user's settings is `openai/gpt-5.4-mini` — neither of our cost.py's pre-populated keys (`gpt-5`, `gpt-5-mini`) match this model name. Either (a) we add `gpt-5.4-mini` to MODEL_PRICES, (b) we rely on pi's own cost figures, (c) Pranav sets PI_HARNESS_MODEL_PRICES for the real models in use.

---

## 6. Reproducibility (what to run for next sample)

```bash
KEY=$(grep -E '^OPENAI_API_KEY=' ~/.config/pi-harness/.env | sed -E 's/^OPENAI_API_KEY=//; s/^"//; s/"$//')
OPENAI_API_KEY="$KEY" pi \
  --print --mode json --no-session --no-context-files --no-extensions --no-skills \
  --tools read,ls "PROMPT" \
  < /dev/null \
  > sample.ndjson 2> sample.err.log
```

Critical: `< /dev/null` — without it, pi 0.73.1 hangs (`stdin` bound to a non-TTY,
non-closed unix socket → pi never produces output even with `--print`).
