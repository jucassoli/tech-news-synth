---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: "Completed 08-01-PLAN.md (cycle_summary + 3 CLIs). Plan 08-02 next (soak + cutover + DEPLOY.md)."
last_updated: "2026-04-14T17:37:08Z"
progress:
  total_phases: 8
  completed_phases: 7
  total_plans: 16
  completed_plans: 14
  percent: 88
---

# tech-news-synth — STATE

**Last updated:** 2026-04-14

## Project Reference

- **What:** Python agent that every 2h pulls tech news from 5 public feeds (TechCrunch/Verge/Ars RSS + HN Firebase + Reddit r/tech JSON), clusters by TF-IDF title similarity, synthesizes the highest-coverage cluster into one PT-BR tweet via Claude Haiku 4.5, and posts to @ByteRelevant.
- **Core value:** One post per cycle that highlights the most-covered tech topic without repeating within 48h — signal over noise.
- **Current focus:** Phase 08 — End-to-End + Hardening

## Current Position

Phase: 08 (End-to-End + Hardening) — EXECUTING
Plan: 2 of 2

- **Milestone:** v1 (initial production-ready agent on @ByteRelevant)
- **Phase:** 08 — End-to-End + Hardening (EXECUTING)
- **Plan:** 08-01 COMPLETE → 08-02 next (operator tooling + DEPLOY.md)
- **Status:** Executing Phase 08
- **Progress:** [█████████░] 88%

## Decisions

- Phase 8 D-04/D-06: `cycle_summary` emitted from scheduler outer finally AFTER commit (not inside finish_cycle); 10 fields including `status` + `dry_run`.
- Phase 8 D-12: `run_synthesis(..., *, persist=True)` keyword-only. persist=False returns post_id=None, status='replay'; enables replay CLI reuse of orchestrator.
- Phase 8 D-06 field 6: `char_budget_used = weighted_len(final_text)` now in synth counts_patch (reachable even when persist=False).
- tweepy 4.16 Client has no `timeout` kwarg; enforce via `functools.partial` monkey-wrap of `client.session.request` (T-07-08)
- Fixed T-07-07: `update_posted(cost_usd=None)` no longer overwrites existing column value — preserves Phase 6 pre-populated cost
- PG 16 3-arg `date_trunc('day', now(), 'UTC')` verified working; used for daily/monthly cap queries
- `update_post_to_posted` / `update_post_to_failed` are thinner than `update_posted` (no cost_usd/centroid params) — D-10 transitions only, cost_usd preserved from Phase 6

## Performance Metrics

- **Phases planned:** 2 / 8
- **Plans complete:** 3 / 4 (Phase 01 complete; Phase 02 P01 complete)
- **Requirements covered:** 10 / 54 (+ STORE-02, STORE-04, STORE-06 partial — schema/helpers ready, Plan 02-02 completes)
- **Cycles executed:** 0
- **Dry-run hours accumulated:** 0 / 48 (soak target in Phase 8)

### Plan Execution Log

| Plan | Duration (s) | Tasks | Files | Commits | Result |
|------|--------------|-------|-------|---------|--------|
| 01-01 | 302 | 5 | 24 | 6 | 53 passed, 3 skipped (stubs), 99% cov |
| Phase 01 P02 | 457 | 3 tasks | 13 files |
| Phase 02 P01 | 1300 | 5 tasks | 20 files |
| Phase 03-validation-gate P01 | 205 | 5 tasks | 6 files |
| Phase 04 P02 | 25 | 7 tasks | 14 files |
| Phase 05 P01 | 40min | 5 tasks | 22 files |
| Phase 06 P01 | 2700 | 5 tasks | 32 files |
| Phase 07 P01 | 1080 | 5 tasks | 14 files | 5 | 440 passed (+46 new: 17 unit + 21 integration + reshuffled), 0 regressions |
| Phase 07 P01 | 1080 | 5 tasks | 14 files |
| Phase 07 P02 | 9 | 3 tasks | 11 files |
| Phase 08 P01 | 873 | 5 tasks | 17 files | 6 | 381 unit + 19 Phase 8 integration passed (+32 new); 0 regressions |

## Accumulated Context

### Key Decisions (locked)

