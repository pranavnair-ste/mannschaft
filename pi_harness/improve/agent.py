"""Improve-agent: summarization helpers + the LLM call.

The agent's single public entry point is :class:`ImproveAgent` (added in
Task 7). Helpers in this module:

- :func:`summarize_trajectory` — collapse raw trajectory events into a
  high-level run shape + per-agent step list (no I/O payloads).
- :func:`summarize_corpus_metadata` — drop full ``body``, keep a 120-char
  preview + counters.
- :func:`summarize_git_diff` — keep per-file ``+N -M`` totals + the first
  and last 3 hunks per file, capped at 2000 chars.
- :func:`load_prompt_template` — read the v1 prompt template file.
- :func:`build_messages` — assemble the chat-completions ``messages`` list.

The actual ``chat.completions.create`` call lives in :class:`ImproveAgent`
so the API shape can be swapped in one place (Responses API vs Chat
Completions; see ``HARNESS_ARCHITECTURE.md``).
"""

from __future__ import annotations

import importlib.resources
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

from pi_harness.corpus.format import CorpusEntry
from pi_harness.trajectory.schema import TrajectoryEvent

__all__ = [
    "ImproveAgent",
    "ImproveError",
    "MAX_RETRIES",
    "build_messages",
    "load_prompt_template",
    "summarize_corpus_metadata",
    "summarize_git_diff",
    "summarize_trajectory",
]

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# summarize_trajectory
# ---------------------------------------------------------------------------


def summarize_trajectory(events: Sequence[TrajectoryEvent]) -> dict[str, Any]:
    """Collapse raw events into a shape suitable for prompting.

    Args:
        events: All trajectory events for one run.

    Returns:
        A dict with two keys:

        - ``run_shape``: ``{"agents": [...], "tools_used": [...],
          "outcomes": {agent_id: final_outcome}}``.
        - ``per_agent_steps``: ``{agent_id: [{"step_id", "tool",
          "outcome", "duration_ms"}, ...]}``. Raw ``input`` / ``output``
          payloads are deliberately dropped.
    """
    agents: list[str] = []
    tools_used: set[str] = set()
    per_agent: dict[str, list[dict[str, Any]]] = {}
    outcomes: dict[str, str] = {}

    # Preserve order of first appearance for stable prompts.
    seen_agents: set[str] = set()
    for ev in events:
        if ev.agent_id not in seen_agents:
            seen_agents.add(ev.agent_id)
            agents.append(ev.agent_id)
            per_agent[ev.agent_id] = []
        if ev.tool:
            tools_used.add(ev.tool)
        per_agent[ev.agent_id].append(
            {
                "step_id": ev.step_id,
                "tool": ev.tool,
                "outcome": ev.outcome,
                "duration_ms": ev.duration_ms,
            }
        )
        outcomes[ev.agent_id] = ev.outcome  # last write wins → final outcome

    return {
        "run_shape": {
            "agents": agents,
            "tools_used": sorted(tools_used),
            "outcomes": outcomes,
        },
        "per_agent_steps": per_agent,
    }


# ---------------------------------------------------------------------------
# summarize_corpus_metadata
# ---------------------------------------------------------------------------


_BODY_PREVIEW_CHARS = 120


def summarize_corpus_metadata(entries: Sequence[CorpusEntry]) -> list[dict[str, Any]]:
    """Strip ``body``, keep metadata + a 120-char body preview.

    Used to fit the entire corpus index into the prompt without blowing
    the token budget. The agent expands specific entries by id (via the
    ``prunes``-side rationale) — it doesn't need full bodies upfront.
    """
    out: list[dict[str, Any]] = []
    for e in entries:
        out.append(
            {
                "id": e.id,
                "classification": e.classification.value,
                "record_type": e.record_type.value,
                "helpful_count": e.helpful_count,
                "harmful_count": e.harmful_count,
                "last_referenced_run_id": e.last_referenced_run_id,
                "body_preview": e.body[:_BODY_PREVIEW_CHARS],
            }
        )
    return out


# ---------------------------------------------------------------------------
# summarize_git_diff
# ---------------------------------------------------------------------------


_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")
_HUNK_HEADER_RE = re.compile(r"^@@ .+ @@")
_DIFF_MAX_CHARS = 2000
_HUNKS_KEPT_PER_FILE = 3  # first 3 + last 3 retained


