# Phase 7: Publish - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Take the `posts` row Phase 6 wrote (`status='pending'` or `'dry_run'`), call `tweepy.Client.create_tweet` via OAuth 1.0a User Context, transition `status → posted|failed` with `tweet_id` + `posted_at` + structured `error_detail`, enforce `MAX_POSTS_PER_DAY` daily cap and `MAX_MONTHLY_COST_USD` monthly cost kill-switch, handle X 429 responses via `x-rate-limit-reset` header, and short-circuit cleanly under `DRY_RUN=1`. Out of scope: retry/backoff logic for transient errors (accepted — next cycle is the retry), alerts (Phase 8 OPS), daily cap header enforcement (X pay-per-use tier does not expose `x-user-limit-24hour-*` per Phase 3 baseline — local counter is authoritative).

</domain>

<decisions>
## Implementation Decisions

### OAuth + SDK Contract
- **D-01:** **`tweepy.Client.create_tweet` with OAuth 1.0a User Context (4 secrets).** Build `tweepy.Client(consumer_key=..., consumer_secret=..., access_token=..., access_token_secret=..., return_type=requests.Response)` per Phase 3 research finding — `return_type=requests.Response` is REQUIRED for rate-limit header access (PUBLISH-03). Bearer token path explicitly rejected at boot: Settings validator raises if `ANTHROPIC_API_KEY` is present but X consumer/access tokens are missing (fail-fast).

### Idempotency (PUBLISH-02)
- **D-02:** **Stale-pending guard at cycle start.** Before Phase 7 runs, the publisher queries `SELECT id, created_at FROM posts WHERE status='pending' AND created_at < NOW() - INTERVAL '5 minutes'`. Any matching rows are:
  - Logged as `orphaned_pending` WARN events
  - UPDATE'd to `status='failed'`, `error_detail = '{"reason": "orphaned_pending_row", "detected_at": <iso>}'`
  - NOT re-published
  Rationale: X v2 has NO idempotency-key header (unlike Stripe); a mid-call crash window is small (~1-2s between `create_tweet` response and DB UPDATE) but non-zero. The 5-min stale-guard is generous enough to protect against clock skew + container restart timing, and any real "the tweet was actually posted but DB didn't update" case is surfaced to the operator via the `failed` row + error_detail. Operator-investigation workflow (check account timeline manually) is documented in `docs/runbook-orphaned-pending.md`.
- **D-03:** **Current-cycle idempotency within-cycle:** Phase 6 inserts row with `status='pending'` BEFORE Phase 7 call. Phase 7 reads the same row by `post_id` (not by cycle_id — a cycle could theoretically have multiple posts in future) and performs one `create_tweet` call. On success, UPDATE same row to `posted`. On failure, UPDATE to `failed`. No queue-of-pending-rows pattern — single-row-per-cycle invariant enforced by Phase 5's winner-or-fallback model.

