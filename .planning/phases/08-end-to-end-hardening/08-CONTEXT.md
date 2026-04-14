# Phase 8: End-to-End + Hardening - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning (final phase)

<domain>
## Phase Boundary

Ship v1 to production on @ByteRelevant. Deliver: (1) a single aggregated `cycle_summary` JSON log line per cycle; (2) three operator CLIs (`replay`, `post-now`, `source-health`) that flesh out the Phase 1 D-06 dispatcher stubs; (3) `docs/DEPLOY.md` runbook validated on a fresh Ubuntu VPS; (4) a 48-hour `DRY_RUN=1` soak with pass criteria documented; (5) a live-cutover protocol with rollback steps and post-cutover verification (≥12 tweets/24h, zero 48h dupes, cost within ±50% of Phase 3 baseline). No new requirements or features — pure hardening + operational readiness.

</domain>

<decisions>
## Implementation Decisions

### CLIs (OPS-02/03/04)
- **D-01:** **`replay --cycle-id X`** re-runs synthesis ONLY, prints to stdout, no DB writes, no publish.
  - Fetch the winning cluster + member articles for the target cycle_id via existing Phase 2/5 helpers.
  - If cycle has `fallback_article_id` instead of `winner_cluster_id`: fetch the single article and synthesize against it (same path as Phase 6 fallback).
  - Call `run_synthesis(...)` but with a `persist=False` override — the orchestrator signature gets a keyword flag. NO `insert_post` call; NO `update_post_to_*` call.
  - Real Anthropic call (~$0.0001 real cost per replay); print `{cycle_id, text, hashtags, cost_usd, input_tokens, output_tokens, final_method}` as JSON to stdout.
  - On missing cluster/article: exit 1 with `cycle-id not found or has no resolvable input` message.
- **D-02:** **`post-now`** calls `run_cycle()` inline from the CLI process.
  - Open a session, reuse all existing run_cycle code (kill-switch, DRY_RUN, cap checks, anti-repeat, publish). Blocks until cycle completes (~30-90s). Prints the same `cycle_summary` log line the scheduler emits.
  - Does NOT interfere with APScheduler's next tick — schedule is unchanged.
  - Exits with the cycle's status (`ok` → 0, `failed|capped|paused` → non-zero).
  - Safe to run while scheduler is also up (session isolation + Phase 7 stale-pending guard prevents double-publish).
- **D-03:** **`source-health`** has 3 modes:
  - No args → read-only status table: `name | last_fetched_at | last_status | consecutive_failures | disabled_at (YES/NO)` printed as aligned text (or `--json` for machine-readable).
  - `source-health --enable NAME` → UPDATE source_state: `disabled_at=NULL, consecutive_failures=0`. Logs audit event. Exits 0 on success, 1 if name unknown.
  - `source-health --disable NAME` → UPDATE source_state: `disabled_at=NOW()`. Logs audit event. Completes the Phase 4 D-13 re-enable contract both directions.
  - All three use existing `db/source_state.py` helpers (no new SQL).

### cycle_summary Log Line (OPS-01)
- **D-04:** **Emitted inside `finish_cycle`** after the DB commit succeeds. One `log.info("cycle_summary", ...)` per cycle. Guarantees durability invariant: if the line appears in logs, the DB row also exists.
- **D-05:** **Coexists with per-phase events** (`source_fetch_*`, `cluster_winner`, `synth_done`, `publish_posted`). `cycle_summary` is the operator dashboard view; per-phase events remain for debugging.
- **D-06:** **10 fields on the cycle_summary line** (OPS-01 spec + 2):
  1. `cycle_id` (ULID string)
  2. `duration_ms` (int — cycle wall-clock, from start_cycle to finish_cycle)
  3. `articles_fetched_per_source` (dict[str, int] — from run_log.counts)
  4. `cluster_count` (int)
  5. `chosen_cluster_id` (int | null)
  6. `char_budget_used` (int | null — weighted_len of final synthesized_text, null on no-synth paths)
  7. `token_cost_usd` (float | null — synth_cost_usd, null on no-synth)
  8. `post_status` (str — one of `posted|failed|dry_run|capped|empty|paused`)
  9. **`status`** (str — run_log.status: `ok|failed|paused|cost_capped`)
  10. **`dry_run`** (bool — settings.dry_run value at cycle start)