def _parse_diff_into_files(diff_text: str) -> list[tuple[str, list[str]]]:
    """Split a raw git diff into ``[(filename, lines), ...]``.

    Filenames come from ``diff --git a/... b/...`` headers. The header
    itself is included as the first element of ``lines`` so downstream
    code can reproduce it verbatim.
    """
    files: list[tuple[str, list[str]]] = []
    current_lines: list[str] | None = None
    current_name = ""
    for line in diff_text.splitlines():
        header_match = _DIFF_HEADER_RE.match(line)
        if header_match:
            if current_lines is not None:
                files.append((current_name, current_lines))
            current_name = header_match.group(2)  # the "b/" path
            current_lines = [line]
        else:
            if current_lines is None:
                # Junk before the first diff header — ignore.
                continue
            current_lines.append(line)
    if current_lines is not None:
        files.append((current_name, current_lines))
    return files


def _split_into_hunks(file_lines: list[str]) -> tuple[list[str], list[list[str]]]:
    """Split a single file's diff lines into (preamble, [hunk_lines, ...])."""
    preamble: list[str] = []
    hunks: list[list[str]] = []
    current_hunk: list[str] | None = None
    for line in file_lines:
        if _HUNK_HEADER_RE.match(line):
            if current_hunk is not None:
                hunks.append(current_hunk)
            current_hunk = [line]
        elif current_hunk is None:
            preamble.append(line)
        else:
            current_hunk.append(line)
    if current_hunk is not None:
        hunks.append(current_hunk)
    return preamble, hunks


def summarize_git_diff(diff_text: str) -> str:
    """Compact a git diff for prompting.

    Strategy: per file, emit a ``<filename>: +A -B`` header (counts cover
    the whole file), then the first 3 hunks, an elision marker if any
    hunks are dropped, then the last 3 hunks. Total length is capped at
    2000 chars; the tail is replaced by ``[truncated]`` if needed.
    """
    if not diff_text.strip():
        return ""

    files = _parse_diff_into_files(diff_text)
    pieces: list[str] = []
    for name, lines in files:
        added = sum(
            1 for ln in lines if ln.startswith("+") and not ln.startswith("+++")
        )
        removed = sum(
            1 for ln in lines if ln.startswith("-") and not ln.startswith("---")
        )
        _, hunks = _split_into_hunks(lines)
        pieces.append(f"{name}: +{added} -{removed}")
        if len(hunks) <= _HUNKS_KEPT_PER_FILE * 2:
            for h in hunks:
                pieces.append("\n".join(h))
        else:
            for h in hunks[:_HUNKS_KEPT_PER_FILE]:
                pieces.append("\n".join(h))
            elided = len(hunks) - _HUNKS_KEPT_PER_FILE * 2
            pieces.append(f"... <{elided} hunks elided> ...")
            for h in hunks[-_HUNKS_KEPT_PER_FILE:]:
                pieces.append("\n".join(h))

    combined = "\n".join(pieces)
    if len(combined) > _DIFF_MAX_CHARS:
        truncated_at = _DIFF_MAX_CHARS - len(" [truncated]")
        combined = combined[:truncated_at] + " [truncated]"
    return combined


# ---------------------------------------------------------------------------
# Prompt loading + message assembly (Task 6)
# ---------------------------------------------------------------------------


def load_prompt_template() -> str:
    """Read the v1 improve-agent prompt template.

    Uses :mod:`importlib.resources` so the prompt ships inside the wheel
    when installed; falls back to a sibling-path read for editable installs
    that might exhibit namespace-package quirks.
    """
    try:
        text = (
            importlib.resources.files("pi_harness.improve.prompts")
            .joinpath("improve_prompt.md")
            .read_text(encoding="utf-8")
        )
        if text:
            return text
    except (FileNotFoundError, ModuleNotFoundError):
        pass
    # Fallback path.
    fallback = Path(__file__).parent / "prompts" / "improve_prompt.md"
    return fallback.read_text(encoding="utf-8")


