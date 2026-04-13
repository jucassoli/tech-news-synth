"""Per-cycle ingest orchestrator (D-05, D-11, D-12, D-14).

``run_ingest`` iterates every configured source, invokes its fetcher with
total per-source failure isolation, persists source_state transitions, and
upserts the aggregated ArticleRow batch. The returned counts dict has a
locked shape — it flows directly into ``run_log.counts`` JSONB.

Counts schema (locked by this plan)::

    {
      "articles_fetched": {source_name: int, ...},
      "articles_upserted": int,           # unique new rows (via ON CONFLICT)
      "sources_ok": int,
      "sources_error": int,
      "sources_skipped_disabled": int,
    }

Auto-disable semantics (D-12):
  - Check at CYCLE START: if ``consecutive_failures >= max_failures`` OR
    ``disabled_at IS NOT NULL`` → skip with ``source_skipped_disabled`` log.
  - Just-tripped: if a fetch error causes the counter to cross the threshold,
    set ``disabled_at`` so the NEXT cycle skips it. The current cycle still
    completed its attempt. Clean boundary.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.orm import Session

from tech_news_synth.config import Settings
from tech_news_synth.db import source_state as ss_repo
from tech_news_synth.db.articles import upsert_batch
from tech_news_synth.ingest.fetchers import FETCHERS
from tech_news_synth.ingest.models import ArticleRow
from tech_news_synth.ingest.sources_config import SourcesConfig
from tech_news_synth.logging import get_logger

log = get_logger(__name__)


def _classify_error(exc: Exception) -> str:
    """Map an exception to a short ``error:<kind>`` tag for source_state."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        sc = exc.response.status_code
        if 500 <= sc < 600:
            return "http_5xx"
        if 400 <= sc < 500:
            return f"http_{sc}"
    if isinstance(exc, httpx.HTTPError):
        return "http_error"
    return type(exc).__name__.lower()


def run_ingest(
    session: Session,
    config: SourcesConfig,
    client: httpx.Client,
    settings: Settings,
) -> dict[str, Any]:
    """Run one ingest cycle. Per-source isolated. Returns the counts dict.

    The caller (``scheduler.run_cycle``) owns the transaction; this function
    flushes state transitions but does not commit. However we DO call
    ``session.commit()`` once up front after upsert_source so every source has
    a visible state row when ``get_state`` runs — this is safe because the
    scheduler has already written the run_log start row.
    """
    counts: dict[str, Any] = {
        "articles_fetched": {},
        "articles_upserted": 0,
        "sources_ok": 0,
        "sources_error": 0,
        "sources_skipped_disabled": 0,
    }
    all_rows: list[ArticleRow] = []
    max_failures = settings.max_consecutive_failures

    # Ensure every source has a source_state row (idempotent).
    for src in config.sources:
        ss_repo.upsert_source(session, src.name)
    session.flush()

    for src in config.sources:
        slog = log.bind(source=src.name, source_type=src.type)
        state = ss_repo.get_state(session, src.name)
        assert state is not None, "upsert_source above guarantees existence"

        # D-12: cycle-start auto-disable check.
        if state.disabled_at is not None or state.consecutive_failures >= max_failures:
            slog.info(
                "source_skipped_disabled",
                consecutive_failures=state.consecutive_failures,
                disabled_at=state.disabled_at.isoformat() if state.disabled_at else None,
            )
            counts["sources_skipped_disabled"] += 1
            # If the threshold is crossed but disabled_at is still null, set it.
            if state.disabled_at is None:
                ss_repo.mark_disabled(session, src.name)
            continue

        fetcher = FETCHERS[src.type]
        slog.info("source_fetch_start")
        try:
            rows, meta = fetcher(
                src,
                client,
                state.etag if src.type == "rss" else None,
                state.last_modified if src.type == "rss" else None,
                config,
            )
        except Exception as exc:  # D-11: total per-source isolation
            kind = _classify_error(exc)
            slog.warning("source_fetch_error", error=str(exc), error_kind=kind)
            ss_repo.mark_error(session, src.name, kind)
            counts["sources_error"] += 1
            # Just-tripped → disable for the NEXT cycle (D-12 boundary).
            if state.consecutive_failures + 1 >= max_failures:
                ss_repo.mark_disabled(session, src.name)
            continue

        status = meta.get("status", "ok")
        if status == "skipped_304":
            slog.info("source_not_modified")
            ss_repo.mark_304(session, src.name)
            counts["sources_ok"] += 1
            counts["articles_fetched"][src.name] = 0
            continue

        counts["articles_fetched"][src.name] = len(rows)
        all_rows.extend(rows)
        ss_repo.mark_ok(
            session,
            src.name,
            etag=meta.get("etag"),
            last_modified=meta.get("last_modified"),
        )
        counts["sources_ok"] += 1
        slog.info("source_fetch_end", count=len(rows))

    # Single batch upsert across all sources (T-04-14: keys are trusted).
    if all_rows:
        row_dicts = [r.model_dump() for r in all_rows]
        counts["articles_upserted"] = upsert_batch(session, row_dicts)

    return counts


__all__ = ["run_ingest"]
