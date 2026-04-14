---
phase: 07-publish
plan: 01
subsystem: publish
tags: [publish, scaffolding, posts-repo, bug-fix, cap-checks, idempotency]
dependency_graph:
  requires:
    - "Phase 2: db.posts helpers (insert_post, update_posted)"
    - "Phase 6: SynthesisResult shape"
  provides:
    - "publish.build_x_client / post_tweet / XCallOutcome"
    - "publish.check_caps / CapCheckResult"
    - "publish.cleanup_stale_pending"
    - "publish.PublishResult (model only; status values consumed by 07-02)"
    - "db.posts.update_post_to_posted / update_post_to_failed"
    - "db.posts.get_stale_pending_posts / count_posted_today / sum_monthly_cost_usd"
  affects:
    - "Settings: 4 new fields + model_validator rejecting bearer-only configs"
    - "db.posts.update_posted: T-07-07 bug fix (preserves cost_usd when None passed)"
tech_stack:
  added: ["responses>=0.25,<1 (dev dep)"]
  patterns:
    - "tweepy 4.16 OAuth 1.0a + return_type=requests.Response + functools.partial timeout monkey-wrap"
    - "Two-query cap check (count + sum) with PG 16 3-arg date_trunc('day', now(), 'UTC')"
    - "Stale-pending guard: query + structured JSON error_detail + structlog warning"
key_files:
  created:
    - "src/tech_news_synth/publish/__init__.py"
    - "src/tech_news_synth/publish/models.py"
    - "src/tech_news_synth/publish/client.py"
    - "src/tech_news_synth/publish/caps.py"
    - "src/tech_news_synth/publish/idempotency.py"
    - "src/tech_news_synth/publish/orchestrator.py (intentionally empty; Plan 07-02)"
    - "tests/unit/test_publish_client.py"
    - "tests/unit/test_caps.py"
    - "tests/unit/test_posts_repo.py"
    - "tests/integration/test_posts_repo_phase7.py"
    - "tests/integration/test_stale_pending_guard.py"
    - "tests/integration/test_caps_daily.py"
    - "tests/integration/test_caps_monthly.py"
    - "docs/runbook-orphaned-pending.md"
  modified:
    - "pyproject.toml (responses dev dep)"
    - "uv.lock"
    - ".env.example (4 Phase 7 commented vars)"
    - "src/tech_news_synth/config.py (4 fields + bearer-rejection validator)"
    - "src/tech_news_synth/db/posts.py (bug fix + 5 helpers)"
    - "tests/unit/test_config.py (+3 test functions + bounds parametrization)"
decisions:
  - "tweepy Client has NO timeout kwarg in 4.16 — enforce via functools.partial(session.request, timeout=...)"
  - "PG 16 3-arg date_trunc('day', now(), 'UTC') verified working (not 2-arg + timezone())"
  - "update_post_to_posted/failed are thinner than existing update_posted — no cost_usd/centroid params (D-10 state transitions only)"
  - "sum_monthly_cost_usd returns float (not Decimal) so Settings.max_monthly_cost_usd (float) comparison is direct"
  - "orchestrator.py deliberately empty docstring-only; 07-02 writes run_publish"
metrics:
  duration_minutes: 18
  completed_at: "2026-04-14T15:30:00Z"
  tasks: 5
  tests_added:
    unit: 17
    integration: 21
---

# Phase 07 Plan 01: Scaffolding + Pure Modules + Posts-Repo Extensions Summary

Scaffolded the Phase 7 `publish/` package with four pure, side-effect-free modules (`models`, `client`, `caps`, `idempotency`), extended `Settings` with four publish fields and a boot-time validator that rejects bearer-only X configs, added five new `db/posts.py` helpers, and fixed a pre-existing `update_posted` cost_usd overwrite bug (T-07-07) that would have corrupted monthly-cost cap tracking as soon as Phase 6 handed off to Phase 7. `orchestrator.py` is intentionally empty — Plan 07-02 composes the primitives into `run_publish` and wires the scheduler.

## What Shipped

### Settings (src/tech_news_synth/config.py)
- `max_posts_per_day: int = 12` (ge=1, le=1000)
- `max_monthly_cost_usd: float = 30.00` (ge=1.0, le=10000.0)
- `publish_stale_pending_minutes: int = 5` (ge=1, le=1440)
- `x_api_timeout_sec: int = 30` (ge=5, le=120)
- `@model_validator(mode="after") _require_x_oauth_secrets` — raises `ValueError` listing any of the 4 `x_*` OAuth secrets whose `.get_secret_value()` is empty. Enforces D-01 / PUBLISH-01.

### publish/models.py
- `CapCheckResult` (frozen pydantic): `daily_count, daily_reached, monthly_cost_usd, monthly_cost_reached, skip_synthesis`
- `PublishResult` (frozen pydantic): `post_id, status ∈ {posted, failed, dry_run, capped, empty}, tweet_id, attempts, elapsed_ms, error_detail, counts_patch`

### publish/client.py
- `XCallOutcome` frozen dataclass: `status ∈ {posted, rate_limited, publish_error}, tweet_id, elapsed_ms, error_detail`
- `build_x_client(settings) -> tweepy.Client` — OAuth 1.0a 4-secret User Context, `return_type=requests.Response`, `wait_on_rate_limit=False`, **`functools.partial` monkey-wrap of `client.session.request` enforcing `x_api_timeout_sec`** (T-07-08 — tweepy 4.16 has no timeout kwarg).
- `post_tweet(client, text) -> XCallOutcome` — never raises; maps `TooManyRequests → rate_limited` (captures `x-rate-limit-*` headers + computes `retry_after_seconds`), `HTTPException with 422+duplicate → publish_error (reason=duplicate_tweet)`, generic `HTTPException → publish_error`, any other exception (timeout, network) → `publish_error`. T-07-03 verified: no OAuth secret ever appears in `error_detail`.

