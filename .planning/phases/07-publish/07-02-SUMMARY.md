---
phase: 07-publish
plan: 02
subsystem: publish
status: awaiting-checkpoint
tags: [publish, orchestrator, scheduler, d12-order, dry-run, caps]
dependency_graph:
  requires:
    - "07-01 scaffolding (build_x_client, post_tweet, check_caps, cleanup_stale_pending)"
    - "Phase 6 SynthesisResult (status, post_id, text)"
    - "db.posts.update_post_to_posted / update_post_to_failed"
  provides:
    - "publish.run_publish — Phase 7 orchestrator"
    - "scheduler.run_cycle extended with D-12 wiring"
  affects:
    - "scheduler.run_cycle flow (stale-cleanup + cap-check + conditional publish)"
tech_stack:
  added: []
  patterns:
    - "structlog.contextvars.bind_contextvars(phase='publish') — per-cycle log binding"
    - "Structured ``counts_patch`` merged into ``run_log.counts`` by scheduler"
    - "Dry-run short-circuit: ``x_client=None`` accepted, no HTTP made (T-07-11)"
    - "pydantic v2 frozen PublishResult accepts capped/empty (scheduler-level statuses)"
key_files:
  created:
    - "tests/unit/test_publish_orchestrator.py"
    - "tests/unit/test_publish_429.py"
    - "tests/unit/test_publish_422.py"
    - "tests/unit/test_publish_skipped.py"
    - "tests/integration/test_publish_idempotency.py"
    - "tests/integration/test_publish_rate_limit.py"
    - "tests/integration/test_publish_dry_run.py"
  modified:
    - "src/tech_news_synth/publish/orchestrator.py (wrote run_publish)"
    - "src/tech_news_synth/publish/__init__.py (re-export run_publish)"
    - "src/tech_news_synth/scheduler.py (D-12 wiring)"
    - "tests/unit/test_scheduler.py (autouse phase7 fixture + 7 new tests)"
decisions:
  - "No tweepy exception escapes run_publish — all errors map to PublishResult"
  - "PublishResult.status='capped'|'empty' produced by scheduler, never by run_publish"
  - "Scheduler sets x_client=None when synthesis.status=='dry_run' (T-07-11)"
  - "cleanup_stale_pending runs BEFORE cap check + BEFORE selection-empty check (always)"
  - "New autouse fixture mock_phase7_collaborators keeps Phase 1-6 tests green with zero edits"
metrics:
  duration_minutes: 9
  completed_at: "2026-04-14T15:03:24Z"
  tasks: 3
  tests_added:
    unit: 18
    integration: 4
---

# Phase 07 Plan 02: Orchestrator + Scheduler Integration Summary

Implemented `run_publish` (the Phase 7 orchestrator) and wired it into `scheduler.run_cycle` in the locked D-12 order (`ingest → cluster → cleanup_stale_pending → check_caps → conditional synth → conditional publish → finish_cycle`). All 3 live status branches of `run_publish` are covered by unit + integration tests (posted, failed, dry_run); the two scheduler-level status values (`capped`, `empty`) are produced by `run_cycle` without calling `run_publish`. The final `checkpoint:human-verify` gate (compose smoke under `DRY_RUN=1`) is **pending operator execution**.

## What Shipped

### publish/orchestrator.py — `run_publish`
Composes Plan 01 primitives into the Phase 7 entrypoint.

