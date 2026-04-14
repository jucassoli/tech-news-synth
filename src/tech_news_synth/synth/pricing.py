"""Claude Haiku 4.5 pricing constants — stub for Plan 06-01 Task 1.

Real ``compute_cost_usd`` body lands in Plan 06-01 Task 5.
"""

from __future__ import annotations

# Stub constants exposed early so test imports succeed. Task 5 proves the
# exact values via unit tests.
MODEL_ID: str = "claude-haiku-4-5"  # last verified 2026-04-13
HAIKU_INPUT_USD_PER_MTOK: float = 1.00
HAIKU_OUTPUT_USD_PER_MTOK: float = 5.00


def compute_cost_usd(input_tokens: int, output_tokens: int) -> float:  # noqa: ARG001
    raise NotImplementedError("Plan 06-01 Task 5 implements compute_cost_usd")


__all__ = [
    "HAIKU_INPUT_USD_PER_MTOK",
    "HAIKU_OUTPUT_USD_PER_MTOK",
    "MODEL_ID",
    "compute_cost_usd",
]
