"""Per-type fetcher registry (D-05).

Each fetcher is a module-level function with the signature::

    def fetch(
        source: <variant>Source,
        client: httpx.Client,
        state_etag: str | None,
        state_last_modified: str | None,
        config: SourcesConfig,
    ) -> tuple[list[ArticleRow], dict[str, Any]]

The returned meta dict always carries ``status`` ("ok" | "skipped_304") and
optional ``etag`` / ``last_modified`` for the orchestrator to persist to
``source_state``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tech_news_synth.ingest.fetchers import hn_firebase, reddit_json, rss

FETCHERS: dict[str, Callable[..., Any]] = {
    "rss": rss.fetch,
    "hn_firebase": hn_firebase.fetch,
    "reddit_json": reddit_json.fetch,
}

__all__ = ["FETCHERS"]