### 48h DRY_RUN Soak (OPS-06) — Claude's Discretion
- **D-07:** **Soak automation via a monitoring script.** New `scripts/soak_monitor.py` (operator-runnable on host) polls `run_log` every 30 min for 48h:
  - Checks: last cycle timestamp < 2.5h ago (no missed cycles), last 24h cycle count ≥ 10 (within 48h: ≥ 20), no `status='failed'` rows, every cycle has a `dry_run` row in `posts`.
  - Writes a progress log to stdout + appends to `.planning/intel/soak-log.md` (new intel doc).
  - On failure: prints red-flag summary, exits non-zero; operator investigates.
- **D-08:** **Soak pass criteria (SC-4):**
  - ≥ 24 cycles over 48h (one per 2h ±30min tolerance)
  - Zero unhandled exceptions (all cycle errors caught by INFRA-08 and logged; none crash PID 1)
  - Every cycle produces a `posts` row with `status='dry_run'` (fallback scenarios allowed; empty-window scenarios count as "no synthesis this cycle" and do NOT produce a posts row — document this explicitly)
  - Every cycle emits exactly one `cycle_summary` log line
  - Allow **up to 2 cycles with `status='failed'`** (transient network / Anthropic blip); flag if > 2.

### Live Cutover (SC-5) — Claude's Discretion
- **D-09:** **Cutover is operator-executed** with a documented checklist in `docs/DEPLOY.md`:
  1. Soak passed (D-08 criteria met)
  2. Operator sets `DRY_RUN=0` in `.env`
  3. `docker compose restart app` (or equivalent)
  4. Operator monitors first 3 cycles live (logs + X account + posts table)
  5. If anything goes wrong: rollback = `DRY_RUN=1` in `.env` + `docker compose restart app` + query `posts WHERE status='pending' AND created_at > <cutover_ts>` → operator manually investigates and may delete rows/tweets
  6. After 24h live: verify via new `scripts/cutover_verify.py` (see D-10)
- **D-10:** **`scripts/cutover_verify.py`** runs the post-24h acceptance check (SC-5):
  - Count posts with `status='posted' AND posted_at > <cutover_ts>` → assert ≥ 12
  - Anti-repeat audit: for each posted post in the last 48h, compute cosine similarity of its `theme_centroid` against all other posts in the same window; report pairs ≥ 0.5 similarity (SHOULD be zero — Phase 5 D-03 anti-repeat filter should have caught them before publish)
  - Cost check: SUM cost_usd over the 24h window; compare against Phase 3 baseline ($0.03/post × 12 = $0.36 expected + ~$0.001 synthesis). Flag if > 2× expected.
  - Writes findings to `.planning/intel/cutover-report.md` (new intel doc).

### DEPLOY.md Runbook (OPS-05) — Claude's Discretion
- **D-11:** **`docs/DEPLOY.md` structure:**
  - Prerequisites (Ubuntu 22.04+, Docker Engine ≥26, Compose v2, git, ≥2GB RAM, ≥5GB disk)
  - Secrets acquisition (Anthropic API key, X Developer Portal 4 OAuth tokens — Phase 3 smoke script reference for validation)
  - Clone + configure (`.env` from `.env.example`, fill secrets, optionally tune caps)
  - Boot (`docker compose up -d --build`, verify health via `docker compose ps`)
  - First-cycle verification (reuse Phase 7 smoke protocol — DRY_RUN=1 preferred for first boot)
  - Daily operations (`docker compose logs -f app`, `docker compose exec app python -m tech_news_synth source-health`, common failure modes)
  - Soak + cutover (reference `scripts/soak_monitor.py` + D-09 checklist)
  - Troubleshooting: orphaned_pending (link to existing runbook), source disabled, Anthropic errors, X 429s, cap breaches
  - Validated by reading aloud on a fresh Ubuntu VPS (operator does this; not automatable) OR a GitHub Actions "fresh Ubuntu" job (deferred — operator manual validation is sufficient for v1)

