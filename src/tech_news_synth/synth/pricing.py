"""Claude Haiku 4.5 pricing constants — stub for Plan 06-01 Task 1.

Real constants + ``compute_cost_usd`` land in Plan 06-01 Task 5.
"""

from __future__ import annotations

# Stub model id — replaced with literal "claude-haiku-4-5" in Task 5.
MODEL_ID: str = "claude-haiku-4-5"  # last verified 2026-04-13


def compute_cost_usd(input_tokens: int, output_tokens: int) -> float:  # noqa: ARG001
    raise NotImplementedError("Plan 06-01 Task 5 implements compute_cost_usd")


__all__ = ["MODEL_ID", "compute_cost_usd"]
