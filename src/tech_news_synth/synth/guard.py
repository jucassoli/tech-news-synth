"""Output guardrails for synthesis bodies.

Rejects assistant-style/meta responses that are not directly publishable as
timeline posts. The goal is to fail safe: a skipped cycle is preferable to a
garbage tweet on the public account.
"""

from __future__ import annotations

import re

_LEADING_META_PATTERNS = (
    r"^\s*entendi[\s\.,!]",
    r"^\s*claro[\s\.,!]",
    r"^\s*com base no artigo fornecido",
    r"^\s*aqui est[áa]\s+(?:a|o)\s+(?:s[ií]ntese|resumo|texto|post)",
    r"^\s*segue\s+(?:a|o)\s+(?:s[ií]ntese|resumo|texto|post)",
    r"^\s*por favor[,:\s]",
)

_META_SNIPPETS = (
    "artigo fornecido",
    "artigos-fonte",
    "texto anterior",
    "assim poderei",
    "estou pronto para reescrever",
    "compartilhe:",
    "compartilhe os artigos",
    "aqui está a síntese",
    "aqui está o resumo",
)


def explain_invalid_body(text: str) -> str | None:
    """Return a human-readable invalid reason, or ``None`` when acceptable."""
    stripped = text.strip()
    if not stripped:
        return "empty_output"

    lowered = stripped.casefold()
    for pattern in _LEADING_META_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            return "assistant_preamble"

    for snippet in _META_SNIPPETS:
        if snippet in lowered:
            return "assistant_meta_request"

    if "\n- " in stripped or "\n• " in stripped:
        return "bullet_list"

    return None


__all__ = ["explain_invalid_body"]
