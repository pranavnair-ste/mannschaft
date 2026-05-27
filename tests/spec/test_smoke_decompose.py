"""Gated real-API smoke: the Decomposer against live OpenAI chat.completions.

Marked `smoke` so it is deselected by default (`-m "not smoke"`). Run with:

    OPENAI_API_KEY=sk-... uv run pytest tests/spec/test_smoke_decompose.py -v -m smoke

Verifies the chat.completions JSON-mode call shape works end-to-end and that
the real model output validates against DecompositionResult — the one part of
the spec layer that a mocked client can't prove.
"""
from __future__ import annotations

import os

import pytest

from pi_harness.config import load_config
from pi_harness.spec.decomposer import Decomposer
from pi_harness.spec.format import Spec
from pi_harness.spec.runspec import spec_to_runspec
from pi_harness.topology.coordinator import Coordinator

pytestmark = pytest.mark.smoke


def _spec() -> Spec:
    return Spec(
        id="smoke-decompose",
        title="Add a health-check endpoint",
        goal="Expose a /healthz endpoint that reports service liveness",
        acceptance_criteria=[
            "GET /healthz returns 200 with a JSON body within 50ms",
            "The endpoint reports the build SHA in the response",
        ],
        constraints=[],
        non_goals=["Authentication on the health endpoint"],
        created_at="2026-05-25T10:00:00Z",
        updated_at="2026-05-25T10:00:00Z",
        linter_score=1.0,
        status="decomposed",
    )


def test_real_decompose_then_bridge_to_runspec() -> None:
    if not os.environ.get("OPENAI_API_KEY", "").startswith("sk-"):
        pytest.skip("OPENAI_API_KEY not set (or not sk-*); decompose smoke skipped")

    config = load_config()
    tasks = Decomposer(config).decompose(_spec())

    assert tasks, "decomposer returned no tasks"
    valid_roles = {"orchestrator", "builder", "scout", "reviewer", "synthesizer"}
    assert all(t.assigned_role in valid_roles for t in tasks)

    # The real output must bridge into a RunSpec a real Coordinator accepts.
    run_spec = spec_to_runspec(_spec(), tasks)
    from unittest.mock import MagicMock

    coord = Coordinator(
        config=MagicMock(),
        clawteam_client=MagicMock(),
        corpus_reader=MagicMock(prime=MagicMock(return_value=[])),
        improve_runner=MagicMock(),
    )
    handle = coord.launch(run_spec)
    assert handle.run_id
