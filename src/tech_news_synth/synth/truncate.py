"""Word-boundary truncation — SYNTH-04 (D-06 last-resort step).

Used only when all LLM re-prompt attempts have exceeded the weighted budget.
The orchestrator (Plan 06-02) calls ``word_boundary_truncate`` on the final
over-budget text and appends the result to the post body.

Invariant: ``weighted_len(result) <= max_weighted`` for any ``text``.
"""

from __future__ import annotations

from tech_news_synth.synth.charcount import ELLIPSIS, weighted_len


def _largest_prefix_within(text: str, max_weighted: int) -> int:
    """Largest ``n`` with ``weighted_len(text[:n]) <= max_weighted``.

    Linear scan (O(n²) in the worst case with weighted_len's internals) —
    ``n`` is bounded by tweet length (~280) so this is fine.
    """
    if max_weighted <= 0:
        return 0
    n = len(text)
    while n > 0 and weighted_len(text[:n]) > max_weighted:
        n -= 1
    return n


def word_boundary_truncate(text: str, max_weighted: int) -> str:
    """Truncate ``text`` to ``<= max_weighted`` weighted chars.

    Algorithm:
      1. Passthrough if already within budget.
      2. Reserve weight for the ellipsis. If budget < ellipsis weight → return
         the largest prefix that fits (no ellipsis).
      3. Find the largest prefix of ``text`` fitting in ``budget_body =
         max_weighted - weighted_len(ELLIPSIS)``.
      4. Prefer cutting at the last whitespace inside that prefix; fall back
         to char-level cut if no whitespace found.
      5. Safety loop: if the result + ellipsis still exceeds the budget (edge
         cases around combining chars), shrink one char at a time.
    """
    if weighted_len(text) <= max_weighted:
        return text

    ellipsis_weight = weighted_len(ELLIPSIS)
    if max_weighted < ellipsis_weight:
        # Budget smaller than the ellipsis itself — return largest fitting prefix.
        n = _largest_prefix_within(text, max_weighted)
        return text[:n].rstrip()

    budget_body = max_weighted - ellipsis_weight
    n = _largest_prefix_within(text, budget_body)
    if n == 0:
        # Nothing fits even without the ellipsis body — return just the ellipsis
        # if it fits, otherwise empty.
        return ELLIPSIS if ellipsis_weight <= max_weighted else ""

    head = text[:n]
    # Last whitespace boundary inside the head (prefer space; also honor \n/\t).
    ws_idx = head.rfind(" ")
    for ws in ("\n", "\t"):
        idx = head.rfind(ws)
        if idx > ws_idx:
            ws_idx = idx

    if ws_idx > 0:
        truncated = head[:ws_idx].rstrip()
    else:
        truncated = head.rstrip()

    # Safety: shrink until result + ellipsis fits the budget. Handles odd
    # combining-char weight interactions with the ellipsis.
    while truncated and weighted_len(truncated + ELLIPSIS) > max_weighted:
        truncated = truncated[:-1].rstrip()

    return truncated + ELLIPSIS if truncated else ELLIPSIS


__all__ = ["word_boundary_truncate"]
