"""Fallback article picker (D-11, CLUSTER-06).

Used when no cluster qualifies (either no multi-source clusters formed or
all were rejected by anti-repeat). Keeps cadence over strict dedup per the
project's Core Value.
"""

from __future__ import annotations

from typing import Any


def pick_fallback(
    articles: list[Any],
    source_weights: dict[str, float],
) -> int | None:
    """Return the id of the best-ranked article, or None if empty.

    Rank key: ``(-source.weight, -published_at.timestamp(), id ASC)``.
    Missing source weight defaults to 1.0. Missing ``published_at``
    (None) is treated as epoch 0 (oldest).

    ``articles`` is duck-typed: each element must expose ``source: str``,
    ``published_at: datetime | None``, and ``id: int``.
    """
    if not articles:
        return None
    chosen = min(
        articles,
        key=lambda a: (
            -source_weights.get(a.source, 1.0),
            -(a.published_at.timestamp() if a.published_at is not None else 0.0),
            a.id,
        ),
    )
    return chosen.id


__all__ = ["pick_fallback"]
