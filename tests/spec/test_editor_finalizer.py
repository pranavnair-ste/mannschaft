"""Regression: _finalize_run must call wait_for_completion with a timeout."""
from __future__ import annotations

from unittest.mock import MagicMock

from pi_harness.spec import editor


class _RealishCoordinator:
    """Mimics Coordinator's real signature: timeout is a required positional."""

    def __init__(self) -> None:
        self.waited_with = None

    def wait_for_completion(self, handle, timeout):  # noqa: ANN001 - test stub
        self.waited_with = timeout
        return MagicMock(success=True)

    def on_completion(self, handle):  # noqa: ANN001 - test stub
        pass


def test_finalize_run_passes_timeout(monkeypatch):
    # Don't touch the filesystem: stub the status writer.
    monkeypatch.setattr(editor, "_set_spec_status", lambda spec_id, status: None)
    coord = _RealishCoordinator()
    handle = MagicMock(run_id="run-xyz")

    editor._finalize_run(coord, handle, "spec-1")

    # Before the fix this raised TypeError (swallowed) and timeout stayed None.
    assert coord.waited_with is not None
