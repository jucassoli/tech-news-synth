---
phase: 04-ingestion
plan: 02
subsystem: ingestion
tags: [fetchers, orchestrator, scheduler-wiring, conditional-get, auto-disable]
status: awaiting-checkpoint
requirements:
  - INGEST-02
  - INGEST-04
  - INGEST-05
  - INGEST-07
dependency-graph:
  requires:
    - tech_news_synth.ingest.sources_config.load_sources_config
    - tech_news_synth.ingest.sources_config.SourcesConfig
    - tech_news_synth.ingest.models.ArticleRow
    - tech_news_synth.ingest.normalize.build_article_row
    - tech_news_synth.ingest.http.build_http_client
    - tech_news_synth.ingest.http.fetch_with_retry
    - tech_news_synth.db.source_state.{upsert_source,get_state,mark_ok,mark_304,mark_error,mark_disabled}
    - tech_news_synth.db.articles.upsert_batch
    - tech_news_synth.db.run_log.{start_cycle,finish_cycle}
  provides:
    - tech_news_synth.ingest.fetchers.rss.fetch
    - tech_news_synth.ingest.fetchers.hn_firebase.fetch
    - tech_news_synth.ingest.fetchers.reddit_json.fetch
    - tech_news_synth.ingest.fetchers.FETCHERS
    - tech_news_synth.ingest.orchestrator.run_ingest
    - tech_news_synth.scheduler.run_cycle (rewired)
    - tech_news_synth.scheduler.build_scheduler (accepts sources_config)
  affects:
    - src/tech_news_synth/__main__.py (loads sources.yaml at boot, INGEST-01)
tech-stack:
  added: []
  patterns:
    - "Per-source try/except isolation inside orchestrator (D-11)"
    - "Cycle-start auto-disable check + just-tripped boundary (D-12)"
    - "Conditional GET only for RSS sources (D-14)"
    - "Single aggregated upsert_batch per cycle"
key-files:
  created:
    - src/tech_news_synth/ingest/fetchers/rss.py
    - src/tech_news_synth/ingest/fetchers/hn_firebase.py
    - src/tech_news_synth/ingest/fetchers/reddit_json.py
    - src/tech_news_synth/ingest/orchestrator.py
  modified:
    - src/tech_news_synth/ingest/fetchers/__init__.py (FETCHERS registry)
    - src/tech_news_synth/scheduler.py (http_client + run_ingest wiring)
    - src/tech_news_synth/__main__.py (load_sources_config at boot)
    - tests/unit/test_fetcher_rss.py (6 tests)
    - tests/unit/test_fetcher_hn.py (5 tests)
    - tests/unit/test_fetcher_reddit.py (5 tests)
    - tests/unit/test_scheduler.py (3 new tests for Phase 4 wiring)
    - tests/integration/test_ingest_cycle.py
    - tests/integration/test_failure_isolation.py
    - tests/integration/test_conditional_get.py
    - tests/integration/test_auto_disable.py (2 tests)
    - tests/integration/test_orchestrator_counts.py
decisions:
  - "counts dict schema LOCKED: {articles_fetched: dict[str,int], articles_upserted: int, sources_ok, sources_error, sources_skipped_disabled}"
  - "Reddit self-posts always filtered (is_self=True) regardless of URL — url field on self-posts points at the reddit thread, not an external destination"
  - "scheduler.run_cycle keeps legacy _run_cycle_body hook when sources_config=None (preserves Phase 1 INFRA-08 isolation tests)"
metrics:
  duration-min: ~25
  completed: 2026-04-13
---

# Phase 04 / Plan 02 — Fetchers + Orchestrator + Integration Summary

## One-liner

Three working fetchers (RSS with conditional GET, HN Firebase topstories+items, Reddit JSON) plus the `run_ingest` orchestrator with per-source failure isolation and cycle-start auto-disable, wired into `scheduler.run_cycle` so a live compose cycle now upserts real `articles` rows and populates `source_state` + `run_log.counts`.

## Commits

- `67cb1f9` — RSS fetcher with conditional GET (D-14)
- `945a03e` — HN Firebase fetcher
- `50bbf7c` — Reddit JSON fetcher
- `5537aab` — FETCHERS registry (D-05)
- `7fb57e1` — orchestrator (isolation, auto-disable, counts)
- `2d7a7fa` — scheduler + __main__ wiring (INGEST-01 fail-fast)

## Counts schema (LOCKED)

```json
{
  "articles_fetched": {"techcrunch": 5, "verge": 5, "ars_technica": 5, "hacker_news": 1, "reddit_technology": 2},
  "articles_upserted": 18,
  "sources_ok": 5,
  "sources_error": 0,
  "sources_skipped_disabled": 0
}
```

Keys are hardcoded in the orchestrator; only `articles_fetched` has dynamic (source-name) keys, and those are keyed off operator-trusted `source.name` (T-04-14 mitigation).

## Test delta

- **Unit:** 142 → **161 passing** (+19: 6 RSS + 5 HN + 5 Reddit + 3 scheduler)
- **Integration:** 33 → **38 passing** (+5: happy path, failure isolation, conditional GET, auto-disable x2, counts JSONB roundtrip)
- All red-stubs from Plan 04-01 replaced with real tests.
- `tests/integration/test_migration_roundtrip.py` fails with a pre-existing password auth error unrelated to this plan (verified by stashing our changes — same failure). Out of scope per execution rules.
- ruff clean; ruff format clean.

## Interfaces exposed

