---
phase: 07-publish
verified: 2026-04-12T00:00:00Z
status: passed
verdict: PASS
score: 5/5 must-haves verified
operator_sign_off:
  scope: "Compose smoke Steps 1-6 (DRY_RUN=1, including seeded 10-min stale-pending row)"
  result: "approved"
  step_7_live_post: "not required for sign-off (optional, deferred)"
bonus_findings:
  - "Phase 2 latent defect `update_posted` cost_usd overwrite bug (T-07-07) caught during Phase 7 research and fixed with regression test `test_update_posted_preserves_cost_usd`. Would have corrupted monthly-cost cap tracking as soon as Phase 6 handed off to Phase 7."
---

# Phase 7: Publish Verification Report

**Phase Goal:** Idempotently post the synthesized tweet to @ByteRelevant with hard guardrails on quota, cost, and rate limits — the only irreversible side effect in the pipeline.
**Verified:** 2026-04-12
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP SC 1-5)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | OAuth 1.0a 4-secret client used; bearer-only rejected at boot (SC-1, PUBLISH-01) | VERIFIED | `config.py:106` `_require_x_oauth_secrets` model_validator raises ValueError listing missing OAuth secrets. `publish/client.py:43-55` `build_x_client` uses 4 OAuth kwargs + `return_type=requests.Response` + `wait_on_rate_limit=False`. Covered by `tests/unit/test_config.py` (bearer reject) + `test_publish_client.py` (9 tests). |
| 2 | pending → posted\|failed idempotent; mid-crash does not duplicate (SC-2, PUBLISH-02) | VERIFIED | `orchestrator.py:87-92` calls `update_post_to_posted` on success; `:116` `update_post_to_failed` on failure. Stale-pending guard `idempotency.py:23` runs at cycle top. Operator-verified via seeded 10-min-old pending row (Step 6 of compose smoke). Tests: `test_publish_idempotency.py::test_pending_to_posted_full_roundtrip`, `test_mid_call_crash_simulated_by_stale_guard`, `test_stale_pending_guard.py` (5 integration tests). |
| 3 | 429 reads `x-rate-limit-reset`, scheduler continues (SC-3, PUBLISH-03) | VERIFIED | `client.py:69-89` catches `tweepy.TooManyRequests`, extracts `x-rate-limit-reset/remaining/limit` headers, computes `retry_after_seconds`. `orchestrator.py:118-138` logs `rate_limit_hit` WARN with ISO `reset_at`; returns PublishResult status='failed' without raising. Tests: `test_publish_429.py` (2), `test_publish_rate_limit.py::test_429_writes_structured_error_detail`. |
| 4 | Daily cap (MAX_POSTS_PER_DAY) + monthly cost kill-switch (SC-4, PUBLISH-04, PUBLISH-05) | VERIFIED | `caps.py:20-38` `check_caps` returns `CapCheckResult(skip_synthesis=daily_reached or monthly_cost_reached)`. Scheduler calls it at `scheduler.py:115` between cluster and synth. Tests: `test_caps_daily.py` (4), `test_caps_monthly.py` (4), `test_scheduler.py::TestPhase7Wiring::test_cap_skips_synth_and_publish`, `test_cost_cap_skips_synth_and_publish`. |
| 5 | DRY_RUN=1 → status='dry_run', no X call (SC-5, PUBLISH-06) | VERIFIED | `orchestrator.py:62-75` short-circuits when `synthesis_result.status == 'dry_run'`, returns PublishResult(status='dry_run') with no X call. Scheduler `scheduler.py:158` gates `build_x_client` behind non-dry-run. Tests: `test_publish_skipped.py` (2), `test_publish_dry_run.py::test_dry_run_no_api_call`. Operator-verified via compose Step 5 (grep of app logs confirms zero X API calls). |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/tech_news_synth/publish/client.py` | tweepy factory + post_tweet | VERIFIED | OAuth 1.0a 4 secrets, `return_type=requests.Response`, `functools.partial` timeout wrap, 422-duplicate special case |
| `src/tech_news_synth/publish/caps.py` | check_caps | VERIFIED | 2-query daily+monthly; `>=` boundary |
| `src/tech_news_synth/publish/idempotency.py` | cleanup_stale_pending | VERIFIED | JSON error_detail, `orphaned_pending` WARN |
| `src/tech_news_synth/publish/orchestrator.py` | run_publish | VERIFIED | 3 live branches (posted/rate_limited/publish_error) + dry_run short-circuit |
| `src/tech_news_synth/publish/models.py` | CapCheckResult, PublishResult | VERIFIED | frozen pydantic v2 |
| `src/tech_news_synth/config.py` (modified) | 4 fields + validator | VERIFIED | lines 71-74 fields; 105-123 validator |
| `src/tech_news_synth/db/posts.py` (modified) | bug fix + 5 helpers | VERIFIED | `update_posted` cost_usd preservation (lines 62-74); `update_post_to_posted/failed`, `get_stale_pending_posts`, `count_posted_today`, `sum_monthly_cost_usd` |
| `src/tech_news_synth/scheduler.py` (modified) | D-12 wiring | VERIFIED | Lines 110 (cleanup) < 115 (caps) < 146 (synth) < 158 (build_x) < 159 (publish) |
| `docs/runbook-orphaned-pending.md` | operator guide | VERIFIED | present |
| `pyproject.toml` | responses dev dep | VERIFIED | `responses>=0.25,<1` line 41 |

### Key Link Verification

| From | To | Via | Status |
|------|-----|-----|--------|
| scheduler.run_cycle | cleanup_stale_pending | direct call pre-caps | WIRED |
| scheduler.run_cycle | check_caps | pre-synth | WIRED |
| scheduler.run_cycle | build_x_client | pre-publish (guarded by dry_run) | WIRED |
| scheduler.run_cycle | run_publish | post-synth | WIRED |
| run_publish | post_tweet | XCallOutcome map | WIRED |
| run_publish | update_post_to_posted | success branch | WIRED |
| run_publish | update_post_to_failed | failure branch | WIRED |
| build_x_client | functools.partial(session.request, timeout=...) | monkey-wrap | WIRED (T-07-08) |

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| PUBLISH-01 OAuth 1.0a 4-secret | SATISFIED | config validator + build_x_client |
| PUBLISH-02 pending → posted idempotent | SATISFIED | state machine + stale guard |
| PUBLISH-03 429 handling | SATISFIED | TooManyRequests branch + header extraction |
| PUBLISH-04 daily cap | SATISFIED | count_posted_today + check_caps |
| PUBLISH-05 monthly cost cap | SATISFIED | sum_monthly_cost_usd + kill-switch |
| PUBLISH-06 DRY_RUN no X call | SATISFIED | orchestrator dry_run branch + scheduler gate |

### Context Decisions Coverage (D-01..D-13)

All 13 decisions honored verbatim (D-01 OAuth+return_type, D-02 stale guard, D-03 single-row, D-04 cap pre-synth, D-05 daily query, D-06 monthly query, D-07 429 headers, D-08 generic failure, D-09 dry_run, D-10 state machine, D-11 4 settings, D-12 scheduler order, D-13 per-cycle client).

### Anti-Pattern Scan

| Check | Result |
|-------|--------|
| tenacity around tweepy | NONE (correct — 2h cadence is retry) |
| DB migrations added | NONE (no schema change — correct) |
| Retry queue | NONE (deferred per context) |
| Alert wiring | NONE (deferred to Phase 8 OPS) |
| Secret leak in error_detail | NONE (only exception type names + api_messages) |

### Behavioral Spot-Checks

| Behavior | Check | Status |
|----------|-------|--------|
| Compose DRY_RUN cycle end-to-end | Operator compose smoke Steps 1-6 | PASS (operator approved) |
| Seeded stale pending row → marked failed | Operator compose Step 6 | PASS (operator verified `orphaned_pending` warning emitted + row transitioned to `failed`) |
| 363 unit + ~99 integration green | per 07-02 SUMMARY: 462 passed, 0 failed | PASS |
| Ruff clean | per 07-02 SUMMARY self-check | PASS |

### Human Verification Required

None outstanding. Optional Step 7 (live @ByteRelevant post costing ~$0.03) is explicitly NOT required for Phase 7 sign-off — it is the Phase 8 live-cutover exercise.

## Bonus Finding

During Phase 7 research, a latent Phase 2 defect was discovered in `db/posts.update_posted`: when called with `cost_usd=None`, the helper was overwriting the persisted cost column with `Decimal('None')`-derived NULL, which would have silently corrupted Phase 7's monthly-cost cap tracking (`sum_monthly_cost_usd` would under-count). The bug was fixed in Plan 07-01 with a regression test (`test_update_posted_preserves_cost_usd` in `tests/integration/test_posts_repo_phase7.py`) and the new state-transition helpers `update_post_to_posted` / `update_post_to_failed` deliberately do NOT touch `cost_usd` — making this class of regression structurally harder to reintroduce.

## Gaps Summary

None. All SC 1-5 truths verified; all PUBLISH-01..06 satisfied; all D-01..D-13 honored; operator signed off on compose smoke Steps 1-6 (including the stale-pending guard integration check with a seeded 10-min-old row).

---

*Verified: 2026-04-12*
*Verifier: Claude (gsd-verifier)*
