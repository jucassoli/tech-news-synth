# tech-news-synth — STATE

**Last updated:** 2026-04-12

## Project Reference

- **What:** Python agent that every 2h pulls tech news from 5 public feeds (TechCrunch/Verge/Ars RSS + HN Firebase + Reddit r/tech JSON), clusters by TF-IDF title similarity, synthesizes the highest-coverage cluster into one PT-BR tweet via Claude Haiku 4.5, and posts to @ByteRelevant.
- **Core value:** One post per cycle that highlights the most-covered tech topic without repeating within 48h — signal over noise.
- **Current focus:** Roadmap complete; awaiting Phase 1 planning.

## Current Position

- **Milestone:** v1 (initial production-ready agent on @ByteRelevant)
- **Phase:** — (not started; next up: Phase 1 Foundations)
- **Plan:** —
- **Status:** Roadmap approved; ready for `/gsd-plan-phase 1`
- **Progress:** `[░░░░░░░░] 0/8 phases complete`

## Performance Metrics

- **Phases planned:** 0 / 8
- **Plans complete:** 0 / ?
- **Requirements covered:** 0 / 54 (all mapped, none executed yet)
- **Cycles executed:** 0
- **Dry-run hours accumulated:** 0 / 48 (soak target in Phase 8)

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

### Open Questions (deferred to phase research)

- Phase 5: empirical TF-IDF threshold tuning on PT-BR headlines (need ~50-pair labeled fixture)
- Phase 6: Haiku 4.5 char-budget compliance rate in PT-BR; tune retry policy if retries > 10%
- Phase 2: centroid storage format — pickled BYTEA vs. `TEXT[]` top-K terms (both work; decide at schema design)
- Phase 7: exact pay-per-use cost model — only knowable post-Phase-3

### Todos (inbox)

- [ ] Run `/gsd-plan-phase 1` to decompose Foundations into executable plans
- [ ] Confirm `.planning/intel/` directory exists (will be created during Phase 3 gate)

### Blockers

- None currently.

## Session Continuity

- **Last action:** Roadmap authored by `/gsd-new-project` roadmapper.
- **Next action:** Operator reviews `.planning/ROADMAP.md`, then runs `/gsd-plan-phase 1`.
- **Resume command:** `/gsd-plan-phase 1`

---
*STATE.md is the single source of truth for "where are we right now." Updated at phase transitions and plan completion.*
