---
phase: 07
slug: publish
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-14
---

# Phase 07 — Validation Strategy

> Per-phase validation contract. Mix of unit (tweepy-Client-mocked via `responses` lib) + integration (live postgres, mocked X API) + manual compose smoke.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (inherits Phase 1-6 config) |
| **Config file** | `pyproject.toml` — no new markers |
| **New dev dep** | `responses>=0.25,<1` (for mocking tweepy's `requests` internals — `respx` only handles httpx) |
| **Quick run command** | `uv run pytest tests/unit/test_publish_* tests/unit/test_caps.py tests/unit/test_idempotency.py -q -x --ff` |
| **Full unit** | `uv run pytest tests/unit -q` |
| **Integration** | `uv run pytest tests/integration -q -x -m integration` |
| **Full suite** | `uv run pytest tests/ -v --cov=tech_news_synth` |
| **Estimated runtime** | ~3s unit, ~12s integration |

---

## Sampling Rate

- **After every task commit:** quick run of publish-touched files.
- **After Wave 1 (pure modules + caps + idempotency + client):** full unit suite.
- **After Wave 2 (orchestrator + scheduler wiring):** full unit + integration.
- **Before `/gsd-verify-work`:** full suite green + compose smoke (one real cycle to @ByteRelevant with the full pipeline).
- **Max feedback latency:** ~3s unit, ~15s integration.

---

## Per-Requirement Verification Map

| Requirement | Test Type | Automated Command | Wave 0 Dep |
|-------------|-----------|-------------------|------------|
| PUBLISH-01 (tweepy.Client OAuth 1.0a + 4 secrets; bearer-only rejected at boot) | unit | `pytest tests/unit/test_publish_client.py tests/unit/test_config.py -q` (client built with 4 secrets + return_type=requests.Response; Settings validator rejects config with empty x_consumer_key) | `tests/unit/test_publish_client.py`, `src/tech_news_synth/publish/client.py` |
| PUBLISH-02 (posts row status='pending' BEFORE create_tweet; success→posted+tweet_id+posted_at; failure→failed; idempotent) | integration | `pytest tests/integration/test_publish_idempotency.py -q` (simulate mid-call crash by raising after create_tweet but before UPDATE; next cycle stale-guard marks as failed; no duplicate create_tweet call) | `tests/integration/test_publish_idempotency.py` |
| PUBLISH-03 (429 → read x-rate-limit-reset, WARN log, skip cycle cleanly) | unit + integration | `pytest tests/unit/test_publish_429.py tests/integration/test_publish_rate_limit.py -q` (responses lib injects 429 with x-rate-limit-* headers; assert posts.status='failed' error_detail captures headers; scheduler doesn't crash) | `tests/unit/test_publish_429.py`, `tests/integration/test_publish_rate_limit.py` |
| PUBLISH-04 (MAX_POSTS_PER_DAY cap; synth+publish skip when capped) | integration | `pytest tests/integration/test_caps_daily.py -q` (seed 12 posted rows today UTC; cap_check returns skip_synthesis=True; run_cycle emits `daily_cap_reached`; no synth/publish calls; run_log.counts.daily_cap_skipped=true) | `tests/integration/test_caps_daily.py` |
| PUBLISH-05 (MAX_MONTHLY_COST_USD cap; hard kill-switch) | integration | `pytest tests/integration/test_caps_monthly.py -q` (seed posts summing $31 cost this month with status in posted/failed; cap_check skips; dry_run rows in same month do NOT count) | `tests/integration/test_caps_monthly.py` |
| PUBLISH-06 (DRY_RUN=1 → no X API call; posts.status='dry_run' + synthesized_text written) | integration | `pytest tests/integration/test_publish_dry_run.py -q` (Phase 6 wrote status='dry_run'; Phase 7 skips API; row unchanged except Phase 7 logs publish_skipped_dry_run) | `tests/integration/test_publish_dry_run.py` |

**Cross-cutting — stale-pending guard (D-02):** `tests/integration/test_stale_pending_guard.py` — seed a `status='pending'` row with `created_at` 6 min ago; run_publish cycle-start hook marks it as `status='failed'` with `error_detail.reason='orphaned_pending_row'` BEFORE any new publish.

**Cross-cutting — tweepy Client timeout (research §9):** `tests/unit/test_publish_client.py::test_timeout_enforced` — build client with `x_api_timeout_sec=30`; assert `client.session.request` has `timeout=30` applied via monkey-wrap (since `tweepy.Client` constructor has no `timeout` kwarg).

**Cross-cutting — 422 duplicate-tweet handling:** `tests/unit/test_publish_422.py` — inject 422 response with X error body; assert `error_detail.reason='duplicate_tweet'` and posts.status='failed' + clear log line.

**Cross-cutting — cost_usd preservation on UPDATE (research bug fix):** `tests/unit/test_posts_repo.py::test_update_posted_preserves_cost_usd` — seed post with cost_usd=0.000038; call `update_post_to_posted(post_id, tweet_id, posted_at)` WITHOUT cost_usd arg; assert row still has cost_usd=0.000038. This requires fixing the existing Phase 2 `update_posted` helper (see research §4/Open Q#2).

**Cross-cutting — scheduler wiring + revised order (D-12):** `tests/unit/test_scheduler.py` extended — mock `check_caps`, `run_synthesis`, `run_publish`; assert ordering `run_ingest → run_clustering → check_caps → (synth + publish) | (skip both)`; assert cap flags merged into counts. Phase 6 scheduler tests preserved (publish path mocked).

**Cross-cutting — empty-cluster + dry-run composition:** `tests/unit/test_publish_skipped.py` — when SynthesisResult.status='dry_run', run_publish is CALLED but returns immediately with `status='dry_run'`, no API.

---

## Wave 0 Requirements

- [ ] `responses>=0.25,<1` added to `pyproject.toml` `[project.optional-dependencies].dev` (or similar dev-deps section)
- [ ] `src/tech_news_synth/publish/` package tree (`__init__.py`, `client.py`, `caps.py`, `idempotency.py`, `orchestrator.py`, `models.py`)
- [ ] Settings extended with 4 fields per CONTEXT D-11 (`max_posts_per_day`, `max_monthly_cost_usd`, `publish_stale_pending_minutes`, `x_api_timeout_sec`) + `.env.example` + `tests/unit/test_config.py`
- [ ] Settings validator asserting all 4 X OAuth secrets present (rejects bearer-only) — PUBLISH-01
- [ ] `db/posts.py` extensions per CONTEXT + research §13:
  - [ ] `update_post_to_posted(session, post_id, tweet_id, posted_at)` — does NOT touch cost_usd/error_detail unless explicitly passed
  - [ ] `update_post_to_failed(session, post_id, error_detail_json)` — does NOT touch cost_usd
  - [ ] `get_stale_pending_posts(session, cutoff_dt) -> list[Post]`
  - [ ] `count_posted_today(session) -> int`
  - [ ] `sum_monthly_cost_usd(session) -> float`
  - [ ] **Fix existing `update_posted` helper bug (research §4):** guard `if cost_usd is not None:` so Phase 6's inserted value isn't overwritten to NULL.
- [ ] Red-stub test files for everything in per-requirement table

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real post to @ByteRelevant + delete | PUBLISH-01, 02 | Live API (real $0.03 + real tweet visible briefly) | `docker compose down -v && docker compose up -d --build`; wait for one cycle (~30-90s); check logs for `{"event":"publish_posted", ...}`; `psql ... SELECT status, tweet_id, posted_at FROM posts ORDER BY created_at DESC LIMIT 1` → status='posted', tweet_id non-null, posted_at populated; visit `https://x.com/ByteRelevant/status/<tweet_id>` → tweet visible; operator MUST manually delete the tweet via X UI to avoid leaving test content on the account. Alternatively, test with DRY_RUN=1 for no-side-effect path. |
| DRY_RUN cycle writes status='dry_run' without posting | PUBLISH-06 | Live with DRY_RUN=1 | `DRY_RUN=1` in `.env`; restart compose; one cycle; query: status='dry_run', tweet_id IS NULL, synthesized_text populated; no tweet on @ByteRelevant. |
| Daily cap triggers skip after 12 posts | PUBLISH-04 | Simulated via manual DB insert | `psql -c "INSERT INTO posts (cycle_id, status, posted_at, synthesized_text, cost_usd, hashtags) SELECT 'seed-' || g, 'posted', NOW() AT TIME ZONE 'UTC', 'seeded', 0.0, ARRAY['#tech']::text[] FROM generate_series(1,12) g;"`; restart app; next cycle logs `daily_cap_reached`, no synth/publish attempted. Cleanup: delete seeded rows. |
| Monthly cost cap triggers kill-switch | PUBLISH-05 | Simulated via manual DB insert | Seed posts with high cost_usd summing > $30 this month; restart; assert run_log.counts.monthly_cost_capped=true. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` or `<manual>` verify
- [ ] `responses` dep added; tweepy HTTP fully mockable in tests
- [ ] Phase 2 `update_posted` cost_usd bug fixed with dedicated test
- [ ] Phase 1-6 baseline preserved (320 unit + 74 integration)
- [ ] Stale-pending guard tested end-to-end
- [ ] DRY_RUN → no X API call proven in test + compose smoke
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
