---
phase: 04
slug: ingestion
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-13
---

# Phase 04 — Validation Strategy

> Per-phase validation contract. Mix of unit (respx-mocked HTTP) + integration (live postgres) + manual compose smoke.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (inherits Phase 1/2/3 config) |
| **Config file** | `pyproject.toml` — no new markers beyond `integration` (Phase 2) |
| **Quick run command** | `uv run pytest tests/unit/test_ingest_* tests/unit/test_sources_config.py -q -x --ff` |
| **Full unit command** | `uv run pytest tests/unit -q` |
| **Integration command** | `uv run pytest tests/integration -q -x -m integration` (needs compose postgres) |
| **Full suite** | `uv run pytest tests/ -v --cov=tech_news_synth --cov-report=term-missing` |
| **Estimated runtime** | ~5s unit (respx mocks), ~20s integration |

---

## Sampling Rate

- **After every task commit:** quick run (scoped to ingest-touched test files).
- **After Wave 1 (config/models/fetchers) commits:** full unit suite.
- **After Wave 2 (orchestrator + scheduler wiring) commits:** full unit + integration.
- **Before `/gsd-verify-work`:** full suite green + one manual compose-smoke cycle confirming real-network fetch to all 5 sources (or documented Reddit fallback).
- **Max feedback latency:** ~5s unit, ~30s integration per wave.

---

## Per-Requirement Verification Map

| Requirement | Test Type | Automated Command | Wave 0 Dep |
|-------------|-----------|-------------------|------------|
| INGEST-01 (`sources.yaml` mounted + schema valid; malformed fails boot with line-ref) | unit + manual | `pytest tests/unit/test_sources_config.py -q` (valid/missing-key/bad-type/duplicate-name/unknown-type cases) + manual boot test with a broken yaml | `tests/unit/test_sources_config.py`, `tests/fixtures/sources/{valid,bad_type,duplicate_name,missing_url,unknown_type}.yaml` |
| INGEST-02 (5 v1 sources fetchable with correct UA) | unit + integration | `pytest tests/unit/test_fetcher_rss.py tests/unit/test_fetcher_hn.py tests/unit/test_fetcher_reddit.py -q` (respx asserts UA header on every call) + `pytest tests/integration/test_ingest_cycle.py::test_all_sources_ok -q` | `tests/unit/test_fetcher_rss.py`, `test_fetcher_hn.py`, `test_fetcher_reddit.py`, `tests/fixtures/rss/techcrunch.xml`, `tests/fixtures/json/hn_topstories.json`, `tests/fixtures/json/hn_item_1.json`, `tests/fixtures/json/reddit_technology.json`, `tests/integration/test_ingest_cycle.py` |
| INGEST-03 (httpx + per-source timeout + UA + tenacity max 3 exp backoff) | unit | `pytest tests/unit/test_http_retry.py -q` (assert 3 attempts on 500s; assert UA header; assert no retry on 404) | `tests/unit/test_http_retry.py` |
| INGEST-04 (conditional GET: ETag + Last-Modified stored, sent on rerun, 304 → 0 new rows) | integration | `pytest tests/integration/test_conditional_get.py -q` (first cycle populates source_state.etag; second cycle sends If-None-Match and gets 304 from respx; assert 0 articles inserted + last_status="skipped_304") | `tests/integration/test_conditional_get.py` |
| INGEST-05 (one source 5xx/timeout → others succeed; cycle completes) | integration | `pytest tests/integration/test_failure_isolation.py -q` (respx maps techcrunch → 500; others → 200; assert articles inserted from others; assert source_state for techcrunch shows consecutive_failures=1) | `tests/integration/test_failure_isolation.py` |
| INGEST-06 (ArticleRow fields; canonical_url + article_hash; HTML-stripped summary; UTC-aware published_at) | unit | `pytest tests/unit/test_article_row.py tests/unit/test_normalize.py -q` (pydantic validation; bs4 strip roundtrip; UTC invariant; canonicalize_url determinism via Phase 2 helper) | `tests/unit/test_article_row.py`, `tests/unit/test_normalize.py` |
| INGEST-07 (auto-disable after 20 failures; re-enable only via CLI or manual) | integration | `pytest tests/integration/test_auto_disable.py -q` (seed source_state with consecutive_failures=20 → next cycle skips that source with `source_skipped_disabled` log + increments sources_skipped_disabled counter) | `tests/integration/test_auto_disable.py` |

