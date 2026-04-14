"""Diverse-sources-first article picker (D-01).

Given a cluster's member Articles, return up to ``max_articles`` (default 5)
biased toward source diversity: round-1 picks 1 most-recent article per
distinct source; round-2 fills remaining slots by global recency across
already-represented sources.

Honors the project Core Value ("ângulo único de cada fonte"): every source
present in the cluster contributes at least one article while slots remain.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tech_news_synth.db.models import Article


def _sort_key_recent_desc(a: Any) -> tuple[float, int]:
    """(-timestamp, id) — most-recent-first, ascending id tiebreak for determinism."""
    ts = a.published_at.timestamp() if a.published_at is not None else 0.0
    return (-ts, a.id)


def pick_articles_for_synthesis(
    cluster_articles: list[Article],
    max_articles: int = 5,
) -> list[Article]:
    """Return up to ``max_articles`` articles, source-diverse first.

    Round 1: group by ``source``, each group sorted (published_at DESC, id ASC);
             take the most-recent from each distinct source, in source-insertion
             order (first-seen source first).
    Round 2: flatten remaining articles across all groups into one list sorted
             (published_at DESC, id ASC) and append until ``max_articles`` filled.
    """
    if not cluster_articles:
        return []

    # Group by source, preserving first-seen order via insertion-ordered dict.
    groups: dict[str, list[Any]] = defaultdict(list)
    for a in cluster_articles:
        groups[a.source].append(a)
    for src in groups:
        groups[src].sort(key=_sort_key_recent_desc)

    # Round 1 — one per distinct source.
    selected: list[Any] = []
    leftovers: list[Any] = []
    for _src, arts in groups.items():
        selected.append(arts[0])
        leftovers.extend(arts[1:])
        if len(selected) >= max_articles:
            return selected[:max_articles]

    # Round 2 — fill remaining slots by global recency.
    leftovers.sort(key=_sort_key_recent_desc)
    for a in leftovers:
        if len(selected) >= max_articles:
            break
        selected.append(a)

    return selected


__all__ = ["pick_articles_for_synthesis"]
