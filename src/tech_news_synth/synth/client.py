"""Anthropic SDK wrapper — stub for Plan 06-01 Task 1.

Task 5 implements ``call_haiku``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import anthropic


def call_haiku(
    client: anthropic.Anthropic,  # noqa: ARG001
    system: str,  # noqa: ARG001
    user_prompt: str,  # noqa: ARG001
    max_tokens: int,  # noqa: ARG001
) -> tuple[str, int, int]:
    raise NotImplementedError("Plan 06-01 Task 5 implements call_haiku")


__all__ = ["call_haiku"]