def build_messages(
    run_id: str,
    trajectory_summary: dict[str, Any],
    corpus_summary: list[dict[str, Any]],
    git_diff_summary: str,
    prompt_template_text: str,
) -> list[dict[str, str]]:
    """Assemble the chat-completions ``messages`` list.

    The system message is the loaded prompt template (verbatim). The user
    message bundles the four summaries in a JSON envelope plus a closing
    reminder so the model emits raw JSON instead of fenced markdown.
    """
    envelope: dict[str, Any] = {
        "run_id": run_id,
        "trajectory_summary": trajectory_summary,
        "corpus_metadata": corpus_summary,
        "git_diff_summary": git_diff_summary,
    }
    user_content = (
        json.dumps(envelope, sort_keys=True, indent=2)
        + "\n\nReturn ONLY a JSON object matching the schema in the system prompt."
    )
    return [
        {"role": "system", "content": prompt_template_text},
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------------------
# ImproveError + ImproveAgent (Task 7)
# ---------------------------------------------------------------------------


class ImproveError(Exception):
    """Raised when the improve-agent cannot produce valid output."""


# Total attempts = MAX_RETRIES + 1 (initial + 2 retries = 3 total).
MAX_RETRIES = 2


def _call_llm(
    client: Any,
    *,
    model: str,
    messages: list[dict[str, str]],
) -> str:
    """The single swap-point for the LLM API shape.

    v1 uses ``chat.completions.create`` with JSON mode. To switch to the
    Responses API or strict ``response_format={"type": "json_schema"}``,
    replace the body of this function and keep the same string return
    contract.
    """
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    return content or ""


class ImproveAgent:
    """Post-hoc improve-agent.

    Reads the (already-summarized) inputs, calls the LLM with JSON mode,
    validates the response via :func:`parse_agent_response`, retries on
    malformed output up to :data:`MAX_RETRIES` times, and returns
    ``(list[ProposedUpdate], list[ProposedPrune])``.

    Use :meth:`analyze` as the single entry point. ``client`` is exposed
    only to make testing trivial — production callers pass ``None`` and we
    construct an ``OpenAI`` client from the config.
    """

    def __init__(self, config: Any, client: Any | None = None, settings: Any | None = None) -> None:
        self._config = config
        if client is not None:
            # Injected client (tests): resolve the model from settings only.
            from pi_harness.settings import load_settings

            s = settings if settings is not None else load_settings()
            self._model = s.orchestrator.model
            self._client = client
        else:
            # Sovereign local-first: build the client + model from the reasoning
            # bucket (local needs no key; api requires OPENAI_API_KEY).
            from pi_harness.llm_direct import reasoning_client_and_model

            self._client, self._model = reasoning_client_and_model(config, settings)

    def analyze(
        self,
        run_id: str,
        events: Sequence[TrajectoryEvent],
        corpus_entries: Sequence[CorpusEntry],
        git_diff_text: str,
    ) -> tuple[list, list]:
        """Run one full improve pass; return ``(updates, prunes)``.

        Raises :class:`ImproveError` after :data:`MAX_RETRIES` + 1 failed
        attempts to coax valid JSON out of the model.
        """
        # Local import to avoid a circular reference at module import time.
        import json as _json

        import pydantic

        from pi_harness.improve.candidates import parse_agent_response

        trajectory_summary = summarize_trajectory(events)
        corpus_summary = summarize_corpus_metadata(corpus_entries)
        git_diff_summary = summarize_git_diff(git_diff_text)
        prompt_text = load_prompt_template()
        messages = build_messages(
            run_id=run_id,
            trajectory_summary=trajectory_summary,
            corpus_summary=corpus_summary,
            git_diff_summary=git_diff_summary,
            prompt_template_text=prompt_text,
        )

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            content = _call_llm(
                self._client,
                model=self._model,
                messages=messages,
            )
            try:
                updates, prunes = parse_agent_response(content)
                return updates, prunes
            except (_json.JSONDecodeError, pydantic.ValidationError) as exc:
                last_error = exc
                _LOGGER.warning(
                    "ImproveAgent attempt %d/%d produced invalid output: %s",
                    attempt + 1,
                    MAX_RETRIES + 1,
                    exc,
                )
                messages = messages + [
                    {
                        "role": "user",
                        "content": (
                            f"Your previous response was invalid: {exc}. "
                            "Re-emit ONLY valid JSON matching the schema in "
                            "the system prompt."
                        ),
                    }
                ]
                continue

        raise ImproveError(
            f"Agent produced invalid output after {MAX_RETRIES + 1} attempts: "
            f"{last_error!r}"
        )
