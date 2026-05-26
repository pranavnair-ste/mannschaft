"""PersistentTopology: session_id reuse, corpus prime filtered by tag."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pi_harness.topology.base import (
    AgentSpec, ModelTier, Role, RunSpec, SyncMode, TopologyMode,
)
from pi_harness.topology.persistent import PersistentTopology


def _spec(session_id: str | None) -> RunSpec:
    return RunSpec(
        goal="persistent goal",
        agents=[
            AgentSpec(name="p1", role=Role.BUILDER, model_tier=ModelTier.FAST),
            AgentSpec(name="p2", role=Role.BUILDER, model_tier=ModelTier.FAST),
        ],
        mode=TopologyMode.PERSISTENT,
        sync_mode=SyncMode.PER_AGENT,
        corpus_classifications=["tactical"],
        session_id=session_id,
    )


class TestPersistentPlan:
    def test_requires_session_id(self):
        with pytest.raises(ValueError, match="session_id"):
            PersistentTopology().plan(_spec(session_id=None))

    def test_with_session_id_produces_sequential_chain(self):
        tasks = PersistentTopology().plan(_spec(session_id="session-abc"))
        assert len(tasks) == 2
        assert tasks[0].blocked_by == []
        assert tasks[1].blocked_by == [tasks[0].task_id]

    def test_template_carries_session_id_tag(self):
        top = PersistentTopology()
        spec = _spec(session_id="session-abc")
        dct = top.build_template_dict(spec)
        assert dct["template"]["metadata"]["session_id"] == "session-abc"

    def test_prime_filters_by_session(self):
        """Reuse across two launches: corpus reader called with same session_id."""
        top = PersistentTopology()
        spec = _spec(session_id="session-xyz")
        mock_reader = MagicMock()
        mock_reader.prime.return_value = []
        top.prime_corpus(spec, reader=mock_reader)
        top.prime_corpus(spec, reader=mock_reader)
        assert mock_reader.prime.call_count == 2
        for call in mock_reader.prime.call_args_list:
            assert call.kwargs.get("session_id") == "session-xyz"
            assert call.kwargs.get("classifications") == ["tactical"]
