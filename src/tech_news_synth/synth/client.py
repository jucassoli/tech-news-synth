"""Anthropic SDK wrapper (SYNTH-01).

Single-call wrapper around ``client.messages.create`` pinned to ``MODEL_ID``.
No tenacity wrap — INFRA-08 (scheduler cycle isolation) handles exceptions at
the cycle boundary. Letting ``anthropic.APIError`` propagate preserves
observability (per RESEARCH §8).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tech_news_synth.synth.pricing import MODEL_ID

if TYPE_CHECKING:
    import anthropic


def call_haiku(
    client: anthropic.Anthropic,
    system: str,
    user_prompt: str,
    max_tokens: int,
) -> tuple[str, int, int]:
    """Invoke ``claude-haiku-4-5`` once.

    Returns ``(text, input_tokens, output_tokens)``. Raises anthropic
    exceptions unmodified (cycle-level isolation handles them).
    """
    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = response.content[0].text
    return text, int(response.usage.input_tokens), int(response.usage.output_tokens)


__all__ = ["call_haiku"]
