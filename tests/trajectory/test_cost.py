from __future__ import annotations

import pytest

from pi_harness.trajectory.cost import MODEL_PRICES, event_cost, run_cost


def test_known_model_cost():
    # price is USD per 1M tokens; gpt-5-mini present in table
    pin, pout = MODEL_PRICES["gpt-5-mini"]
    assert event_cost("gpt-5-mini", 1_000_000, 0) == pytest.approx(pin)
    assert event_cost("gpt-5-mini", 0, 1_000_000) == pytest.approx(pout)


def test_unknown_model_costs_zero():
    assert event_cost("totally-unknown", 1000, 1000) == 0.0


def test_empty_model_costs_zero():
    # task_transition events carry model="" and zero tokens
    assert event_cost("", 0, 0) == 0.0


def test_run_cost_sums_events():
    events = [
        {"model": "gpt-5-mini", "tokens_in": 1_000_000, "tokens_out": 0},
        {"model": "gpt-5", "tokens_in": 0, "tokens_out": 1_000_000},
    ]
    expected = MODEL_PRICES["gpt-5-mini"][0] + MODEL_PRICES["gpt-5"][1]
    assert run_cost(events) == pytest.approx(expected)


def test_run_cost_handles_missing_keys():
    # defensive: events missing token keys count as zero, not crash
    assert run_cost([{"model": "gpt-5"}]) == 0.0


def test_env_override_prices(monkeypatch):
    monkeypatch.setenv("PI_HARNESS_MODEL_PRICES", '{"custom-model": [2.0, 8.0]}')
    assert event_cost("custom-model", 1_000_000, 0) == pytest.approx(2.0)
    assert event_cost("custom-model", 0, 1_000_000) == pytest.approx(8.0)