### publish/caps.py
- `check_caps(session, settings) -> CapCheckResult` — composes `count_posted_today` + `sum_monthly_cost_usd`, applies `>=` boundary semantics (at-limit counts as reached).

### publish/idempotency.py
- `cleanup_stale_pending(session, cutoff_minutes) -> int` — D-02 guard. Fetches `get_stale_pending_posts`, for each row writes `error_detail = json.dumps({"reason": "orphaned_pending_row", "detected_at": <iso>, "original_created_at": <iso>})` via `update_post_to_failed`, emits `log.warning("orphaned_pending", post_id=..., cutoff_minutes=...)`.

### db/posts.py
- **BUG FIX `update_posted`** (T-07-07): `if cost_usd is not None: post.cost_usd = Decimal(...)` — preserves the column when None is passed. Regression test `test_update_posted_preserves_cost_usd`.
- `update_post_to_posted(session, post_id, tweet_id, posted_at)` — D-10 success transition; clears `error_detail` to NULL; does NOT touch `cost_usd`.
- `update_post_to_failed(session, post_id, error_detail_json)` — D-10 failure transition; does NOT touch `cost_usd`.
- `get_stale_pending_posts(session, cutoff_dt) -> list[Post]` — `status='pending' AND created_at < cutoff` ordered by id.
- `count_posted_today(session) -> int` — PG 16 `date_trunc('day', now(), 'UTC')`; filters `status='posted'` only.
- `sum_monthly_cost_usd(session) -> float` — `COALESCE(SUM(cost_usd), 0)` over `status IN ('posted','failed')` in current UTC month; excludes `dry_run`.

## Test Delta

| Layer | New | Details |
|-------|-----|---------|
| Unit | +17 | test_config (+4 publish defaults/bounds/bearer reject), test_publish_client (9), test_caps (5), test_posts_repo (1 import-guard), less prior test_config (3 replaced/extended) |
| Integration | +21 | test_posts_repo_phase7 (8), test_stale_pending_guard (5), test_caps_daily (4), test_caps_monthly (4) |

Baseline preserved: 394 → 440 pytest collections, **0 regressions**. Full suite (`pytest tests/ -q`): **440 passed**.

## Interfaces Exposed for Plan 07-02

```python
from tech_news_synth.publish import (
    build_x_client,        # tweepy.Client factory (call once per cycle)
    post_tweet,            # (client, text) -> XCallOutcome; never raises
    XCallOutcome,          # {status, tweet_id, elapsed_ms, error_detail}
    check_caps,            # (session, settings) -> CapCheckResult
    cleanup_stale_pending, # (session, cutoff_minutes) -> int
    PublishResult,         # frozen model for scheduler output
    CapCheckResult,        # frozen model
)
from tech_news_synth.db.posts import (
    update_post_to_posted,   # D-10 success; does NOT touch cost_usd
    update_post_to_failed,   # D-10 failure; does NOT touch cost_usd
    get_stale_pending_posts, # D-02
    count_posted_today,      # D-05 daily cap query
    sum_monthly_cost_usd,    # D-06 monthly cost cap query
)
```

Plan 07-02's `run_publish(session, cycle_id, synthesis_result, settings, x_client) -> PublishResult` will:
1. Check `synthesis_result.status == 'dry_run'` → return `PublishResult(status='dry_run', ...)` without calling `post_tweet`.
2. Otherwise call `post_tweet(x_client, synthesis_result.text)` → map `XCallOutcome` → `update_post_to_posted` on success, `update_post_to_failed` on rate-limit/error.
3. Always return a `PublishResult` with `counts_patch` for `run_log.counts` merging.

Scheduler wiring (also Plan 07-02):
- Call `cleanup_stale_pending(session, settings.publish_stale_pending_minutes)` at top of `run_cycle`, before ingest.
- Call `check_caps(session, settings)` between `run_clustering` and `run_synthesis`; if `skip_synthesis` skip both synth and publish.
- Build `x_client = build_x_client(settings)` once per cycle.

## Deviations from Plan

None. Ruff auto-fixed 4 quoted-string TYPE_CHECKING annotations (UP037) in already-written files and reformatted 3 files — cosmetic only, no behavioral change.

## Known Stubs

- `publish/orchestrator.py` — module docstring only. **Intentional stub owned by Plan 07-02** (explicitly called out in the plan and verified by plan-level check `! grep -q 'def run_publish' src/tech_news_synth/publish/orchestrator.py`).

No other stubs. All exposed functions have real implementations.

## Self-Check: PASSED

- `src/tech_news_synth/publish/{__init__,models,client,caps,idempotency,orchestrator}.py` — all 6 files exist.
- `docs/runbook-orphaned-pending.md` — exists.
- All 5 commits present in `git log`:
  - `d9cd1b0` scaffold
  - `1fbfa1d` posts bug fix + 5 helpers
  - `bdbdcf0` publish/client
  - `28f0ccd` publish/caps
  - `7453f4d` publish/idempotency + runbook
- 440 pytest pass, 0 failed, 0 errors (compose postgres via TEST_DATABASE_URL override).
- `grep -q 'def run_publish' publish/orchestrator.py` returns nothing (correct).
- All new symbols importable from `tech_news_synth.publish` and `tech_news_synth.db.posts`.
