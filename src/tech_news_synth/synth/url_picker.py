"""Source URL picker (D-02).

From the 3-5 articles chosen by ``article_picker``, select the URL to embed
in the tweet. Rule: highest source weight first, recency tiebreak, id tiebreak.

With all weights = 1.0 (v1 default), this reduces to "most recent". Operators
tune ``config/sources.yaml`` weights to bias URL routing without code change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tech_news_synth.db.models import Article


def pick_source_url(
    selected_articles: list[Article],
    source_weights: dict[str, float],
) -> str:
    """Return the winning article's URL (D-02).

    Sort key: (-weight, -published_at_ts, id) — highest weight first, most
    recent first, lowest id first. Deterministic across identical inputs.
    """
    if not selected_articles:
        raise ValueError("pick_source_url requires at least one article")

    def key(a: Any) -> tuple[float, float, int]:
        w = source_weights.get(a.source, 1.0)
        ts = a.published_at.timestamp() if a.published_at is not None else 0.0
        return (-w, -ts, a.id)

    return min(selected_articles, key=key).url


__all__ = ["pick_source_url"]
