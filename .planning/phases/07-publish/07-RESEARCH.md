# Phase 7: Publish - Research

**Researched:** 2026-04-12
**Domain:** X (Twitter) API v2 posting via tweepy 4.14 with OAuth 1.0a User Context — idempotent publish-or-fail flow with local cost/volume caps
**Confidence:** HIGH (tweepy source inspected directly from installed venv; Phase 3 smoke already proved the response shape end-to-end with real credentials)

## Summary

Phase 7 is the only irreversible side-effect in the pipeline: take the `posts` row Phase 6 wrote (`status='pending'` or `'dry_run'`), send one `tweepy.Client.create_tweet` call, and atomically transition the row to `posted` (success) or `failed` (429 / non-2xx / exception / timeout). Two hard guardrails gate entry: a **local daily-post cap** (X pay-per-use tier does NOT expose `x-user-limit-24hour-*` headers per Phase 3 intel — local counter is authoritative) and a **monthly USD kill-switch** (protects against billing anomalies). A **stale-pending guard** covers the ~1-2s window between `create_tweet` success and the DB UPDATE; X v2 has no idempotency-key header, so we log+mark-failed orphaned rows and surface them via an operator runbook rather than attempt auto-recovery.

Almost every technical question is already answered by work-in-place:
- **tweepy contract:** verified by inspecting `Client.__init__` and `BaseClient.request` source in the installed venv (tweepy 4.16 — well inside the `>=4.14,<5` pin). Exception hierarchy + error-code mapping is explicit in source.
- **Response shape:** Phase 3 smoke captured a real post (`tweet_id=2043757607970619474`, 377ms elapsed, headers logged). The `return_type=requests.Response` pattern must be reused so `.headers` + `.json()["data"]["id"]` work.
- **DB helpers:** `db/posts.py` already ships `update_posted`, `update_failed`, `insert_pending`, `insert_post` — Phase 7 only ADDS three cap/idempotency helpers (`get_stale_pending_posts`, `count_posted_today`, `sum_monthly_cost_usd`).

