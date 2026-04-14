"""Claude Haiku 4.5 pricing constants + cost helper (T-06-03 mitigation).

The model id is a literal string — NEVER an alias like ``haiku-latest``.
A future SDK could silently remap an alias; the literal plus the unit-test
equality assertion makes drift loud (T-06-03).

Pricing last verified 2026-04-13 — see .planning/intel/x-api-baseline.md.
"""

from __future__ import annotations

# T-06-03: literal model id (not an alias). Unit test asserts string equality.
MODEL_ID: str = "claude-haiku-4-5"  # last verified 2026-04-13

# Haiku 4.5 pricing — last verified 2026-04-13.
HAIKU_INPUT_USD_PER_MTOK: float = 1.00
HAIKU_OUTPUT_USD_PER_MTOK: float = 5.00


def compute_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Return USD cost for a single Haiku call given token counts (SYNTH-07)."""
    return (
        (input_tokens / 1_000_000.0) * HAIKU_INPUT_USD_PER_MTOK
        + (output_tokens / 1_000_000.0) * HAIKU_OUTPUT_USD_PER_MTOK
    )


__all__ = [
    "HAIKU_INPUT_USD_PER_MTOK",
    "HAIKU_OUTPUT_USD_PER_MTOK",
    "MODEL_ID",
    "compute_cost_usd",
]