- `ingest.fetchers.FETCHERS: dict[str, Callable]` keyed by `"rss" | "hn_firebase" | "reddit_json"`
- fetcher signature: `(source, client, state_etag, state_last_modified, config) -> (list[ArticleRow], dict[str,Any])`
- `ingest.orchestrator.run_ingest(session, config, client, settings) -> counts dict`
- `scheduler.run_cycle(settings, sources_config=None)` — legacy Phase 1 path preserved when `sources_config is None`
- `scheduler.build_scheduler(settings, sources_config=None)` — passes `sources_config` through `add_job` kwargs

## Decision fidelity

- D-01/02/03 consumed (loader from Plan 04-01)
- D-04 consumed (source_state table from Plan 04-01)
- D-05 honored — FETCHERS registry is the single dispatch point
- D-06 honored — `build_http_client()` once per cycle, closed in try/finally even on ingest error
- D-07 honored — `ArticleRow.model_dump()` dicts flow to `upsert_batch`
- D-08 honored — `max_articles_per_fetch` respected globally + per source
- D-09 honored — `max_article_age_hours` cutoff applied in every fetcher
- D-10 honored — per-source `timeout_sec` applied via `httpx.Timeout(source.timeout_sec, connect=5.0)`
- D-11 honored — per-source `try/except Exception` in orchestrator; cycle continues
- D-12 honored — cycle-start check AND just-tripped boundary both fire; `disabled_at` set only when threshold crossed
- D-13 deferred — re-enable remains Phase 8 OPS-04
- D-14 honored — RSS-only conditional GET; HN + Reddit receive `state_etag`/`state_last_modified` as None from orchestrator and ignore their signature values

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Reddit self-post filter semantics**
- **Found during:** Task 3 (test_reddit_filters_stickied_and_selfposts)
- **Issue:** Fixture `abc003` is an `is_self=true` post whose `url` starts with `http://www.reddit.com/...` (the reddit thread itself). Plan + CONTEXT D-discretion expressed the filter as `is_self=true && not url.startswith("http")` — but that leaks reddit-internal self-posts as "news". The integration test behavior expectation ("Intel layoffs" + "EU AI Act" only = 2 rows) requires dropping all self-posts.
- **Fix:** Skip any `is_self=True` post unconditionally. Documented in reddit_json module docstring: the `url` field on self-posts points back at the reddit thread.
- **Commit:** `50bbf7c`

**2. [Rule 2 - Critical] http_client lifecycle on ingest exception**
- **Found during:** Task 6 (scheduler wiring)
- **Issue:** Original plan pseudocode put `http_client.close()` in the inner try's `finally`, but `counts = run_ingest(...)` was assigned outside that scope. On exception, `counts` could end up uninitialized.
- **Fix:** Initialize `counts: dict = {}` BEFORE the try; inner finally closes the client; outer finally uses whatever `counts` holds (empty on error).
- **Commit:** `2d7a7fa`

**3. [Rule 1 - Bug] Legacy Phase 1 _run_cycle_body hook preserved**
- **Found during:** Task 6 (scheduler tests)
- **Issue:** Existing tests (`test_run_cycle_writes_run_log_on_error`) monkeypatch `_run_cycle_body` to inject failures. Removing it would break 2 Phase 1 tests.
- **Fix:** `run_cycle` accepts `sources_config=None` default; when None, calls legacy `_run_cycle_body` (no http_client built); when supplied, runs real ingest. This keeps Phase 1 INFRA-08 isolation tests green while enabling Phase 4.
- **Commit:** `2d7a7fa`

## Known Stubs

None — all fetchers return live ArticleRow data; the orchestrator's counts dict is fully populated; no placeholder UI or "coming soon" values.

## Handoff to Phase 5

- `articles` table now gets populated every cycle. Phase 5 clustering consumes `articles WHERE fetched_at >= now() - interval '6h'` (INGEST window).
- `run_log.counts` JSONB carries the per-source fetch breakdown for operator observability and Phase 8 replay.
- `source_state` table carries conditional-GET headers (rss) + failure counters (all sources) — Phase 8 OPS-04 will surface this via CLI.

## Reddit live-traffic outcome

Not yet observed — gated on Task 7 operator smoke. RESEARCH A1 contingency encoded:
- Reddit fetcher raises gracefully on 403/429/401
- Orchestrator's D-11 isolation keeps cycle moving
- 20 consecutive failures (~40h at INTERVAL_HOURS=2) auto-disables per D-12

## Remaining work before merge

**Task 7 (checkpoint:human-verify)** — Operator-driven compose smoke. See `04-02-PLAN.md` `<how-to-verify>` for the 7-step protocol. Executor intentionally stops here per plan.

## Self-Check: PASSED

- FOUND: `src/tech_news_synth/ingest/fetchers/rss.py`
- FOUND: `src/tech_news_synth/ingest/fetchers/hn_firebase.py`
- FOUND: `src/tech_news_synth/ingest/fetchers/reddit_json.py`
- FOUND: `src/tech_news_synth/ingest/fetchers/__init__.py` (FETCHERS registry)
- FOUND: `src/tech_news_synth/ingest/orchestrator.py`
- FOUND: commit `67cb1f9`
- FOUND: commit `945a03e`
- FOUND: commit `50bbf7c`
- FOUND: commit `5537aab`
- FOUND: commit `7fb57e1`
- FOUND: commit `2d7a7fa`
- VERIFIED: `uv run pytest tests/unit -q` → 161 passed
- VERIFIED: `POSTGRES_HOST=… uv run pytest tests/integration -q --ignore=tests/integration/test_migration_roundtrip.py` → 38 passed
- VERIFIED: `uv run ruff check . && uv run ruff format --check .` → clean