**Cross-cutting — yaml safe_load:** `tests/unit/test_sources_config.py::test_rejects_python_object_tags` feeds a yaml with `!!python/object/apply:...` — must raise before any Python object is instantiated (proves `yaml.safe_load` not `yaml.load`).

**Cross-cutting — orchestrator contract:** `tests/integration/test_orchestrator_counts.py` asserts the returned dict has exactly `{articles_fetched, articles_upserted, sources_ok, sources_error, sources_skipped_disabled}` keys and that it round-trips through `run_log.counts` JSONB.

**Cross-cutting — scheduler integration:** update `tests/unit/test_scheduler.py` to mock `run_ingest` and assert it's called between `start_cycle` and `finish_cycle` with the current session; `finish_cycle` receives the returned counts dict.

---

## Wave 0 Requirements

- [ ] `pyyaml>=6,<7` added to `pyproject.toml` → `uv sync` → `uv.lock` regenerated
- [ ] `config/sources.yaml` committed with the 5 v1 sources (replaces Phase 1 `sources.yaml.example` stub)
- [ ] `src/tech_news_synth/ingest/` package tree created (empty `__init__.py` files only at Wave 0)
- [ ] `tests/fixtures/rss/` directory with 3 RSS samples (techcrunch, verge, ars_technica — real feed captures, stripped to ~10 entries each)
- [ ] `tests/fixtures/json/` directory with HN `topstories.json` (30 IDs) + 3 sample `item/*.json` + Reddit `r/technology/.json` snapshot
- [ ] `tests/fixtures/sources/` directory with 5 yaml variants (valid + 4 broken cases for INGEST-01 validation tests)
- [ ] Red-stub test files for every test listed in the per-requirement table above (pytest.skip until code lands)
- [ ] `Settings` schema extended with `sources_config_path` + `max_consecutive_failures` (with `.env.example` entries)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Compose boot fails fast on malformed `sources.yaml` | INGEST-01 | Requires container restart + log inspection | `docker compose down && mv config/sources.yaml config/sources.yaml.bak && echo "not: valid yaml: {" > config/sources.yaml && docker compose up -d && docker compose logs app` — container exits non-zero with `ValidationError` or yaml parse error mentioning file path + line. Restore: `mv config/sources.yaml.bak config/sources.yaml`. |
| Real-network cycle fetches all 5 sources | INGEST-02 | Live internet, live feeds | `docker compose up -d && sleep 10 && docker compose exec postgres psql -U app -d tech_news_synth -c "SELECT source, COUNT(*) FROM articles GROUP BY source ORDER BY source;"` — shows rows for `techcrunch`, `verge`, `ars_technica`, `hacker_news`, `reddit_technology`. If Reddit shows 0 or a known-failure log, document fallback per research Assumption A1. |
| Second cycle against unchanged RSS feeds skips via 304 | INGEST-04 | Requires two consecutive cycles + feed stability | After first cycle, `docker compose exec app psql ... -c "SELECT name, etag, last_status FROM source_state;"` — RSS rows have non-null `etag`. Wait for second scheduler tick (or trigger manually). Check `source_state.last_status` flips to `skipped_304` for RSS sources when feeds are unchanged (may need to verify by comparing article counts across cycles). |
| Kill-switch respected by orchestrator | INFRA-09 (carry-over) | Requires live toggle | `docker compose exec app touch /data/paused` → next cycle logs `cycle_skipped paused_by=marker` and `run_log.counts` is empty dict; no DB writes. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` (unit/integration) or `<manual>` (smoke) verify
- [ ] Sampling continuity preserved (no 3-task gap without verify)
- [ ] Wave 0 fixtures + stubs created before Wave 1 fetcher implementation
- [ ] No watch-mode flags
- [ ] Phase 1/2/3 test baseline preserved (106 unit + 24 integration + all operator-verified gates)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
