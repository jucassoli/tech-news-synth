"""Fallback article picker (D-11, CLUSTER-06).

Plan 05-01 Task 1 scaffold — Task 5 implements the real function.
"""

from __future__ import annotations

from typing import Any


def pick_fallback(
    articles: list[Any],
    source_weights: dict[str, float],
) -> int | None:
    """Stub — real implementation in Task 5."""
    raise NotImplementedError("cluster.fallback.pick_fallback implemented in Task 5")


__all__ = ["pick_fallback"]
