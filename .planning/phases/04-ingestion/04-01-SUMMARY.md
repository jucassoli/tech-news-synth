---
phase: 04-ingestion
plan: 01
subsystem: ingestion
tags: [scaffold, sources-config, source-state, article-row, httpx, tenacity]
status: complete
requirements:
  - INGEST-01
  - INGEST-03
  - INGEST-06
dependency-graph:
  requires:
    - tech_news_synth.config.Settings
    - tech_news_synth.db.base.Base
    - tech_news_synth.db.hashing.canonicalize_url
    - tech_news_synth.db.hashing.article_hash
    - tech_news_synth.db.session.SessionLocal
  provides:
    - tech_news_synth.ingest.sources_config.load_sources_config
    - tech_news_synth.ingest.sources_config.SourcesConfig
    - tech_news_synth.ingest.sources_config.{RssSource, HnFirebaseSource, RedditJsonSource, Source}
    - tech_news_synth.ingest.models.ArticleRow
    - tech_news_synth.ingest.normalize.{strip_html, build_article_row}
    - tech_news_synth.ingest.http.{build_http_client, fetch_with_retry, _RetryableHTTP}
    - tech_news_synth.db.models.SourceState
    - tech_news_synth.db.source_state.{upsert_source, get_state, mark_ok, mark_error, mark_304, mark_disabled}
---

# Phase 04 / Plan 01 — Scaffold + Core Modules

## Outcome

Foundation for Phase 4 ingestion in place. `sources.yaml` loader validates at boot via pydantic discriminated union + `yaml.safe_load`. `SourceState` table added as new Alembic revision (downstream of Phase 2 initial). `ArticleRow` pydantic model reuses Phase 2's SHA256 canonicalization. Shared sync `httpx.Client` builder + `fetch_with_retry` with custom `_RetryableHTTP(httpx.HTTPStatusError)` subclass for clean tenacity composition (5xx/429 retried; 304 short-circuits; 4xx flows to caller).

## Commits (cherry-picked onto main, preserving Phase 3 work)

- `4fab83d` — scaffold (pyyaml dep, package tree, config/sources.yaml, 24 test fixtures, red stubs)
- `fb525d8` — sources_config (pydantic discriminated union, safe_load, 5 variant fixtures)
- `a886da1` — SourceState ORM + Alembic migration `c503b386ce5e` + repo helpers
- `0022bf2` — ArticleRow + normalize.build_article_row
- `0679971` — httpx client + tenacity retry helper

## Test delta

- **142 unit passing** (baseline 106 + 36 new)
- 3 skipped red-stubs (test_fetcher_{rss,hn,reddit}.py — reserved for Plan 04-02)
- Integration: 33 passing (baseline 24 + 9 new for source_state repo and migration roundtrip)

## Interfaces exposed to Plan 04-02

- `ingest.sources_config.load_sources_config(Path) -> SourcesConfig`
- `ingest.models.ArticleRow` (pydantic v2 — source, url, canonical_url, article_hash, title, summary, published_at, fetched_at)
- `ingest.normalize.build_article_row(source, title, html_or_text, url, published_at, fetched_at) -> ArticleRow`
- `ingest.http.build_http_client(settings) -> httpx.Client` + `fetch_with_retry(client, method, url, **kw) -> httpx.Response`
- `db.source_state.{upsert_source, get_state, mark_ok, mark_error, mark_304, mark_disabled}` (session, name, ...)
- `db.models.SourceState` ORM model
- Settings extended with `sources_config_path` + `max_consecutive_failures`

## Decision fidelity

- D-01/02/03 honored — flat list + discriminator + safe_load
- D-04 honored — SourceState columns match verbatim
- D-06 honored — UA = `ByteRelevant/0.1 (+https://x.com/ByteRelevant)`, http2=True, follow_redirects=True
- D-07 honored — ArticleRow fields match INGEST-06
- tenacity config: max 3 attempts, exp 1→16s, retry on `_RetryableHTTP` (5xx + 429) + `httpx.TransportError` only

## Notes for Plan 04-02

- `test_migration_roundtrip.py` updated from `downgrade "-1"` → `downgrade "base"` because Phase 4 added a 2nd migration.
- `test_schema_invariants.py` updated `EXPECTED_TABLES` to include `source_state`.
- Red-stub tests in `tests/unit/test_fetcher_{rss,hn,reddit}.py` to be replaced with real implementations.
- 5 integration red-stubs in `tests/integration/test_{ingest_cycle,failure_isolation,conditional_get,auto_disable,orchestrator_counts}.py` reserved for 04-02.

Status: Plan 04-02 unblocked.