### Integration / Plumbing
- **D-12:** **`run_synthesis` signature extension:** add `persist: bool = True` keyword-only parameter. When False, skip the `insert_post` call; return SynthesisResult without post_id (null). Allows `replay` CLI to reuse all existing synthesis logic without duplication.
- **D-13:** **CLI argparse dispatch already exists in `__main__.py`** (Phase 1 D-06 subcommand stubs). Phase 8 replaces the stub bodies with real implementations in `src/tech_news_synth/cli/{replay,post_now,source_health}.py`. No new subcommand registration needed.

### Claude's Discretion
- Exact soak monitoring cadence (30 min vs 1h) — 30 min recommended for early failure detection.
- Whether `post-now` should require an `--confirm` flag when `DRY_RUN=0` (defense-in-depth) — recommend NO: CLI is already an intentional operator action.
- Cost check tolerance multiplier (2× vs 1.5×) — 2× recommended; single 24h sample is noisy.
- Whether the 48h soak should include a simulated failure injection (kill network mid-cycle) — defer; passive monitoring is enough for v1.
- Whether `DEPLOY.md` should include a "v1 graduation" section (how to move to v2 milestone cleanly) — defer to post-v1 `/gsd-complete-milestone`.
- `run_log.counts` field naming — existing Phase 4-7 keys stay; Phase 8 only READS from them.
- Whether `cycle_summary` goes to stdout only or also to the `/data/logs/app.jsonl` file — both (inherits structlog dual-sink from Phase 1 D-07).

</decisions>

<canonical_refs>
## Canonical References

### Project context
- `.planning/PROJECT.md` — cost envelope, cadence target
- `.planning/REQUIREMENTS.md` §OPS-01..OPS-06
- `.planning/ROADMAP.md` §"Phase 8: End-to-End + Hardening"
- `.planning/intel/x-api-baseline.md` — Phase 3 GO ($0.03/post, Read+Write confirmed)
- `.planning/phases/01-foundations/01-CONTEXT.md` (D-06 subcommand dispatcher stubs)
- `.planning/phases/04-ingestion/04-CONTEXT.md` (D-13 re-enable CLI placeholder)
- `.planning/phases/06-synthesis/06-02-SUMMARY.md` (run_synthesis interface)
- `.planning/phases/07-publish/07-02-SUMMARY.md` (run_publish interface)
- `docs/runbook-orphaned-pending.md` (Phase 7 operator runbook)
- `CLAUDE.md`

