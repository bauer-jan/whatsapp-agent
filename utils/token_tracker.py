"""Cumulative token usage tracking across all LLM calls."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_totals = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0, "calls": 0}


def track(usage: dict) -> None:
    """Accumulate token usage from a single LLM call."""
    _totals["inputTokens"] += usage.get("inputTokens", 0)
    _totals["outputTokens"] += usage.get("outputTokens", 0)
    _totals["totalTokens"] += usage.get("totalTokens", 0)
    _totals["calls"] += 1


def log_totals() -> None:
    """Log the running total (typically at shutdown)."""
    logger.info(
        "Token totals: %d calls, %d in, %d out, %d total",
        _totals["calls"],
        _totals["inputTokens"],
        _totals["outputTokens"],
        _totals["totalTokens"],
    )


def get_totals() -> dict:
    """Return a copy of the current totals."""
    return dict(_totals)
