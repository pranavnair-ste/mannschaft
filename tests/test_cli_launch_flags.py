"""CLI launch threads --in-place / --keep-alive into the Coordinator."""
from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from pi_harness.cli import app

runner = CliRunner()


def _patches(coord):
    """Patch the launch pipeline so no real lint/decompose/launch happens.

    NOTE: ``load_config`` is imported *locally* inside ``cli.launch`` via
    ``from pi_harness.config import load_config``, so it has no module-level
    attribute on ``pi_harness.cli`` — we patch it at its source module, which
    the function-local import resolves to at call time.
    """
    spec = MagicMock(id="spec-1")
    return [
        patch("pi_harness.cli._load_spec_or_die", return_value=spec),
        patch("pi_harness.cli._lint_or_die", return_value=None),
        patch("pi_harness.config.load_config", return_value=MagicMock()),
        patch("pi_harness.cli._decompose_or_die", return_value=[]),
        patch("pi_harness.cli.spec_to_runspec", return_value=MagicMock()),
        patch("pi_harness.cli._make_coordinator", return_value=coord),
    ]


def test_launch_passes_in_place_and_keep_alive(tmp_path):
    coord = MagicMock()
    coord.launch.return_value = MagicMock(run_id="run-1", run_branch="run/abc")
    spec_file = tmp_path / "s.md"
    spec_file.write_text("x")
    with contextlib.ExitStack() as stack:
        for p in _patches(coord):
            stack.enter_context(p)
        result = runner.invoke(app, ["launch", str(spec_file), "--detach",
                                     "--in-place", "--keep-alive"])
    assert result.exit_code == 0, result.output
    kwargs = coord.launch.call_args.kwargs
    assert kwargs["in_place"] is True
    assert kwargs["keep_alive"] is True


def test_launch_defaults_isolated(tmp_path):
    coord = MagicMock()
    coord.launch.return_value = MagicMock(run_id="run-1", run_branch="run/abc")
    spec_file = tmp_path / "s.md"
    spec_file.write_text("x")
    with contextlib.ExitStack() as stack:
        for p in _patches(coord):
            stack.enter_context(p)
        result = runner.invoke(app, ["launch", str(spec_file), "--detach"])
    assert result.exit_code == 0, result.output
    kwargs = coord.launch.call_args.kwargs
    assert kwargs["in_place"] is False
    assert kwargs["keep_alive"] is False
    assert "run/abc" in result.output  # reports where the work landed