### External specs
- Docker Compose v2 operational reference — https://docs.docker.com/compose/
- Ubuntu VPS hardening basics — operator-known

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/tech_news_synth/cli/{replay,post_now,source_health}.py` — stub modules exist from Phase 1; Phase 8 replaces stub bodies.
- `src/tech_news_synth/__main__.py` — argparse dispatcher already routes subcommands; no changes needed.
- `src/tech_news_synth/synth/orchestrator.py::run_synthesis` — extend with `persist: bool = True` keyword.
- `src/tech_news_synth/scheduler.py::run_cycle` — extend `finish_cycle` emit to include the cycle_summary log line.
- `src/tech_news_synth/db/run_log.py::finish_cycle` — the emit point for `cycle_summary`.
- `src/tech_news_synth/db/source_state.py` — all needed helpers exist (get_state, mark_ok/error/disabled, and a simple `enable_source(name)` helper to add).
- `src/tech_news_synth/db/posts.py` — reads for post-hoc audits.
- `src/tech_news_synth/cluster/antirepeat.py::is_repeat` — reusable for cutover_verify.py dup audit.
- structlog + JSON logging already dual-sink to stdout + `/data/logs/app.jsonl`.

### Established Patterns
- Pure-function modules, per-cycle clients, UTC everywhere, structlog bind contextvars.
- Settings extended per-phase with validators.
- `scripts/` directory for operator tools (Phase 3 smoke scripts, Phase 2 create_test_db.sh).
- `.planning/intel/` for operator-facing intel docs.
- `docs/` for runbooks.

### Integration Points
- `db/run_log.py::finish_cycle` — add cycle_summary log emit AFTER commit.
- `synth/orchestrator.py::run_synthesis` — add `persist` kwarg.
- `cli/replay.py` — full implementation.
- `cli/post_now.py` — full implementation.
- `cli/source_health.py` — full implementation.
- `db/source_state.py` — add `enable_source(session, name)` + `disable_source(session, name)` helpers if not already present.
- `scripts/soak_monitor.py` — new.
- `scripts/cutover_verify.py` — new.
- `docs/DEPLOY.md` — new.
- `.planning/intel/soak-log.md` + `.planning/intel/cutover-report.md` — new (templates + filled-by-operator).
- No compose.yaml changes.
- No new Python deps.

</code_context>

<specifics>
## Specific Ideas

- `cycle_summary` sample line (JSON, one-line):
  ```json
  {"event": "cycle_summary", "cycle_id": "01KP...", "duration_ms": 3421, "articles_fetched_per_source": {"techcrunch": 8, "verge": 12, ...}, "cluster_count": 4, "chosen_cluster_id": 42, "char_budget_used": 223, "token_cost_usd": 0.00014, "post_status": "posted", "status": "ok", "dry_run": false, "timestamp": "2026-04-14T22:00:03.421Z"}
  ```
- `source-health` text output:
  ```
  name                last_fetched_at              last_status  failures  disabled
  techcrunch          2026-04-14T22:00:00Z         ok           0         NO
  verge               2026-04-14T22:00:01Z         ok           0         NO
  ars_technica        2026-04-14T22:00:00Z         skipped_304  0         NO
  hacker_news         2026-04-14T22:00:02Z         ok           0         NO
  reddit_technology   2026-04-14T18:00:00Z         error:http_403  3     NO
  ```
- `scripts/soak_monitor.py` output: one line per check + final summary.
- Intel doc `soak-log.md` template has placeholders for start_ts, end_ts, cycle_count, failures, anomalies, operator notes.
- `post-now` respects the "run immediately on boot" pattern but does NOT register with APScheduler — it's a one-shot invocation of `run_cycle(session, cycle_id=new_cycle_id(), settings, sources_config, hashtag_allowlist)`.

</specifics>

<deferred>
## Deferred Ideas

- **Prometheus / OpenTelemetry metrics export** — structlog JSON + grep is sufficient for v1.
- **Health endpoint** (HTTP /health for external monitors) — compose healthcheck covers container-level.
- **Automatic rollback on cutover** (auto-flip DRY_RUN=1 if N failures) — manual rollback via documented checklist is fine for solo operator.
- **Failure injection testing** — defer to v2 chaos engineering.
- **Multi-account cutover staging** — single account in v1.
- **Web dashboard** for operator view — out of scope per PROJECT.md.
- **Auto-tuning of `max_posts_per_day` based on 7-day rolling engagement** — no engagement signal in v1.
- **CI job for fresh-Ubuntu deploy validation** — defer; operator manual validation of DEPLOY.md suffices for single-handle v1.

</deferred>

---

*Phase: 08-end-to-end-hardening*
*Context gathered: 2026-04-14 via /gsd-discuss-phase*
