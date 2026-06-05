"""Token -> USD cost derivation for trajectory events.

Cost has no fuel until the live-capture wrapper (Phase 6) records real token
counts; task_transition events carry model="" and zero tokens, so they cost 0.

Prices are USD per 1,000,000 tokens (input, output). The values in
``MODEL_PRICES`` are EXAMPLE defaults -- confirm real OpenAI pricing before
trusting cost figures (see the adapted plan's Unresolved decisions). Override
at runtime with ``PI_HARNESS_MODEL_PRICES`` (JSON: ``{"model": [in, out]}``).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Mapping

log = logging.getLogger(__name__)

# EXAMPLE prices (USD / 1M tokens). Update with confirmed values or override
# via PI_HARNESS_MODEL_PRICES.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
}


def _prices() -> dict[str, tuple[float, float]]:
    raw = os.environ.get("PI_HARNESS_MODEL_PRICES")
    if not raw:
        return MODEL_PRICES
    try:
        parsed = json.loads(raw)
    except ValueError:
        log.warning(
            "PI_HARNESS_MODEL_PRICES is not valid JSON; using built-in prices"
        )
        return MODEL_PRICES
    if not isinstance(parsed, dict):
        log.warning(
            "PI_HARNESS_MODEL_PRICES must be a JSON object {model: [in, out]}; "
            "using built-in prices"
        )
        return MODEL_PRICES
    # Overlay valid entries onto the built-ins, parsing per-entry so ONE
    # malformed entry can't discard the whole override (audit #25). A valid
    # entry overrides its model; other models keep their built-in price.
    prices = dict(MODEL_PRICES)
    for k, v in parsed.items():
        try:
            prices[k] = (float(v[0]), float(v[1]))
        except (TypeError, ValueError, KeyError, IndexError):
            log.warning(
                "PI_HARNESS_MODEL_PRICES entry %r is malformed (%r); skipping it",
                k, v,
            )
    return prices


def event_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """USD cost of one event's token usage. Unknown/empty model -> 0.0."""
    prices = _prices()
    if model not in prices:
        return 0.0
    price_in, price_out = prices[model]
    return (tokens_in / 1_000_000) * price_in + (tokens_out / 1_000_000) * price_out


def run_cost(events: list[Mapping[str, Any]]) -> float:
    """Sum cost across a list of event-like mappings (model/tokens_in/tokens_out)."""
    return sum(
        event_cost(
            str(e.get("model", "")),
            int(e.get("tokens_in", 0) or 0),
            int(e.get("tokens_out", 0) or 0),
        )
        for e in events
    )