### Cap Checks
- **D-04:** **Daily cap check fires BEFORE Phase 6 synthesis** (top of cycle, after `run_ingest` + `run_clustering` select the winner). If daily cap reached, skip BOTH synthesis AND publish; log `daily_cap_reached posted_today=<N>`; cycle exits clean with `run_log.status='ok'` + `counts.daily_cap_skipped=true`. Rationale: synthesis costs real money ($0.000038 per smoke); no reason to synthesize if we can't publish. SC-4 says "cluster + synthesis still run and log" — this is INTERPRETED as "cluster stage already ran; we don't need to force synthesis when capped" (the cluster audit trail satisfies the observability intent).
- **D-05:** **Daily cap query:** `SELECT COUNT(*) FROM posts WHERE status='posted' AND posted_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC')`. Compared against `settings.max_posts_per_day` (default 12). Excludes `pending`, `failed`, `dry_run` — only successful posts count.
- **D-06:** **Monthly cost cap check also fires BEFORE synthesis** (same reasoning). Query: `SELECT COALESCE(SUM(cost_usd), 0) FROM posts WHERE status IN ('posted', 'failed') AND created_at >= DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC')`. EXCLUDES `dry_run` rows (testing-mode doesn't eat real cap) but INCLUDES `failed` rows (failed posts still incurred Haiku synthesis cost). Default `MAX_MONTHLY_COST_USD=30.00` (Phase 3 intel projected ~$11/mo; 30 is ~2.7× headroom; operator tunes via env). On breach: log `monthly_cost_cap_breached spent=<N>`, cycle exits `run_log.status='cost_capped'`, NO synthesis, NO publish, scheduler keeps ticking. Operator manually investigates + raises cap or pauses via `PAUSED=1`.

### 429 Rate-Limit Handling (PUBLISH-03)
- **D-07:** **On 429 response:** read `x-rate-limit-reset` + `x-rate-limit-remaining` + `x-rate-limit-limit` headers. UPDATE the current `posts` row to `status='failed'` with `error_detail = {"reason": "rate_limited", "status_code": 429, "x_rate_limit_reset": <epoch>, "x_rate_limit_remaining": 0, "x_rate_limit_limit": <n>, "retry_after_seconds": <reset - now>}`. Log structured WARN `rate_limit_hit reset_at=<iso>`. **Return from run_cycle cleanly** — scheduler keeps ticking. No sleep, no retry inside the cycle. Next cycle (2h later) attempts fresh synthesis + publish. Most X 429s reset within 15 min; by 2h cadence we'll be under limit again.
- **D-08:** **Generic failure (non-429) handling:** For `tweepy.TweepyException`, HTTP 4xx/5xx (except 429), or any exception during publish — UPDATE posts row to `status='failed'` with `error_detail = {"reason": "publish_error", "status_code": <int or null>, "tweepy_error_type": <class name>, "message": <str>, "x_rate_limit_*": <if present>}`. Log ERROR. Propagate exception to scheduler's existing INFRA-08 handler — cycle marks `status='failed'`, scheduler ticks on.

### DRY_RUN Behavior (PUBLISH-06)
- **D-09:** **Phase 7 checks `posts.status`.** If the row Phase 6 created has `status='dry_run'` (set by Phase 6 D-12 when `settings.dry_run=True`), Phase 7 returns immediately without any X API call — the row stays `dry_run`, `synthesized_text` is already populated, `tweet_id` + `posted_at` remain NULL. Log `publish_skipped_dry_run post_id=<id>`. Cap checks STILL fire (operator sees "you would be over cap" signal in dry-run mode — useful for capacity planning).

### Posts Row Transitions
- **D-10:** **State machine:** `pending → posted` (success) | `pending → failed` (error) | `dry_run` (terminal, set by Phase 6, never transitions). On success UPDATE: `status='posted', tweet_id=<str>, posted_at=<utc now>, error_detail=NULL`. On failure UPDATE: `status='failed', posted_at=NULL, error_detail=<json str>`. `tweet_id` type is `TEXT` in Phase 2 schema (X tweet IDs are large integers represented as strings to avoid JS precision loss).

### Settings Additions
- **D-11:** **4 new Settings fields:**
  - `max_posts_per_day: int = Field(default=12, ge=1, le=1000)` — PUBLISH-04
  - `max_monthly_cost_usd: float = Field(default=30.00, ge=1.0, le=10000.0)` — PUBLISH-05
  - `publish_stale_pending_minutes: int = Field(default=5, ge=1, le=1440)` — D-02 guard
  - `x_api_timeout_sec: int = Field(default=30, ge=5, le=120)` — httpx/requests timeout for tweepy calls

### Integration
- **D-12:** **Scheduler wiring:** after `run_synthesis`, the scheduler calls `run_publish(session, cycle_id, synthesis_result, settings, x_client) -> PublishResult`. `PublishResult` has `counts_patch` dict with `publish_status, tweet_id, daily_cap_skipped, cost_capped, rate_limited, stale_pending_cleaned`. Merged into `run_log.counts` before `finish_cycle`.
  - Cap checks happen at the TOP of `run_cycle`, BEFORE `run_ingest`? No — we want ingest + cluster to run for observability. **Final decision:** Cap checks happen BETWEEN `run_clustering` and `run_synthesis`. If capped, skip both synthesis and publish; cluster audit trail is still written (Phase 5 already persists clusters before returning).
  - Revised order: `run_ingest → run_clustering → check_caps(session, settings) → run_synthesis (if not capped) → run_publish (if not capped + not dry_run + not empty) → finish_cycle`.
- **D-13:** **X client per-cycle** (matches httpx + anthropic pattern). Build `tweepy.Client(..., return_type=requests.Response)` once per cycle. No explicit close needed (tweepy uses requests internally).

### Claude's Discretion
- Module layout: recommend `src/tech_news_synth/publish/{__init__,client,caps,idempotency,orchestrator,models}.py` (mirrors Phase 4/5/6 layout).
- `PublishResult` model shape — pydantic v2 frozen; fields: `post_id, status, tweet_id, attempts, elapsed_ms, error_detail, counts_patch`.
- `check_caps(session, settings)` return value — recommend `CapCheckResult(daily_reached: bool, daily_count: int, monthly_cost_reached: bool, monthly_cost_usd: float, skip_synthesis: bool)`.
- Posts-repo extensions — add `update_post_to_posted(session, post_id, tweet_id, posted_at)` + `update_post_to_failed(session, post_id, error_detail_json)` + `get_stale_pending_posts(session, cutoff_dt)`. Pure SQL helpers.
- Logging — bind `phase="publish"` contextvar at top of `run_publish`.
- Whether to parse tweet_id from `response.json()["data"]["id"]` (proven Phase 3 pattern) or tweepy's `.json()` then extract — use the raw pattern for header access consistency.
- Runbook doc `docs/runbook-orphaned-pending.md` content — brief operator guide for manual X account timeline check + optional mark-as-posted SQL. Claude writes a stub; operator expands.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project context
- `.planning/PROJECT.md` — X pay-per-use decision, cost envelope
- `.planning/REQUIREMENTS.md` §PUBLISH-01..PUBLISH-06
- `.planning/ROADMAP.md` §"Phase 7: Publish"
- `.planning/intel/x-api-baseline.md` — Phase 3 live proof (tweet_id `2043757607970619474`, $0.03/post observed, `x-user-limit-24hour-*` absent on pay-per-use tier, 24h cap governed by local counter not headers)
- `.planning/phases/03-validation-gate/03-VERIFICATION.md` — GO decision
- `.planning/phases/06-synthesis/06-CONTEXT.md` (D-08 posts row, D-10 synthesized_text, D-12 DRY_RUN)
- `.planning/phases/06-synthesis/06-02-SUMMARY.md` (SynthesisResult interface)
- `CLAUDE.md` — tweepy 4.14 stack

### External specs
- tweepy `Client.create_tweet` — https://docs.tweepy.org/en/stable/client.html
- tweepy OAuth 1.0a User Context — https://docs.tweepy.org/en/stable/authentication.html
- X API v2 rate limits — https://developer.x.com/en/docs/twitter-api/rate-limits
- X error codes + header reference — https://developer.x.com/en/support/x-api/error-troubleshooting

### Research outputs
- `scripts/smoke_x_post.py` — Phase 3 proven post+delete flow + `return_type=requests.Response` pattern

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (Phases 1-6)
- `tech_news_synth.config.Settings.{x_consumer_key, x_consumer_secret, x_access_token, x_access_token_secret}` (SecretStr) — already loaded; OAuth 1.0a ready.
- `tech_news_synth.db.posts` repo — extend with cap-query + state-transition helpers.
- `tech_news_synth.synth.models.SynthesisResult` — Phase 6 output includes `post_id`, `text` (final formatted), `status` (`'pending' | 'dry_run'`). Phase 7 consumes these.
- `scripts/smoke_x_post.py` — proven tweepy Client construction with `return_type=requests.Response`, create_tweet, header extraction.
- `tech_news_synth.logging.get_logger().bind(phase="publish", cycle_id=...)` — structlog pattern.

### Established Patterns
- Pure-function modules + phase orchestrator.
- pydantic v2 for boundary models.
- structlog phase binding.
- UTC everywhere; `datetime.now(timezone.utc)`.
- Per-cycle SDK clients (httpx, anthropic, now tweepy).
- Settings extended with phase-specific fields + validators.
- Integration tests with `pytest.mark.integration` against compose postgres; respx for HTTP mocking (applies to tweepy's underlying `requests` via `responses` lib or custom Client mocking).
- DRY_RUN flow: Phase 6 sets status='dry_run'; downstream phases check and skip live side effects.

### Integration Points
- `src/tech_news_synth/scheduler.py::run_cycle` — insert `check_caps` between `run_clustering` and `run_synthesis`; insert `run_publish` between `run_synthesis` and `finish_cycle`. Build `tweepy.Client` once per cycle.
- `src/tech_news_synth/__main__.py` — no new boot-time loaders; everything flows from Settings + per-cycle client construction.
- `src/tech_news_synth/db/posts.py` — add 3 state-transition helpers + 2 cap-query helpers + `get_stale_pending_posts`.
- No DB schema changes — all writes/reads hit existing `posts` columns.
- No new deps — `tweepy>=4.14,<5` + `requests` (transitive) already pinned.

</code_context>

<specifics>
## Specific Ideas

- tweet_id parsing: `response.json()["data"]["id"]` (string) per Phase 3 smoke_x_post.py.
- posted_at is captured as `datetime.now(timezone.utc)` AFTER successful `create_tweet` returns; stored as TIMESTAMPTZ.
- stale-pending-minutes default 5 is generous vs the actual ~2s window; operator can tighten to 2 later via env.
- `docs/runbook-orphaned-pending.md` stub content:
  ```
  # Orphaned Pending Posts Runbook
  Triggered by structlog event `orphaned_pending`. The row(s) are marked `failed` automatically.
  To investigate: visit https://x.com/ByteRelevant — if a tweet matching `posts.synthesized_text` exists,
  manually `UPDATE posts SET status='posted', tweet_id='<id>', error_detail=NULL WHERE id=<row_id>;`.
  Otherwise leave as `failed` — next cycle supersedes.
  ```
- `check_caps` is cheap: 2 SQL queries, ~5ms total. No caching needed.
- `run_log.counts` Phase 7 additions: `daily_cap_skipped: bool`, `daily_posts_count: int`, `monthly_cost_capped: bool`, `monthly_cost_usd: float`, `publish_status: str` (one of `posted|failed|dry_run|capped|orphaned_cleaned|empty`), `tweet_id: str | null`, `stale_pending_cleaned: int`.

</specifics>

<deferred>
## Deferred Ideas

- **Active retry queue** for transient failures — next-cycle natural re-synthesis is good enough in v1.
- **Discord/Telegram alerts on cap breach** — out of scope per PROJECT.md (OPS alerts deferred).
- **Multi-account posting** (fallback handle if @ByteRelevant 429s) — single handle in v1.
- **Idempotency-key via embedded marker in tweet** — UX-ugly; stale-pending guard + operator workflow suffices.
- **Daily cap pre-warmup** (fetch X account timeline to count actual posts today) — redundant given local counter is authoritative per Phase 3 intel.
- **Cost forecasting** (predict end-of-month spend from first week) — Phase 8 OPS concern.
- **Scheduled retry of failed posts** — treat failure as terminal in v1; operator re-enables manually if needed.
- **Per-hour rate limiting** (burst control) — 12/day is already well below any hourly limit.

</deferred>

---

*Phase: 07-publish*
*Context gathered: 2026-04-14 via inline defaults (discuss skipped)*