**Primary recommendation:** Reuse the exact Phase 3 `smoke_x_post.py` client-construction pattern (`return_type=requests.Response`, 4 OAuth secrets inline via `SecretStr.get_secret_value()`). Wrap `create_tweet` in a thin `publish.client.post_tweet()` helper that handles exception→`error_detail` mapping and enforces a per-request timeout via `client.session.request = functools.partial(client.session.request, timeout=settings.x_api_timeout_sec)` (monkey-wrap — tweepy's `Client` exposes no `timeout` parameter). Add `requests-mock` (or `responses`) as a dev dep for integration tests since `respx` is httpx-only and won't mock tweepy's `requests.Session`-based calls.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions (D-01..D-13)

- **D-01 — OAuth 1.0a + `return_type=requests.Response`.** `tweepy.Client(consumer_key, consumer_secret, access_token, access_token_secret, return_type=requests.Response)`. `return_type=requests.Response` is MANDATORY for rate-limit header access (PUBLISH-03). Bearer-token-only configs rejected at boot by Settings validator.
- **D-02 — Stale-pending guard (5 min default).** `SELECT id, created_at FROM posts WHERE status='pending' AND created_at < NOW() - INTERVAL '5 minutes'` → UPDATE to `status='failed'` with `error_detail={"reason":"orphaned_pending_row","detected_at":<iso>}`. NOT re-published. Operator-runbook at `docs/runbook-orphaned-pending.md`.
- **D-03 — Single-row-per-cycle invariant.** Phase 7 reads the row by `post_id` (not by cycle_id). One `create_tweet` call per cycle.
- **D-04 — Cap-check location: BETWEEN `run_clustering` and `run_synthesis`.** If capped, skip both synth AND publish; cluster audit still persisted (Phase 5 persists before returning). Cycle exits `status='ok'` with `counts.daily_cap_skipped=true`.
- **D-05 — Daily cap query.** `SELECT COUNT(*) FROM posts WHERE status='posted' AND posted_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC')`. Compared to `settings.max_posts_per_day` (default 12). Excludes pending/failed/dry_run.
- **D-06 — Monthly cost cap.** `SELECT COALESCE(SUM(cost_usd),0) FROM posts WHERE status IN ('posted','failed') AND created_at >= DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC')`. Default `MAX_MONTHLY_COST_USD=30.00`. EXCLUDES `dry_run` rows, INCLUDES `failed` (failed synth still cost money).
- **D-07 — 429 handling.** Read `x-rate-limit-reset` + `x-rate-limit-remaining` + `x-rate-limit-limit` → UPDATE post to `failed` with `error_detail={"reason":"rate_limited","status_code":429,"x_rate_limit_reset":<epoch>,...,"retry_after_seconds":<reset-now>}`. Log structured WARN. Return cleanly — scheduler ticks on. NO sleep, NO in-cycle retry.
- **D-08 — Generic failure.** Any non-429 `tweepy.TweepyException` / HTTPException / network error → UPDATE to `failed` with `error_detail={"reason":"publish_error","status_code":<int|null>,"tweepy_error_type":<class>,"message":<str>,"x_rate_limit_*":<if present>}`. Log ERROR. Propagate to scheduler's INFRA-08 handler.
- **D-09 — DRY_RUN.** `posts.status='dry_run'` → Phase 7 returns immediately; no X API call; row unchanged. Cap checks STILL fire (operator observability).
- **D-10 — State machine.** `pending → posted` (success) | `pending → failed` (error) | `dry_run` (terminal). Success UPDATE: `status='posted', tweet_id=<str>, posted_at=<utc_now>, error_detail=NULL`. Failure UPDATE: `status='failed', posted_at=NULL, error_detail=<json_str>`. `tweet_id` is TEXT.
- **D-11 — 4 new Settings fields.** `max_posts_per_day=12` (1..1000), `max_monthly_cost_usd=30.00` (1..10000), `publish_stale_pending_minutes=5` (1..1440), `x_api_timeout_sec=30` (5..120).
- **D-12 — Scheduler order.** `ingest → cluster → check_caps → (if not capped) synth → (if not dry_run + not empty) publish → finish_cycle`.
- **D-13 — X client per-cycle.** Build `tweepy.Client` once at cycle start (after cap check passes); no explicit close.

### Claude's Discretion

- Module layout: `src/tech_news_synth/publish/{__init__,client,caps,idempotency,orchestrator,models}.py` (mirrors Phase 4/5/6).
- `PublishResult` pydantic-v2 frozen model: `post_id, status, tweet_id, attempts, elapsed_ms, error_detail, counts_patch`.
- `CapCheckResult`: `daily_reached, daily_count, monthly_cost_reached, monthly_cost_usd, skip_synthesis`.
- Posts-repo extensions: `get_stale_pending_posts(session, cutoff_dt)`, `count_posted_today(session)`, `sum_monthly_cost_usd(session)`. (Existing `update_posted`/`update_failed` already satisfy D-10 — may need minor signature tune for `error_detail=None` on success.)
- Structlog `phase="publish"` binding at top of `run_publish`.
- `response.json()["data"]["id"]` raw-extraction pattern (proven Phase 3).
- Stub `docs/runbook-orphaned-pending.md` content provided inline in CONTEXT.

### Deferred Ideas (OUT OF SCOPE)

- Active retry queue for transient failures — next-cycle natural re-synthesis suffices in v1.
- Discord/Telegram alerts on cap breach — Phase 8 OPS.
- Multi-account posting / fallback handle.
- Idempotency-key via embedded marker in tweet body — UX-ugly; stale-pending guard suffices.
- Daily cap pre-warmup (fetch X timeline to count today's posts) — redundant with local counter.
- Cost forecasting — Phase 8 OPS.
- Scheduled retry of failed posts — terminal in v1.
- Per-hour / burst-control rate limiting — 12/day is well below any hourly limit.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PUBLISH-01 | Use `tweepy.Client.create_tweet` with OAuth 1.0a User Context (4 secrets); reject bearer-only at boot | §1 tweepy contract (Client 4-secret constructor verified from source); §10 Settings validator pattern |
| PUBLISH-02 | Idempotent posting — `pending` row inserted BEFORE API call; transition to `posted` on success or `failed` on error; no duplicate on mid-call crash | §4 stale-pending guard; §7 state-transition SA 2.0 patterns; T-07-01 threat |
| PUBLISH-03 | 429 handling — read `x-rate-limit-reset`, structured WARN, skip rest of cycle cleanly | §2 rate-limit headers; §3 tweepy exception hierarchy with `.response` attribute |
| PUBLISH-04 | Local daily cap `MAX_POSTS_PER_DAY=12`; when reached skip publish (cluster+synth still run+log) | §5 daily-cap SQL with `DATE_TRUNC('day', NOW(), 'UTC')`; D-04 cap placement |
| PUBLISH-05 | Monthly cost kill-switch `MAX_MONTHLY_COST_USD` from summed `posts.cost_usd` in current UTC month | §6 monthly-cost SQL; Phase 3 intel projected $10.81/mo vs $30 cap = 2.7× headroom |
| PUBLISH-06 | DRY_RUN: no X API call; `posts` row unchanged at `status='dry_run'` | §8 D-09 DRY_RUN flow; posts row ownership Phase 6 D-12 already sets status |

</phase_requirements>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `tweepy` | `>=4.14,<5` (installed: 4.16.0) | X v2 `create_tweet` with OAuth 1.0a User Context | `[VERIFIED: installed venv introspection]` — `Client.__init__` signature `(bearer_token=None, consumer_key=None, consumer_secret=None, access_token=None, access_token_secret=None, *, return_type=Response, wait_on_rate_limit=False)`. De-facto Python client. Already pinned in `pyproject.toml`. |
| `requests` | transitive via tweepy | Used by tweepy's `Client.session = requests.Session()` under the hood | `[VERIFIED: BaseClient.__init__ source]` — `self.session = requests.Session()`. We need `requests` importable only to pass `requests.Response` as the `return_type` class reference (Phase 3 pattern). |
| `pydantic` v2 | `>=2.9,<3` | `PublishResult` / `CapCheckResult` frozen boundary models | Already pinned. Mirrors Phase 4/5/6 boundary-model pattern. |
| `sqlalchemy` | `>=2.0.40,<2.1` | `posts` UPDATE statements + cap-count queries | Already pinned. SA 2.0 `select(func.count())` / `update()` Core statements. |
| `structlog` | `>=25,<26` | `log.bind(phase="publish", cycle_id=..., post_id=...)` | Already pinned. Mirrors `phase="ingest"` / `phase="cluster"` / `phase="synth"`. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `requests-mock` **OR** `responses` | TBD — **add to dev deps** | Mock tweepy's `requests.Session` in integration tests (429 header simulation, duplicate-tweet 422, 401 auth) | `[VERIFIED: venv introspection]` — project has `respx` (httpx-only, installed at 0.23.1) but NOT `responses` or `requests-mock`. tweepy uses `requests`, so respx cannot intercept. Recommend `responses>=0.25,<1` (widely used, Getsentry-maintained) or `requests-mock>=1.12,<2`. **Preference: `responses`** — richer matcher API, used by Anthropic's own SDK tests, cleaner pytest fixture. |
| `tenacity` | `>=9,<10` (already pinned) | NOT used in Phase 7 per D-07/D-08 — no in-cycle retry | Mention here only to note explicit exclusion. Next-cycle natural retry replaces tenacity retry loop. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `requests-mock` | monkeypatch `tweepy.Client.create_tweet` directly via `pytest-mock` | Mocking the higher-level method is simpler but tests less realism (headers not exercised). Recommend using both: `pytest-mock` for unit tests of pure functions, `responses`/`requests-mock` for integration tests that exercise header extraction + 429 path. |
| `return_type=requests.Response` + manual header extraction | `return_type=tweepy.Response` (default namedtuple) | Default loses `.headers`. PUBLISH-03 is impossible without `requests.Response`. `[VERIFIED: Phase 3 RESEARCH §3/4 + tweepy Discussion #1984 referenced in `smoke_x_post.py` docstring]`. |
| Wrapping `session.request` with `functools.partial(..., timeout=N)` | Custom `HTTPAdapter` subclass with mounted timeout | Monkey-wrap is 2 lines and gets every request; adapter subclassing is cleaner but more code. For v1 scope, monkey-wrap wins. Document the pattern so Phase 8 hardening can promote it if needed. |
| `tweepy.Client` with `wait_on_rate_limit=True` | `wait_on_rate_limit=False` (D-07) | `True` would auto-sleep until reset, blocking the scheduler thread for up to 15 min. Our 2h cadence + "fail-now, retry-next-cycle" pattern is strictly superior. `[VERIFIED: BaseClient.request source — `wait_on_rate_limit=True` branch calls `time.sleep`]`. |

**Installation delta:**

```bash
# Add to [dependency-groups].dev in pyproject.toml:
"responses>=0.25,<1"  # or "requests-mock>=1.12,<2"
```

**Version verification:** `[VERIFIED: npm view equivalent — `uv run pip show tweepy` → 4.16.0 which satisfies `>=4.14,<5`]`. `responses` PyPI latest: 0.25.x (stable, active maintenance). `requests-mock` latest: 1.12.x.

## Architecture Patterns

### Recommended Module Layout

```
src/tech_news_synth/publish/
├── __init__.py        # public exports: run_publish, PublishResult, CapCheckResult
├── client.py          # build_x_client() factory + post_tweet() wrapper (timeout + header extraction)
├── caps.py            # check_caps() — daily count + monthly cost queries → CapCheckResult
├── idempotency.py     # clean_stale_pending() — D-02 guard
├── orchestrator.py    # run_publish() — main phase entrypoint
└── models.py          # PublishResult, CapCheckResult (pydantic v2 frozen)
```

Mirrors Phase 4 `ingest/`, Phase 5 `cluster/`, Phase 6 `synth/`. Pure-function modules + one orchestrator.

### Pattern 1: Per-Cycle Client Construction with Enforced Timeout

**What:** `tweepy.Client` has no `timeout` kwarg. Wrap `client.session.request` with a bound timeout before any call.
**When to use:** Every cycle, before first `create_tweet`.
**Example:**

```python
# src/tech_news_synth/publish/client.py
# Source: verified from tweepy.client.BaseClient source (installed venv)
import functools
import requests
import tweepy

def build_x_client(settings: Settings) -> tweepy.Client:
    client = tweepy.Client(
        consumer_key=settings.x_consumer_key.get_secret_value(),
        consumer_secret=settings.x_consumer_secret.get_secret_value(),
        access_token=settings.x_access_token.get_secret_value(),
        access_token_secret=settings.x_access_token_secret.get_secret_value(),
        return_type=requests.Response,       # REQUIRED for header access (Phase 3)
        wait_on_rate_limit=False,            # D-07: fail-fast, no auto-sleep
    )
    # Enforce per-request timeout (tweepy exposes no constructor arg).
    _orig_request = client.session.request
    client.session.request = functools.partial(
        _orig_request, timeout=settings.x_api_timeout_sec
    )
    return client
```

### Pattern 2: `post_tweet()` Thin Wrapper Returning a Structured Result

**What:** Centralize the exception→error_detail mapping in one place so `run_publish` stays flow-control-only.
**When to use:** Called once per cycle from `run_publish`.
**Example:**

```python
# src/tech_news_synth/publish/client.py
# Source: synthesizes D-07 + D-08 + Phase 3 smoke_x_post.py patterns
from __future__ import annotations
import time
from dataclasses import dataclass
import tweepy

@dataclass(frozen=True)
class XCallOutcome:
    status: Literal["posted", "rate_limited", "publish_error"]
    tweet_id: str | None
    elapsed_ms: int
    error_detail: dict | None        # None on success

def post_tweet(client: tweepy.Client, text: str) -> XCallOutcome:
    start = time.monotonic()
    try:
        r = client.create_tweet(text=text)                      # raises on non-2xx
        elapsed_ms = int((time.monotonic() - start) * 1000)
        tweet_id = r.json()["data"]["id"]                       # Phase 3 pattern
        return XCallOutcome("posted", tweet_id, elapsed_ms, None)
    except tweepy.TooManyRequests as e:                         # 429 (D-07)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        h = e.response.headers
        reset = int(h.get("x-rate-limit-reset", "0"))
        return XCallOutcome("rate_limited", None, elapsed_ms, {
            "reason": "rate_limited",
            "status_code": 429,
            "x_rate_limit_reset": reset,
            "x_rate_limit_remaining": h.get("x-rate-limit-remaining"),
            "x_rate_limit_limit": h.get("x-rate-limit-limit"),
            "retry_after_seconds": max(0, reset - int(time.time())),
        })
    except tweepy.HTTPException as e:                           # 400/401/403/404/422/5xx (D-08)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        resp = getattr(e, "response", None)
        headers = getattr(resp, "headers", {}) if resp is not None else {}
        return XCallOutcome("publish_error", None, elapsed_ms, {
            "reason": "publish_error",
            "status_code": getattr(resp, "status_code", None),
            "tweepy_error_type": type(e).__name__,
            "message": str(e)[:500],                            # truncate defensively
            "api_codes": getattr(e, "api_codes", []),           # tweepy attr
            "api_messages": getattr(e, "api_messages", []),
            "x_rate_limit_reset": headers.get("x-rate-limit-reset"),
            "x_rate_limit_remaining": headers.get("x-rate-limit-remaining"),
        })
    except Exception as e:                                      # network / timeout / unknown (D-08)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return XCallOutcome("publish_error", None, elapsed_ms, {
            "reason": "publish_error",
            "status_code": None,
            "tweepy_error_type": type(e).__name__,
            "message": str(e)[:500],
        })
```

### Pattern 3: Cap Check as a Pure Query Function

**What:** 2 SQL queries, ~5ms total; returns a structured verdict. No side effects.
**When to use:** Exactly once per cycle, between `run_clustering` and `run_synthesis`.
**Example:**

```python
# src/tech_news_synth/publish/caps.py
# Source: D-04/D-05/D-06 verbatim
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from tech_news_synth.db.models import Post

class CapCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    daily_count: int
    daily_reached: bool
    monthly_cost_usd: float
    monthly_cost_reached: bool
    skip_synthesis: bool     # True if either cap breached

def check_caps(session: Session, settings: Settings) -> CapCheckResult:
    # D-05
    daily_count = session.execute(
        select(func.count())
        .select_from(Post)
        .where(Post.status == "posted")
        .where(Post.posted_at >= func.date_trunc("day", func.now(), "UTC"))
    ).scalar_one()
    # D-06
    monthly_cost = session.execute(
        select(func.coalesce(func.sum(Post.cost_usd), 0))
        .where(Post.status.in_(("posted", "failed")))
        .where(Post.created_at >= func.date_trunc("month", func.now(), "UTC"))
    ).scalar_one()
    monthly_cost_f = float(monthly_cost)
    daily_reached = daily_count >= settings.max_posts_per_day
    monthly_reached = monthly_cost_f >= settings.max_monthly_cost_usd
    return CapCheckResult(
        daily_count=daily_count,
        daily_reached=daily_reached,
        monthly_cost_usd=monthly_cost_f,
        monthly_cost_reached=monthly_reached,
        skip_synthesis=daily_reached or monthly_reached,
    )
```

Note the 3-arg `date_trunc('day', ts, 'UTC')` form — Postgres 16 supports it and it makes the UTC intent explicit even if the server's `TimeZone` setting drifts. `[CITED: postgresql.org/docs/current/functions-datetime.html]`.

### Pattern 4: Stale-Pending Guard (D-02)

**What:** Pre-publish query; UPDATE orphans to failed in the SAME transaction before new publish starts. Count returned in `counts_patch`.
**Example:**

```python
# src/tech_news_synth/publish/idempotency.py
from datetime import datetime, timedelta, timezone
import json
from sqlalchemy import select, update
from tech_news_synth.db.models import Post

def clean_stale_pending(session: Session, minutes: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    rows = session.execute(
        select(Post.id).where(Post.status == "pending").where(Post.created_at < cutoff)
    ).scalars().all()
    if not rows:
        return 0
    detail = json.dumps({
        "reason": "orphaned_pending_row",
        "detected_at": datetime.now(timezone.utc).isoformat(),
    })
    session.execute(
        update(Post).where(Post.id.in_(rows)).values(
            status="failed", error_detail=detail
        )
    )
    session.flush()
    return len(rows)
```

### Pattern 5: `run_publish` Orchestrator Composition

**Shape:**

```python
def run_publish(
    session: Session,
    cycle_id: str,
    synthesis_result: SynthesisResult,
    settings: Settings,
    x_client: tweepy.Client,
) -> PublishResult:
    log = _log.bind(phase="publish", cycle_id=cycle_id, post_id=synthesis_result.post_id)
    start = time.monotonic()

    # D-09: dry_run short-circuit
    post = get_post_by_id(session, synthesis_result.post_id)
    if post.status == "dry_run":
        log.info("publish_skipped_dry_run")
        return PublishResult(
            post_id=post.id, status="dry_run", tweet_id=None, attempts=0,
            elapsed_ms=int((time.monotonic() - start) * 1000),
            error_detail=None,
            counts_patch={"publish_status": "dry_run"},
        )

    # D-02: stale-pending guard (may mark THIS row if it somehow sat too long)
    cleaned = clean_stale_pending(session, settings.publish_stale_pending_minutes)
    # Re-read after potential UPDATE
    post = get_post_by_id(session, synthesis_result.post_id)
    if post.status != "pending":
        # Our row got marked by the guard — don't publish
        log.warning("publish_aborted_not_pending", current_status=post.status)
        return PublishResult(
            post_id=post.id, status="failed", tweet_id=None, attempts=0,
            elapsed_ms=int((time.monotonic() - start) * 1000),
            error_detail={"reason": "orphaned_pending_row"},
            counts_patch={"publish_status": "failed", "stale_pending_cleaned": cleaned},
        )

    # Actual publish
    outcome = post_tweet(x_client, post.synthesized_text)
    elapsed_ms = int((time.monotonic() - start) * 1000)

    if outcome.status == "posted":
        update_posted(session, post.id, outcome.tweet_id, cost_usd=None)  # cost already set by Phase 6
        # Also explicitly clear error_detail on success (D-10)
        session.execute(update(Post).where(Post.id == post.id).values(error_detail=None))
        session.flush()
        log.info("publish_done", tweet_id=outcome.tweet_id, elapsed_ms=elapsed_ms)
        return PublishResult(
            post_id=post.id, status="posted", tweet_id=outcome.tweet_id, attempts=1,
            elapsed_ms=elapsed_ms, error_detail=None,
            counts_patch={"publish_status": "posted", "tweet_id": outcome.tweet_id,
                          "stale_pending_cleaned": cleaned},
        )

    if outcome.status == "rate_limited":
        update_failed(session, post.id, error_detail=json.dumps(outcome.error_detail))
        log.warning("rate_limit_hit", **outcome.error_detail)
        return PublishResult(
            post_id=post.id, status="failed", tweet_id=None, attempts=1,
            elapsed_ms=elapsed_ms, error_detail=outcome.error_detail,
            counts_patch={"publish_status": "failed", "rate_limited": True,
                          "stale_pending_cleaned": cleaned},
        )

    # publish_error
    update_failed(session, post.id, error_detail=json.dumps(outcome.error_detail))
    log.error("publish_error", **outcome.error_detail)
    return PublishResult(
        post_id=post.id, status="failed", tweet_id=None, attempts=1,
        elapsed_ms=elapsed_ms, error_detail=outcome.error_detail,
        counts_patch={"publish_status": "failed", "stale_pending_cleaned": cleaned},
    )
```

### Scheduler Wiring (D-12)

```python
# src/tech_news_synth/scheduler.py — revised run_cycle (Phase 6 → Phase 7)
ingest_counts = run_ingest(session, sources_config, http_client, settings)
selection = run_clustering(session, cycle_id, settings, sources_config)

cap_check = check_caps(session, settings)
synth_patch: dict = {}
publish_patch: dict = {}

if cap_check.skip_synthesis:
    log.warning("caps_reached_skipping",
                daily_reached=cap_check.daily_reached,
                monthly_reached=cap_check.monthly_cost_reached,
                daily_count=cap_check.daily_count,
                monthly_cost_usd=cap_check.monthly_cost_usd)
    publish_patch = {
        "daily_cap_skipped": cap_check.daily_reached,
        "monthly_cost_capped": cap_check.monthly_cost_reached,
        "daily_posts_count": cap_check.daily_count,
        "monthly_cost_usd": cap_check.monthly_cost_usd,
    }
elif (selection.winner_cluster_id is not None
      or selection.fallback_article_id is not None):
    # Synth (Phase 6)
    if hashtag_allowlist is None:
        hashtag_allowlist = load_hashtag_allowlist(Path(settings.hashtags_config_path))
    anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
    synthesis = run_synthesis(session, cycle_id, selection, settings,
                              sources_config, anthropic_client, hashtag_allowlist)
    synth_patch = synthesis.counts_patch

    # Publish (Phase 7)
    x_client = build_x_client(settings)
    publish = run_publish(session, cycle_id, synthesis, settings, x_client)
    publish_patch = publish.counts_patch

counts = {**ingest_counts, **selection.counts_patch, **synth_patch, **publish_patch}
```

### Anti-Patterns to Avoid

- **Pre-publish "does tweet exist on timeline?" check** — wastes an API call per cycle, still has a race. Stale-pending guard is the documented pattern.
- **Using `wait_on_rate_limit=True`** — blocks the scheduler thread for up to 15 min; violates INFRA-05 cadence assumptions.
- **Parsing `tweet_id` to `int`** — X tweet IDs are 64-bit unsigned (up to 19 digits). `posts.tweet_id` is TEXT; keep it TEXT through the whole pipeline `[VERIFIED: db/models.py:142 — `tweet_id: Mapped[str | None]`]`.
- **Logging the full tweepy exception repr** — can include auth headers in some edge cases. Use `type(e).__name__` + `str(e)[:500]`.
- **Calling `create_tweet` without a timeout** — tweepy's `requests.Session` default is infinite. A hung X endpoint would hang the scheduler thread forever. Monkey-wrap `session.request` with `timeout=settings.x_api_timeout_sec`.
- **Mixing `respx` with tweepy in tests** — `respx` only intercepts `httpx`. tweepy uses `requests`. Use `responses` or `requests-mock`.
- **Relying on `x-user-limit-24hour-*` headers** — `[VERIFIED: Phase 3 intel `.planning/intel/x-api-baseline.md`]` — these are ABSENT on pay-per-use tier. Local `posts.posted_at` counter is the authoritative daily cap.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| OAuth 1.0a signature | Custom HMAC-SHA1 signer | `tweepy.Client` 4-secret constructor | tweepy uses `requests-oauthlib`'s `OAuth1UserHandler` internally (verified from source). Battle-tested. |
| X v2 endpoint routing | Raw `requests.post("https://api.twitter.com/2/tweets", ...)` | `tweepy.Client.create_tweet(text=...)` | Handles endpoint paths, parameter marshaling, error-code mapping consistently. |
| HTTP-status-code → exception-type mapping | `if r.status_code == 429: ...` raw checks | `except tweepy.TooManyRequests / HTTPException` | tweepy's hierarchy (verified from source) already encodes every X error code. |
| Rate-limit header extraction | Parse headers from `r.raw.headers` | `r.headers.get("x-rate-limit-reset")` on the raw `requests.Response` | `return_type=requests.Response` exposes `.headers` directly. |
| Idempotency via embedded marker | Append `[cycle-abc123]` to tweet body | `posts.status=pending` row BEFORE call + stale-pending guard | UX-ugly, doesn't survive X's trimming, and operator can't correlate. DB-first pattern is standard. |
| Daily counter from X API | `client.get_users_tweets(user_id, max_results=100)` and filter by date | `SELECT COUNT(*) FROM posts WHERE status='posted' AND posted_at >= date_trunc('day', ...)` | Pay-per-use tier exposes no `x-user-limit-24hour-*` headers; auth to fetch timeline costs money; local counter is authoritative. |
| Timeout enforcement | Manual `threading.Timer` watchdog | `functools.partial(client.session.request, timeout=N)` | `requests.Session` natively honors `timeout=` — just needs to be plumbed since tweepy has no ctor arg. |

**Key insight:** Every single Phase 7 problem has a well-established idiom in tweepy/requests or an already-written helper in the project. The custom code surface is purely **flow control** (which `error_detail` dict to write, when to skip) — not protocol implementation.

## Common Pitfalls

### Pitfall 1: Forgetting `return_type=requests.Response`
**What goes wrong:** `create_tweet` returns `tweepy.Response` namedtuple `(data, includes, errors, meta)` with NO `.headers` attribute.
**Why it happens:** Default value is `return_type=Response` (tweepy's own class). Easy to miss.
**How to avoid:** Add a unit test that asserts `build_x_client(settings).return_type is requests.Response`. Mirror Phase 3's `smoke_x_post.py:95` comment.
**Warning signs:** `AttributeError: 'Response' object has no attribute 'headers'` at 429-handling code.

### Pitfall 2: 429 Exception with `return_type=requests.Response` Still Raises
**What goes wrong:** Engineer assumes "non-raising mode" because of `return_type`. Writes `if r.status_code == 429:` after the call. Never fires.
**Why it happens:** `BaseClient.request` (verified from source) checks status codes BEFORE honoring `return_type`: `if response.status_code == 429: ... raise TooManyRequests(response)`. The `return_type` branch only applies to successful 2xx responses.
**How to avoid:** Always wrap `create_tweet` in `try/except tweepy.TooManyRequests / HTTPException`. Access headers via `e.response.headers`.
**Warning signs:** Unit tests with a 429 mock produce unhandled exceptions in `run_publish`.

### Pitfall 3: DATE_TRUNC and Session Timezone
**What goes wrong:** Server time-zone changes (ops tweaks postgres.conf) → `date_trunc('day', now())` silently returns local-midnight instead of UTC-midnight → daily cap window drifts.
**Why it happens:** 2-arg `date_trunc` uses the session's `TimeZone` setting.
**How to avoid:** Use 3-arg form `date_trunc('day', now(), 'UTC')`. Verified supported in Postgres 16+.
**Warning signs:** Daily cap resets at e.g. 21:00 UTC instead of 00:00 UTC; posts from "yesterday" still counted today.

### Pitfall 4: `cost_usd` NULL on Failed Rows Breaks Monthly-Cost SUM
**What goes wrong:** If a row's `cost_usd` is NULL (e.g., Phase 6 synthesis crashed before writing it), `SUM(cost_usd)` over that row contributes NULL. `COALESCE(SUM(...), 0)` handles the ALL-NULL case but NOT mixed NULLs — SUM treats NULLs as skipped so this is fine. Pitfall is thinking it's broken and adding an unneeded `WHERE cost_usd IS NOT NULL`.
**Why it happens:** Confusion between SQL's NULL-in-aggregate semantics.
**How to avoid:** Trust `COALESCE(SUM(cost_usd), 0)` — it's correct. Write an integration test with mixed NULL and numeric rows.
**Warning signs:** None — the standard idiom is safe.

### Pitfall 5: Stale-Pending Guard Marks THIS Cycle's Row
**What goes wrong:** Cycle starts at T. Phase 6 inserts pending at T+0.5s. `run_publish` stale-guard runs at T+0.6s with cutoff `T - 5min`. Row's `created_at` (set by `server_default=func.now()`) is T+0.5s → NOT stale. Fine. But if cycle is slow and Phase 6 took 6 min, the guard WOULD mark it. Race is theoretical but real.
**Why it happens:** Ingest + cluster + synth could plausibly exceed 5 min if feeds are slow + anthropic retries.
**How to avoid:** (a) Default 5 min is generous vs typical ~30s cycle time. (b) Re-read `post.status` after guard. (c) If marked, skip publish and return `status='failed'`. (d) Operator can tighten the minutes value or investigate via runbook if it ever fires.
**Warning signs:** `publish_aborted_not_pending` log lines with `cycle_id` matching current cycle.

### Pitfall 6: Duplicate-Tweet (422)
**What goes wrong:** X rejects exact-duplicate text within some window. Happens if a previous "orphaned pending" actually posted but we retried.
**Why it happens:** Stale-pending guard marks a row failed that actually DID post. Next cycle re-synthesizes (different text likely) — but if by coincidence text matches, 422.
**How to avoid:** Log the specific tweepy error code (422 is surfaced by `api_codes`); operator runbook includes a "check https://x.com/ByteRelevant" step. Error-detail captures `api_codes` array so operator can grep.
**Warning signs:** `error_detail.api_codes` includes known-duplicate codes, or `message` contains "duplicate".

### Pitfall 7: Tweepy `Client.session = requests.Session()` Is Per-Instance But Leaks If Not Closed
**What goes wrong:** Per-cycle client construction creates a new `requests.Session()` each time. Small connection-pool leak possible if cycles are frequent + Python GC is lazy.
**Why it happens:** D-13 says no explicit close needed. That's fine for 2h cadence (12 cycles/day); not fine for high-frequency.
**How to avoid:** Accept for v1 — 12 sessions/day is trivial. If Phase 8 soak shows FD accumulation, add `try/finally: x_client.session.close()` in `run_publish`. Not a v1 concern.

### Pitfall 8: Bearer-Token Misconfiguration Passes Silently
**What goes wrong:** Operator populates only `X_BEARER_TOKEN` in `.env`. Settings validates (all 4 OAuth secrets are required SecretStr with no default, so pydantic raises at boot). Actually SAFE — `[VERIFIED: config.py:72-75]` — all 4 are `SecretStr` with no default, so missing any of them fails boot via pydantic ValidationError. No special "reject bearer" validator needed.
**How to avoid:** Confirm in a unit test that a Settings instantiation with only 3 of 4 X secrets raises ValidationError.

## Code Examples

### Successful Post — Phase 3 Proven Pattern

```python
# Source: scripts/smoke_x_post.py (verified live against @ByteRelevant on 2026-04-13)
client = tweepy.Client(
    consumer_key=settings.x_consumer_key.get_secret_value(),
    consumer_secret=settings.x_consumer_secret.get_secret_value(),
    access_token=settings.x_access_token.get_secret_value(),
    access_token_secret=settings.x_access_token_secret.get_secret_value(),
    return_type=requests.Response,
)
r = client.create_tweet(text="Hello world")
# r is a requests.Response (2xx only — non-2xx raises)
tweet_id = r.json()["data"]["id"]             # "2043757607970619474"
rate_limit_reset = r.headers.get("x-rate-limit-reset")  # unix epoch string
# On pay-per-use, x-user-limit-24hour-* are ABSENT (key finding from Phase 3)
```

### 429 Handling — Structured Fallthrough

```python
# Source: synthesized from tweepy.errors source + D-07 contract
try:
    r = client.create_tweet(text=text)
except tweepy.TooManyRequests as e:
    # e.response is the raw requests.Response
    reset = int(e.response.headers.get("x-rate-limit-reset", "0"))
    retry_after = max(0, reset - int(time.time()))
    log.warning("rate_limit_hit",
                reset_at=datetime.fromtimestamp(reset, tz=timezone.utc).isoformat(),
                retry_after_seconds=retry_after,
                remaining=e.response.headers.get("x-rate-limit-remaining"))
    # D-07: mark failed, return, scheduler ticks on
```

### Integration Test — Mocking tweepy with `responses`

```python
# tests/integration/test_publish_rate_limited.py
# Source: responses library idiom (Getsentry-maintained)
import responses, time

@responses.activate
def test_publish_429_marks_failed_and_captures_headers(session, settings, cycle_id):
    reset_epoch = int(time.time()) + 600
    responses.add(
        responses.POST,
        "https://api.twitter.com/2/tweets",
        status=429,
        json={"title": "Too Many Requests"},
        headers={
            "x-rate-limit-limit": "100",
            "x-rate-limit-remaining": "0",
            "x-rate-limit-reset": str(reset_epoch),
        },
    )
    # Arrange: insert a pending post
    post = insert_post(session, cycle_id=cycle_id, cluster_id=None,
                       status="pending", theme_centroid=None,
                       synthesized_text="text", hashtags=["#tech"],
                       cost_usd=0.0001, error_detail=None)
    session.commit()
    # Act
    client = build_x_client(settings)
    synthesis_result = SynthesisResult(post_id=post.id, ...)
    result = run_publish(session, cycle_id, synthesis_result, settings, client)
    session.commit()
    # Assert
    assert result.status == "failed"
    assert result.counts_patch["rate_limited"] is True
    session.refresh(post)
    assert post.status == "failed"
    detail = json.loads(post.error_detail)
    assert detail["reason"] == "rate_limited"
    assert detail["x_rate_limit_reset"] == reset_epoch
```

### Daily-Cap Query (SA 2.0 Core)

```python
from sqlalchemy import func, select
from tech_news_synth.db.models import Post

daily_count = session.execute(
    select(func.count())
    .select_from(Post)
    .where(Post.status == "posted")
    .where(Post.posted_at >= func.date_trunc("day", func.now(), "UTC"))
).scalar_one()
```

### Monthly-Cost Query

```python
monthly_cost = session.execute(
    select(func.coalesce(func.sum(Post.cost_usd), 0))
    .where(Post.status.in_(("posted", "failed")))
    .where(Post.created_at >= func.date_trunc("month", func.now(), "UTC"))
).scalar_one()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `client.create_tweet` → tweepy.Response namedtuple | `create_tweet` with `return_type=requests.Response` | tweepy 4.x (since Response was renamed) | Required for header access — no other way on tweepy 4.14+ |
| X Free tier (50 posts/24h) | Pay-per-use (~$0.03/post, no explicit daily cap header) | 2026-02-06 (Free tier deprecated for new accounts) | `x-user-limit-24hour-*` headers ABSENT; local counter authoritative |
| `psycopg2-binary` | `psycopg[binary,pool]` (v3) | Phase 2 already migrated | `postgresql+psycopg://` dialect in SA URL |
| `tweepy.API` (v1.1) | `tweepy.Client` (v2) | `create_tweet` endpoint is v2-only on paid tiers | No v1.1 fallback path needed |
| `sentence-transformers` embeddings for dedup | Cosine similarity on TF-IDF centroids (already Phase 5) | N/A — Phase 5 deferred ST to v2 | Not a Phase 7 concern but consistent pattern |

**Deprecated/outdated:**
- `wait_on_rate_limit=True` auto-sleep — `[CITED: tweepy BaseClient.request source]` blocks thread for up to 15 min; unsuitable for in-scheduler use.
- Free tier assumptions (50/day, specific rate-limit shape) — all `[VERIFIED: Phase 3 intel]` as no longer applicable.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `responses` lib is preferred over `requests-mock` for dev deps | Standard Stack / Supporting | Low — either library works for tweepy tests. Pick one and standardize. |
| A2 | Duplicate-tweet 422 is the error code X uses for exact-text re-posts | Pitfall 6 | Low — the exact code varies; the handling (log `api_codes`, operator runbook) is code-agnostic. Planner should add "duplicate detection" as a handled variant of `publish_error` without special-casing. |
| A3 | FD leak from per-cycle `requests.Session()` is negligible at 12 cycles/day | Pitfall 7 | Low — 2h cadence means sessions get GC'd before any accumulation. If Phase 8 soak shows otherwise, add `x_client.session.close()` in a `finally`. |

All other claims tagged `[VERIFIED]` (installed venv introspection, Phase 3 live measurement, db/models.py source, config.py source) or `[CITED]` (Postgres docs).

## Open Questions

1. **Should `update_posted` be modified to also clear `error_detail`?**
   - What we know: Existing helper (`db/posts.py:58-74`) does NOT clear `error_detail` on success. Phase 7 orchestrator does it via an explicit `update().values(error_detail=None)`.
   - What's unclear: Should the repo helper be tightened so all callers get the D-10 guarantee automatically?
   - Recommendation: Tighten `update_posted(session, post_id, tweet_id, cost_usd=None)` to always `error_detail = None` on the UPDATE. Current callers (if any beyond Phase 6/7) would be unaffected. Planner should add a task to verify no other caller depends on the old behavior.

2. **Does Phase 6 already set `cost_usd` on the `pending` row?**
   - What we know: Phase 6 `insert_post` writes `cost_usd=Decimal(str(cost_usd))` at insert time. So the `pending` row ALREADY has the cost.
   - What's unclear: Should `update_posted` re-accept `cost_usd` or pass `None` / omit?
   - Recommendation: Phase 7 passes `cost_usd=None` to `update_posted` (idempotent — won't overwrite the already-set value). Verify existing helper behavior: if `cost_usd=None` currently WRITES NULL, that's a bug to fix in the planner's scope. Looking at `db/posts.py:69` — `post.cost_usd = Decimal(str(cost_usd)) if cost_usd is not None else None` — this WILL overwrite to NULL. **Planner must fix:** change to `if cost_usd is not None: post.cost_usd = Decimal(str(cost_usd))` (skip on None rather than set to None). This is a latent Phase 2 bug exposed by Phase 7.

3. **Should cap-check skip ALSO log a `run_log.status` distinct from `ok`?**
   - What we know: D-04/D-06 say cycle exits `run_log.status='ok'` (D-04 wording) or `'cost_capped'` (D-06 wording) — inconsistent.
   - What's unclear: Which is it?
   - Recommendation: Planner resolves by using `run_log.status='ok'` with `counts.daily_cap_skipped`/`counts.monthly_cost_capped` flags — keeps `run_log.status` vocabulary small (`ok|error`) matching INFRA-08. The flag in `counts` gives operators the same observability without expanding the enum.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `tweepy` | `create_tweet` | ✓ | 4.16.0 (satisfies `>=4.14,<5`) | — |
| `requests` | `return_type=requests.Response` class ref | ✓ | transitive via tweepy | — |
| `psycopg` / postgres 16 | cap-count queries, `date_trunc` 3-arg form | ✓ (compose `postgres:16-bookworm`) | 16.x | — |
| `responses` **OR** `requests-mock` | Integration-test HTTP mocking | ✗ | — | Monkeypatch `tweepy.Client.create_tweet` directly (lower realism) |
| `respx` | N/A (httpx-only; NOT usable for tweepy) | ✓ (0.23.1) | — | — |
| X API credentials for @ByteRelevant | Live compose smoke | ✓ (`[VERIFIED: Phase 3 intel — OAuth 1.0a Read+Write confirmed]`) | — | — |

**Missing dependencies with no fallback:** None — can ship Phase 7 without `responses` by monkeypatching at the tweepy level, but integration-test realism suffers.

**Missing dependencies with fallback:** `responses` — recommend adding as dev dep (Plan Wave 0 task). Fallback = `pytest_mock.patch` on `client.create_tweet` return value / side_effect.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-mock + time-machine (already pinned in `[dependency-groups].dev`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths=["tests"]`, `pythonpath=["src"]`, marker `integration: requires live postgres` |
| Quick run command | `uv run pytest tests/unit -q` |
| Full suite command | `TEST_DATABASE_URL=postgresql+psycopg://app:replace-me@172.19.0.2:5432/tech_news_synth_test uv run pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PUBLISH-01 | `build_x_client` uses 4 OAuth secrets; `return_type is requests.Response` | unit | `uv run pytest tests/unit/test_publish_client.py::test_build_x_client_uses_oauth1_with_requests_return_type -x` | ❌ Wave 0 |
| PUBLISH-01 | Missing X secret raises `ValidationError` at boot | unit | `uv run pytest tests/unit/test_config.py::test_missing_x_secret_fails_fast -x` | ❌ Wave 0 |
| PUBLISH-02 | `pending` row → `posted` with tweet_id + posted_at on success | integration | `uv run pytest tests/integration/test_publish_success.py -x` | ❌ Wave 0 |
| PUBLISH-02 | Mid-call crash simulation: next cycle stale-guard marks orphan `failed`, does NOT re-call `create_tweet` | integration | `uv run pytest tests/integration/test_publish_stale_guard.py -x` | ❌ Wave 0 |
| PUBLISH-03 | 429 response → `status='failed'`, `error_detail` captures `x-rate-limit-reset` + `remaining` + `limit` | integration | `uv run pytest tests/integration/test_publish_rate_limited.py -x` | ❌ Wave 0 |
| PUBLISH-03 | Scheduler continues after 429 (no crash; next tick fires) | unit | `uv run pytest tests/unit/test_scheduler.py::test_publish_429_does_not_crash_scheduler -x` | ❌ Wave 0 |
| PUBLISH-04 | 12 posts with today's `posted_at` → `check_caps.skip_synthesis is True`; synth not called | integration | `uv run pytest tests/integration/test_publish_daily_cap.py -x` | ❌ Wave 0 |
| PUBLISH-05 | Posts summing > $30 this UTC month → `check_caps.monthly_cost_reached is True`; synth not called | integration | `uv run pytest tests/integration/test_publish_cost_cap.py -x` | ❌ Wave 0 |
| PUBLISH-05 | `dry_run` rows EXCLUDED from sum; `failed` rows INCLUDED | integration | `uv run pytest tests/integration/test_publish_cost_cap.py::test_cost_cap_inclusion_rules -x` | ❌ Wave 0 |
| PUBLISH-06 | `posts.status='dry_run'` → no X API call; row unchanged | integration | `uv run pytest tests/integration/test_publish_dry_run.py -x` | ❌ Wave 0 |
| PUBLISH-06 | Under DRY_RUN, cap checks STILL fire (operator signal) | integration | `uv run pytest tests/integration/test_publish_dry_run.py::test_caps_still_fire_under_dry_run -x` | ❌ Wave 0 |
| Cross-cutting | DATE_TRUNC UTC behavior correct on timestamptz columns | integration | `uv run pytest tests/integration/test_publish_caps_tz.py -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/unit -q` (~1.5s baseline; Phase 7 adds ~0.3s)
- **Per wave merge:** `TEST_DATABASE_URL=... uv run pytest tests/ -q` (full unit + integration)
- **Phase gate:** Full suite green + compose smoke checkpoint (Plan 07-02 task 3) before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] Add `responses>=0.25,<1` (or `requests-mock>=1.12,<2`) to `[dependency-groups].dev` in `pyproject.toml` — required for all integration tests listed above.
- [ ] `tests/unit/test_publish_client.py` — covers PUBLISH-01 client construction (5 red-stub tests).
- [ ] `tests/unit/test_publish_caps.py` — covers cap-check pure logic with mocked session (6 red-stub tests).
- [ ] `tests/unit/test_publish_orchestrator.py` — covers `run_publish` flow-control branches (posted/429/error/dry_run/stale) with mocked `post_tweet` (8 red-stub tests).
- [ ] `tests/unit/test_publish_idempotency.py` — covers `clean_stale_pending` SQL helper with mocked session (4 red-stub tests).
- [ ] `tests/integration/test_publish_success.py` — end-to-end happy path w/ `responses`-mocked 201 response (PUBLISH-02).
- [ ] `tests/integration/test_publish_rate_limited.py` — 429 + headers (PUBLISH-03).
- [ ] `tests/integration/test_publish_daily_cap.py` — cap at 12 (PUBLISH-04).
- [ ] `tests/integration/test_publish_cost_cap.py` — cap at $30 (PUBLISH-05) + inclusion rules.
- [ ] `tests/integration/test_publish_dry_run.py` — DRY_RUN skip (PUBLISH-06).
- [ ] `tests/integration/test_publish_stale_guard.py` — D-02 orphan cleanup + no-duplicate-call.
- [ ] `tests/integration/test_publish_caps_tz.py` — DATE_TRUNC UTC correctness with time-machine frozen at UTC-midnight-edge.
- [ ] Update `tests/unit/test_scheduler.py` — add Phase 7 wiring tests (`run_publish` called / skipped / cap-skip path / 429-continue).

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | OAuth 1.0a User Context via `tweepy` (`requests-oauthlib` under the hood); 4 secrets as `SecretStr`; never logged; `.get_secret_value()` inline at constructor call site only |
| V3 Session Management | no | Stateless API call per cycle |
| V4 Access Control | no | Single-tenant, single-account; no multi-user authorization |
| V5 Input Validation | yes | `synthesized_text` already validated by Phase 6 (`weighted_len ≤ 280`); pydantic frozen models at Phase 7 boundary |
| V6 Cryptography | yes | TLS via `requests`→`urllib3`; no custom crypto; never hand-roll HMAC/OAuth signing |
| V7 Error Handling | yes | `error_detail` captures structured JSON; tweepy exception repr sanitized via `str(e)[:500]` + `type(e).__name__` only; secrets never appear in stacktraces |
| V8 Data Protection | yes | `.env` gitignored; `.env.example` versioned; SecretStr at rest in Settings |
| V14 Configuration | yes | Settings validator enforces all 4 X secrets present (pydantic ValidationError at boot) |

### Known Threat Patterns for tweepy + X v2 + Postgres

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Duplicate-post after lost DB UPDATE | Integrity | D-02 stale-pending guard + operator runbook; accepted residual risk (T-07-01) |
| Cost-cap bypass via direct DB writes | Tampering | Cap query is server-side SQL; operator must not tamper; v1 accepts this (T-07-02) |
| OAuth secret leak in `error_detail` or log lines | Info Disclosure | `SecretStr.get_secret_value()` inline at constructor only; exception handling uses `type(e).__name__` + `str(e)[:500]`; structlog JSON renderer escapes; verified pattern from Phase 3 (T-07-03) |
| 422 duplicate-tweet after operator manual retry | Integrity | Stale-guard + operator runbook; `error_detail.api_codes` surfaces 422 for observability (T-07-04) |
| Bearer-token misconfig at boot | Availability | pydantic `SecretStr` on all 4 X OAuth fields with NO defaults → missing secret = `ValidationError` at boot (T-07-05) |
| Monthly-cost clock skew at month boundary | Integrity | `date_trunc('month', now(), 'UTC')` is atomic per row-insert; worst-case one cycle's cost lands in wrong bucket (~$0.03 skew); accepted (T-07-06) |
| Untrusted-input in tweet body | Tampering / Reputation | Phase 6 already produces `synthesized_text` from LLM + allowlist hashtags; Phase 7 treats it as opaque string; no injection surface at Phase 7 boundary |
| Infinite hang on X endpoint timeout | Availability | `functools.partial(client.session.request, timeout=settings.x_api_timeout_sec)` (default 30s); fails into `publish_error` path |

## Project Constraints (from CLAUDE.md)

- **Python:** 3.12 (pinned `>=3.12,<3.13` in pyproject)
- **API X tier:** pay-per-use; posting costs real money (~$0.03/post observed)
- **Post char limit:** 280 total (weighted count) incl. `~23` t.co URL + hashtags — Phase 6 already enforced; Phase 7 treats `synthesized_text` as already-validated
- **Janela anti-repetição 48h** — Phase 5's concern, not Phase 7
- **Idioma:** PT-BR — no Phase 7 concern (text already synthesized)
- **Timezone:** UTC everywhere (`TIMESTAMPTZ` in Postgres, `datetime.now(timezone.utc)` in Python) — critical for DATE_TRUNC queries
- **Secrets:** `.env` local, `.env.example` versioned, `.env` in `.gitignore`; pre-commit hook already set up
- **GSD workflow:** any Edit/Write must go through a GSD command (enforced in CLAUDE.md)
- **Forbidden stacks:** no system cron (use APScheduler — already in place), no Alpine base (slim-bookworm — already in place), no bearer-only X auth, no `tweepy.API` v1.1, no mixing `requests`+`aiohttp`
- **Project conventions:** structlog JSON w/ contextvars + `phase=<X>` binding; pure-function modules + one orchestrator; pydantic-v2 frozen boundary models; per-cycle SDK clients; Settings extends with phase-specific fields + validators

## Sources

### Primary (HIGH confidence)

- **Installed tweepy venv introspection** (4.16.0) — `Client.__init__` signature, `BaseClient.request` status-code→exception mapping, `HTTPException.response`/`api_codes` attributes verified directly from source
- `scripts/smoke_x_post.py` — Phase 3 proven post+delete flow with `return_type=requests.Response`; confirmed working against @ByteRelevant 2026-04-13
- `.planning/intel/x-api-baseline.md` — `x-user-limit-24hour-*` headers ABSENT on pay-per-use tier (authoritative for PUBLISH-04 design)
- `src/tech_news_synth/db/posts.py` — existing `update_posted` / `update_failed` / `insert_pending` / `insert_post` helpers (reused)
- `src/tech_news_synth/db/models.py` — `posts.tweet_id: Mapped[str | None] = mapped_column(Text)`, `status CHECK IN ('pending','posted','failed','dry_run')`
- `src/tech_news_synth/config.py` — `x_consumer_key/secret/access_token/access_token_secret: SecretStr` (no default → fail-fast)
- `src/tech_news_synth/scheduler.py` — `run_cycle` structure with session + structlog contextvars + INFRA-08 wrapper

### Secondary (MEDIUM confidence)

- [tweepy Client 4.14 docs](https://docs.tweepy.org/en/stable/client.html) — confirmed signature (WebFetch 403'd; introspection substituted)
- [tweepy Exceptions 4.14 docs](https://docs.tweepy.org/en/stable/exceptions.html) — exception hierarchy (introspection substituted)
- [PostgreSQL DATE_TRUNC docs](https://www.postgresql.org/docs/current/functions-datetime.html) — 3-arg form with explicit timezone confirmed supported

### Tertiary (LOW confidence / flagged)

- `responses` vs `requests-mock` preference — both work; pick one. No hard data on which is more ergonomic for this codebase. Flagged as A1 in Assumptions Log.

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — tweepy signature verified via `inspect.signature` on installed venv; version satisfies pin
- tweepy exception semantics: **HIGH** — `BaseClient.request` source inspected; status-code→exception mapping is explicit
- `return_type=requests.Response` behavior: **HIGH** — `_make_request` source shows `if self.return_type is requests.Response: return response` (2xx only); non-2xx ALWAYS raises regardless of return_type
- SQL patterns (`date_trunc`, `COUNT`, `SUM+COALESCE`): **HIGH** — standard SA 2.0 Core + Postgres 16 idioms
- Existing DB helpers coverage: **HIGH** — `db/posts.py` read end-to-end; only 3 new helpers needed
- Stale-pending guard correctness: **MEDIUM** — logic is straightforward; race window is acknowledged in CONTEXT D-02 with operator runbook
- Test mocking lib choice: **MEDIUM** — `responses` vs `requests-mock` is stylistic; `respx` confirmed unusable (httpx-only)
- Threat model completeness: **MEDIUM** — T-07-01 through T-07-06 cover the major vectors; additional Phase 8 hardening may add more

**Research date:** 2026-04-12
**Valid until:** 2026-05-12 (tweepy 4.x is stable; X API v2 is stable; Postgres 16 is LTS)