Control flow:
1. `bind_contextvars(phase="publish", post_id=...)` — every log line carries the phase tag.
2. **D-09 dry_run short-circuit:** if `synthesis_result.status == "dry_run"`, emit `publish_skipped_dry_run` (info) and return `PublishResult(status='dry_run', ...)` with `counts_patch={"publish_status": "dry_run", "tweet_id": None}`. No X API call, no DB write.
3. **Live path:** call `post_tweet(x_client, text)` (Plan 01's helper — never raises, returns `XCallOutcome`).
4. Branch on `outcome.status`:
   - **posted** → `update_post_to_posted(session, post_id, tweet_id, now_utc)`; log `publish_posted` (info); return `PublishResult(status='posted', tweet_id=..., counts_patch={publish_status, tweet_id, publish_elapsed_ms})`.
   - **rate_limited** → `update_post_to_failed(session, post_id, json.dumps(error_detail))`; log `rate_limit_hit` (warning) with ISO `reset_at` + `retry_after_seconds`; return `PublishResult(status='failed', counts_patch={publish_status='failed', rate_limited=True, publish_elapsed_ms})`.
   - **publish_error** (covers 422 duplicate + generic 4xx/5xx + network/timeout) → `update_post_to_failed`; log `publish_failed` (error) with `reason`, `status_code`, `tweepy_error_type`; return `PublishResult(status='failed', counts_patch={publish_status='failed', publish_error_reason, publish_elapsed_ms})`.

Key invariants enforced:
- `update_posted` (legacy Phase 2 helper) is **never** called — regression guard against T-07-07 cost_usd overwrite.
- `error_detail` is JSON-serialized with `ensure_ascii=False, default=str` before DB persistence; round-trip-tested.
- Tweepy exceptions never escape `run_publish`; the scheduler sees failure via `PublishResult.status='failed'` + structured `counts_patch`.

### scheduler.py — D-12 wiring

Revised control flow inside the `sources_config is not None` branch:

```
run_ingest         (Phase 4)
run_clustering     (Phase 5)
cleanup_stale_pending(session, settings.publish_stale_pending_minutes)  ← D-02
check_caps(session, settings)                                            ← D-04
if cap_check.skip_synthesis:     → publish_patch = {publish_status: 'capped', ...}
elif selection empty:            → publish_patch = {publish_status: 'empty'}
else:
    run_synthesis(...)
    x_client = None if synthesis.status == 'dry_run' else build_x_client(settings)  ← T-07-11
    run_publish(session, cycle_id, synthesis, settings, x_client)
counts = {**ingest, **selection.counts_patch, **synth_patch, **publish_patch,
          "stale_pending_cleaned": stale_pending_cleaned}
finish_cycle(session, cycle_id, status, counts)
```

`grep` of scheduler.py confirms line-number ordering: `cleanup_stale_pending (110) < check_caps (115) < run_synthesis (146) < build_x_client (158) < run_publish (159)`.

### Test Delta

| Layer | New | Detail |
|-------|-----|--------|
| Unit | +18 | test_publish_orchestrator (6), test_publish_429 (2), test_publish_422 (1), test_publish_skipped (2), test_scheduler::TestPhase7Wiring (7) |
| Integration | +4 | test_publish_idempotency (2), test_publish_rate_limit (1), test_publish_dry_run (1) |

Full suite (compose Postgres via `TEST_DATABASE_URL=postgresql+psycopg://app:replace-me@172.19.0.2:5432/tech_news_synth_test`): **440 → 462 passed (+22 net, 0 failed, 0 errors)**. Phase 1-6 baseline preserved via a new autouse `mock_phase7_collaborators` fixture that gives default no-op mocks for the four new scheduler collaborators; existing tests required zero edits except one assertion (`test_run_cycle_calls_run_ingest_with_counts`) that now uses subset comparison to accommodate the two new counts keys (`publish_status`, `stale_pending_cleaned`).

## PUBLISH-* Coverage Map

| Requirement | Test(s) |
|-------------|---------|
| PUBLISH-01 (OAuth 1.0a 4-secret client; no bearer-only path) | Plan 01 `test_publish_client.py` (9 tests) + Plan 02 `test_publish_orchestrator.py::test_posted_happy_path` uses client |
| PUBLISH-02 (pending → posted idempotent) | `test_publish_idempotency.py::test_pending_to_posted_full_roundtrip` + `test_mid_call_crash_simulated_by_stale_guard` |
| PUBLISH-03 (429 → structured error_detail + WARN + skip) | `test_publish_429.py` (2) + `test_publish_rate_limit.py::test_429_writes_structured_error_detail` |
| PUBLISH-04 (daily cap skips synth+publish) | `test_scheduler.py::TestPhase7Wiring::test_cap_skips_synth_and_publish` + Plan 01 `test_caps_daily.py` |
| PUBLISH-05 (monthly cost cap kill-switch) | `test_scheduler.py::TestPhase7Wiring::test_cost_cap_skips_synth_and_publish` + Plan 01 `test_caps_monthly.py` |
| PUBLISH-06 (DRY_RUN=1 → no X API call) | `test_publish_skipped.py` (2) + `test_publish_dry_run.py::test_dry_run_no_api_call` |

Cross-cutting:
- 422 duplicate → `test_publish_422.py`
- Scheduler D-12 order → `test_scheduler.py::TestPhase7Wiring::test_d12_order`
- stale_pending_cleaned always in counts → `TestPhase7Wiring::test_cleanup_stale_pending_always_runs`

## Deviations from Plan

**None material.** The plan's `<action>` block prescribed a `parent.mock_calls == [expected_order]` equality check for `test_d12_order`; I relaxed that to pairwise `names.index(a) < names.index(b)` assertions because `attach_mock` records intermediate `.return_value.__bool__` calls that vary across Python versions — the ordering guarantee is still strict and readable.

Ruff format auto-reformatted `scheduler.py` and `test_scheduler.py` (cosmetic only). No behavioral change.

## Known Stubs

None.

## Operator Checkpoint (Task 3) — PENDING

The plan's final task is `type="checkpoint:human-verify" gate="blocking"` — a compose smoke cycle under `DRY_RUN=1`. I did **NOT** execute the compose steps; they require operator-owned `.env` + volume mounts on the host.

**Handoff protocol:** see `.planning/phases/07-publish/07-02-PLAN.md` Task 3 `<how-to-verify>` Steps 1-6 (mandatory) + Step 7 (optional real-X post). Summary:

1. Set `DRY_RUN=1` in `.env`; `docker compose down -v && docker compose up -d --build`.
2. Watch logs for `cycle_start → publish_skipped_dry_run → cycle_end(status=ok)`.
3. `SELECT` on `posts` → `status='dry_run'`, `tweet_id IS NULL`, `cost_usd > 0`.
4. `SELECT counts FROM run_log` → `publish_status='dry_run'`, `stale_pending_cleaned=0`.
5. `grep -iE 'api\.x\.com|create_tweet|publish_posted|rate_limit_hit'` on app logs → empty (or only the dry-run skip).
6. Seed a stale pending row (`created_at = NOW() - INTERVAL '10 minutes'`), restart app, verify `orphaned_pending` warning + row transitions to `failed`.
7. **Optional** real-X smoke — Step 7 in the plan — costs ~$0.03 and requires operator deletion of the tweet.

Resume with "approved" to unblock the phase verifier; describe failures (which step, what log/output) otherwise. Reference: `docs/runbook-orphaned-pending.md` covers the stale-pending investigation workflow.

## Residual Risks

- **T-07-01 (mid-call crash)** — ~1-2s window between X API 2xx and DB UPDATE. Mitigated by D-02 stale-pending guard running at top of next cycle. Operator runbook documents recovery. Accepted residual.
- **T-07-10 (silenced tweepy errors)** — run_publish never raises on publish_error. Mitigated by `counts.publish_status='failed'` + `rate_limited` flags surfacing in run_log; Phase 8 OPS will alert on sustained failures.
- **T-07-11 (DRY_RUN leaking secrets)** — scheduler gates `build_x_client` behind `synthesis.status != 'dry_run'`; compose Step 5 is the live verification. Unit test `test_dry_run_builds_no_x_client` asserts the guard.

## Next Phase

**Phase 8: End-to-End + Hardening** (OPS-01..OPS-06) — Discord/Telegram alerts, health endpoint, log rotation, restart policy verification, full 24h soak under real traffic, cost-tracking dashboard.

## Self-Check: PASSED

- `src/tech_news_synth/publish/orchestrator.py` exists with `def run_publish` and exports it via `__all__`.
- `from tech_news_synth.publish import run_publish` resolves (confirmed by integration tests importing it).
- Commits present in `git log`:
  - `29578bb` feat(07-02): implement run_publish orchestrator
  - `3135e56` feat(07-02): wire run_cycle per D-12
- 462 pytest pass, 0 failed, 0 errors.
- D-12 ordering grep-verified in scheduler.py (line numbers ascending).
- Ruff check + format clean on all touched files.
- No secret leaks in `src/tech_news_synth/publish/` outside the Settings `get_secret_value()` inline sites (grep-verified).
