#!/usr/bin/env python3
"""GATE-01 smoke: Anthropic Haiku 4.5 minimal-prompt call + cost accounting.

Standalone operator tool per Phase 3 CONTEXT D-01. NOT wired into the
production CLI (python -m tech_news_synth); invoked via:

    uv run python scripts/smoke_anthropic.py

Outputs a single JSON line on stdout with model id, completion text, token
usage, and computed USD cost. Human-readable banner goes to stderr.

Security (T-03-01): ``anthropic_api_key`` is a ``SecretStr`` in Settings;
``.get_secret_value()`` is invoked inline at the SDK constructor call site
and never bound to a named variable. API key is never printed or logged.

Model-drift mitigation (T-03-07): ``MODEL_ID`` is a module-level constant so
future phases (synthesis in Phase 6) import a single source of truth.
"""

from __future__ import annotations

import argparse
import json
import sys

from anthropic import Anthropic

from tech_news_synth.config import load_settings

# Single source of truth for the model id (T-03-07).
MODEL_ID = "claude-haiku-4-5"

# Haiku 4.5 pricing — last verified 2026-04-13 per RESEARCH §2.
HAIKU_4_5_INPUT_USD_PER_MTOK = 1.00   # last verified 2026-04-13
HAIKU_4_5_OUTPUT_USD_PER_MTOK = 5.00  # last verified 2026-04-13

DEFAULT_PROMPT = "Responda apenas 'ok' em português."


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="smoke_anthropic",
        description=(
            "GATE-01 smoke: call claude-haiku-4-5 with a minimal prompt and "
            "print token usage + computed USD cost as one JSON line on stdout."
        ),
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help=(
            "Prompt to send to Haiku 4.5 (default: a minimal PT-BR 'ok' prompt "
            "to keep tokens at floor-level)."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    settings = load_settings()

    print(f"[smoke_anthropic] calling {MODEL_ID}...", file=sys.stderr)

    client = Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=64,
        messages=[{"role": "user", "content": args.prompt}],
    )

    completion_text = response.content[0].text
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost_usd = (
        (input_tokens / 1_000_000) * HAIKU_4_5_INPUT_USD_PER_MTOK
        + (output_tokens / 1_000_000) * HAIKU_4_5_OUTPUT_USD_PER_MTOK
    )

    summary = {
        "model": MODEL_ID,
        "completion_text": completion_text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 8),
    }
    print(json.dumps(summary, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