- Single-provider synthesis: Anthropic `claude-haiku-4-5` pinned (no alias; Haiku 3 EOL 2026-04-19)
- Scheduler: APScheduler `BlockingScheduler` as PID 1 in the app container (NOT system cron, NOT supercronic)
- Clustering: scikit-learn TF-IDF char n-grams (3–5) + cosine + agglomerative, threshold 0.35 default
- Anti-repeat: centroid cosine ≥ 0.5 vs last-48h `posts` centroids (NOT string hash)
- Char budget: weighted char count, t.co fixed at 23, 2 re-prompt retries, whitespace truncation last
- X tier: pay-per-use accepted; Phase 3 gate confirms actual cost + cap
- Persistence: SQLAlchemy 2.0 typed + psycopg 3 + alembic; all timestamps `TIMESTAMPTZ`
- Base image: `python:3.12-slim-bookworm` (Alpine breaks scikit-learn/lxml wheels)
- Secrets: `.env` + `env_file:` in compose; `.env.example` versioned; pre-commit secret scan
- Logs: structlog JSON → stdout + Docker volume; `cycle_id` bound per cycle
- Phase 5 pure-core: PT stopwords stripped in `preprocess()` (not TfidfVectorizer param) — sklearn silently ignores `stop_words` with `analyzer=char_wb` (research P-1)
- Phase 5 anti-repeat: ONE TF-IDF fit per cycle over combined current+past_posts corpus with `FittedCorpus` slice bookkeeping (D-01); past-post centroids computed from the same feature space as cluster centroids
- Phase 6 weighted char counting: `twitter-text-parser` wraps `parse_tweet(text).weightedLength` in `synth/charcount.py` (D-04). Setuptools pinned `<81` to keep `pkg_resources` importable for the library.
- Phase 6 model id: literal `"claude-haiku-4-5"` in `synth/pricing.py` with unit-test equality assertion (T-06-03 mitigation; never an alias like `haiku-latest`).
- Phase 6 ellipsis weight: twitter-text-parser 3.0.0 reports `weighted_len("\u2026") == 2` (not 1). Truncator reserves the measured value dynamically; gate test asserts real value so upstream drift fails loudly (T-06-07).
- Phase 6 hashtag selection: `config/hashtags.yaml` allowlist + `select_hashtags` slug-substring match against centroid terms; LLM never picks hashtags (D-11, T-06-05).

### Open Questions (deferred to phase research)

- Phase 5: empirical TF-IDF threshold tuning on PT-BR headlines (need ~50-pair labeled fixture)
- Phase 6: Haiku 4.5 char-budget compliance rate in PT-BR; tune retry policy if retries > 10%
- Phase 2: centroid storage format — pickled BYTEA vs. `TEXT[]` top-K terms (both work; decide at schema design)
- Phase 7: exact pay-per-use cost model — only knowable post-Phase-3

### Todos (inbox)

- [ ] Execute Plan 06-02 (synth orchestrator composition + scheduler wiring + integration tests + 10-post spot-check)
- [ ] Confirm `.planning/intel/` directory exists (will be created during Phase 3 gate)

### Blockers

- None for Plan 07-02.
- Plan 01-02 checkpoint (11-step docker compose smoke) still pending operator sign-off — does not block Plan 07-02 development.

## Session Continuity

- **Last session:** 2026-04-14T17:37:08Z
- **Last action:** Plan 08-01 executed: `cycle_summary` structlog event (10 fields, post-commit), `replay`/`post-now`/`source-health` CLIs implemented (replace Phase 1 D-06 stubs), `run_synthesis(persist=False)` kwarg for replay reuse, `char_budget_used` propagated through counts_patch. 32 new tests (18 unit + 14 integration). 381 unit + 113 integration passed.
- **Stopped At:** Completed 08-01-PLAN.md (cycle_summary + 3 CLIs). Plan 08-02 next (soak + cutover + DEPLOY.md).
- **Next action:** Execute Plan 08-02 (scripts/soak_monitor.py, scripts/cutover_verify.py, docs/DEPLOY.md, intel templates).
- **Resume command:** `/gsd-execute-phase 08`

---
*STATE.md is the single source of truth for "where are we right now." Updated at phase transitions and plan completion.*
