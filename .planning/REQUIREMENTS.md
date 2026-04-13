# tech-news-synth — v1 Requirements

**Milestone:** v1 (initial production-ready agent on @ByteRelevant)
**Derived from:** `.planning/PROJECT.md`, `.planning/research/SUMMARY.md` + research files
**Last updated:** 2026-04-12

## Conventions

- REQ-IDs follow `[CATEGORY]-[NUMBER]`. Categories: INFRA, GATE, STORE, INGEST, CLUSTER, SYNTH, PUBLISH, OPS.
- Requirements are user- or operator-observable behaviors the system must deliver.
- Each requirement is atomic (one capability) and testable.
- Traceability (phase mapping) is filled by the roadmapper.

---

## v1 Requirements

### INFRA — Foundations (Docker, Config, Observability, Scheduler)

- [x] **INFRA-01** — App runs via `docker compose up` with two services (`app`, `postgres`) and persistent volumes for DB and logs
- [x] **INFRA-02** — Container base is `python:3.12-slim-bookworm` (no Alpine); dependencies installed via `uv` with pinned `pyproject.toml` + lockfile
- [x] **INFRA-03** — Secrets loaded via `pydantic-settings` from `.env` (through Compose `env_file:`); missing/invalid keys fail boot with clear error
- [x] **INFRA-04** — `.env.example` committed; `.env` ignored by `.gitignore` and `.dockerignore`; pre-commit hook scans for leaked secrets
- [x] **INFRA-05** — Cycle runs on a long-lived in-process **APScheduler** (`BlockingScheduler` as PID 1) with `CronTrigger(hour="*/{INTERVAL_HOURS}")` and `timezone=UTC`
- [x] **INFRA-06** — All timestamps are UTC: Postgres columns use `TIMESTAMPTZ`; Python uses `datetime.now(timezone.utc)`; no `TZ=` set on containers
- [x] **INFRA-07** — Structured JSON logs via `structlog`, written to stdout **and** a Docker volume; every log line includes a `cycle_id` bound at cycle start
- [x] **INFRA-08** — Per-cycle graceful failure: any unhandled exception inside `run_cycle()` is logged with stacktrace but never crashes the scheduler
- [x] **INFRA-09** — Kill switch respected at cycle start: if `PAUSED=1` env flag or `/data/paused` marker file exists, cycle exits 0 with a log line and performs no I/O
- [x] **INFRA-10** — `DRY_RUN=1` flag short-circuits publishing (synthesis still runs; write to DB with `status=dry_run`; no X API call)

### GATE — Pre-Implementation Validation

- [ ] **GATE-01** — Smoke test script confirms Anthropic API access with `claude-haiku-4-5` returns a valid completion on a minimal prompt
- [ ] **GATE-02** — Smoke test script confirms X OAuth 1.0a User Context: `client.get_me()` succeeds with the 4 configured secrets
- [ ] **GATE-03** — Smoke test script publishes one real tweet to @ByteRelevant and deletes it; records actual cost per post and daily cap observed from X response headers
- [ ] **GATE-04** — Gate outcome (cost model, caps, OAuth permissions state) is documented in `.planning/intel/x-api-baseline.md` before pipeline work proceeds

### STORE — Persistence Layer

- [ ] **STORE-01** — Postgres schema managed by Alembic migrations, versioned in the repo; `alembic upgrade head` runs on container startup
- [x] **STORE-02** — `articles` table stores normalized articles with `article_hash` (`UNIQUE`, from canonicalized URL); upsert idempotent via `ON CONFLICT DO NOTHING`
- [ ] **STORE-03** — `clusters` table persists cluster metadata per cycle (cycle_id, member article ids, centroid/top-K terms, chosen status, coverage score)
- [x] **STORE-04** — `posts` table persists publish attempts with columns: `theme_centroid` (BYTEA or `TEXT[]`), `status` (`pending|posted|failed|dry_run`), `tweet_id`, `cost_usd`, `created_at`, `posted_at`
- [ ] **STORE-05** — `run_log` table records every cycle: `cycle_id`, `started_at`, `finished_at`, `status`, `counts` (articles fetched per source, clusters formed), `notes`
- [x] **STORE-06** — All article/post timestamps in `TIMESTAMPTZ`; retention of articles is at least 14 days to support 48h anti-repetition with safety margin

### INGEST — Sources, Fetch, Normalize

- [ ] **INGEST-01** — Source list loaded from a mounted `sources.yaml` (not DB); schema supports add/edit/remove without code changes; invalid entries fail boot with clear error
- [x] **INGEST-02** — Initial source set supported: TechCrunch RSS, The Verge RSS, Ars Technica RSS, Hacker News (Firebase `topstories`), Reddit r/technology (`.json`)
- [ ] **INGEST-03** — Each source fetch uses `httpx` with a per-source timeout, descriptive User-Agent `ByteRelevant/0.1 (+https://x.com/ByteRelevant)`, and `tenacity` retry (max 3, exponential backoff)
- [x] **INGEST-04** — Conditional GET: per-source ETag and `Last-Modified` stored in DB and sent on subsequent fetches to avoid re-processing unchanged feeds
- [x] **INGEST-05** — Per-source failure isolation: a 5xx, timeout, or parse error on one source logs a warning and is skipped; cycle continues with remaining sources
- [ ] **INGEST-06** — Normalizer produces a unified `Article` dataclass: `id`, `source`, `url`, `canonical_url`, `title`, `summary`, `published_at` (UTC aware), `fetched_at`, `article_hash`; HTML stripped from summary via `beautifulsoup4/lxml`
- [x] **INGEST-07** — Source-health tracking: consecutive failure counter per source persisted; auto-disable after N consecutive failures (default 20) with an explicit re-enable CLI

### CLUSTER — Clustering, Ranking, Anti-Repetition

- [ ] **CLUSTER-01** — Clustering operates on articles from the last `CLUSTER_WINDOW_HOURS` (default 6) across all active sources
- [ ] **CLUSTER-02** — TF-IDF vectorizer uses char n-grams (range 3–5), PT+EN stopwords, `unidecode` normalization; operates on `title + " " + summary`
- [ ] **CLUSTER-03** — Agglomerative or similar clustering applied with a configurable cosine threshold (default 0.35) producing zero-or-more clusters
- [ ] **CLUSTER-04** — Winner selected deterministically: primary = count of distinct sources in cluster; tiebreak = recency of most recent article; secondary tiebreak = source-weight sum
- [ ] **CLUSTER-05** — Anti-repetition filter: before accepting a winner, compute cosine similarity against centroids of posts in the last 48h; reject if any ≥ 0.5 and fall back to the next best cluster
- [ ] **CLUSTER-06** — Fallback picker: when no cluster meets threshold, publish the single best-ranked article of the cycle (cadence > strict threshold — per Core Value)
- [ ] **CLUSTER-07** — Cluster-selection audit trail persisted per cycle: which cluster won, why (scores), which were rejected by anti-repeat, for operator inspection

### SYNTH — Synthesis (Claude Haiku 4.5)

- [ ] **SYNTH-01** — Synthesis calls the `anthropic` SDK with the pinned model id `claude-haiku-4-5` (no aliases)
- [ ] **SYNTH-02** — Prompt is PT-BR jornalístico neutro; input constrained to cluster's 3–5 articles (titles + summaries only, not full bodies); `max_tokens=150`
- [ ] **SYNTH-03** — Prompt includes explicit grounding guardrails: "use APENAS informações das manchetes/resumos fornecidos; NÃO invente datas, nomes, citações; mantenha nomes próprios intactos"
- [ ] **SYNTH-04** — Character budget enforced in Python after the LLM response using a weighted char count (t.co URL fixed at 23, plus hashtag budget); max 2 re-prompt retries with "encurte para N caracteres" before last-resort whitespace-aware truncation with ellipsis
- [ ] **SYNTH-05** — Hashtag selection pulls 1–2 tags from a curated allowlist in `sources.yaml` (or a separate `hashtags.yaml`); the LLM does not freestyle hashtags
- [ ] **SYNTH-06** — Final post structure: `<síntese PT-BR> <source-URL> <hashtag(s)>`; always includes the source URL for attribution
- [ ] **SYNTH-07** — Token usage and USD cost per synthesis call are logged in the cycle summary and stored on the `posts` row

### PUBLISH — X Posting

- [ ] **PUBLISH-01** — Publishing uses `tweepy.Client.create_tweet` with OAuth 1.0a User Context (4 secrets) — bearer-token path explicitly rejected at boot
- [ ] **PUBLISH-02** — Idempotent posting: a `posts` row with `status=pending` is inserted **before** the X API call; updated to `posted` + `tweet_id` on success, or `failed` with error details on error
- [ ] **PUBLISH-03** — Rate-limit handling: 429 response reads `x-rate-limit-reset`, logs a structured warning, and skips the remainder of the cycle (does not block the scheduler loop)
- [ ] **PUBLISH-04** — Local daily cap guard: `MAX_POSTS_PER_DAY` (default 12) counted from `posts.posted_at` in UTC; cycle skips publishing (still logs cluster/synthesis) once the cap is reached
- [ ] **PUBLISH-05** — Monthly cost cap guard: `MAX_MONTHLY_COST_USD` hard kill-switch based on summed `posts.cost_usd` in the current UTC month
- [ ] **PUBLISH-06** — On dry-run, publisher is short-circuited; the `posts` row is written with `status=dry_run` and the synthesized text for human review

### OPS — Operator Tools, Observability, Hardening

- [ ] **OPS-01** — Per-cycle `cycle_summary` log line (JSON) emitted with: cycle_id, duration, articles_fetched_per_source, cluster_count, chosen_cluster_id, char_budget_used, token_cost_usd, post_status
- [ ] **OPS-02** — `replay` CLI accepts a `--cycle-id` and re-runs synthesis against the stored cluster without publishing (for offline prompt iteration)
- [ ] **OPS-03** — `post-now` CLI forces an off-cadence cycle; respects all guardrails (kill switch, dry-run, daily cap, anti-repeat)
- [ ] **OPS-04** — `source-health` CLI lists each source's last fetch status, consecutive failure count, and disabled/enabled state
- [ ] **OPS-05** — `docker compose up -d` on a fresh Ubuntu VPS produces a working agent within a documented runbook (`docs/DEPLOY.md`)
- [ ] **OPS-06** — 48-hour soak in `DRY_RUN=1` mode passes with zero unhandled exceptions and at least one cycle per 2h window before live cutover

---

## Deferred (v2+)

- Multi-account / cross-posting (LinkedIn, Mastodon, second X handle)
- Threads (multi-tweet chains) — out of scope per PROJECT.md
- Web UI / dashboard — out of scope per PROJECT.md
- Active alerts (Discord/Telegram/email/Sentry) — out of scope per PROJECT.md; logs + optional daily grep cron suffice in v1
- Language detection / multilingual output — out of scope per PROJECT.md
- Image/media generation and attachment
- Embeddings-based clustering — deferred; upgrade path only if TF-IDF empirically fails on PT-BR headlines
- Auto-reply / DM handling
- Managed deploy (Kubernetes, ECS) — out of scope per PROJECT.md

## Out of Scope (v1 — won't build, with reasoning)

- Docker Secrets / HashiCorp Vault — `.env` + `env_file:` cover a single-operator VPS; justification in PROJECT.md
- Paid news sources or scraping sites without RSS/API — public structured feeds only; ToS and reliability concerns
- Dagster / Prefect / Airflow orchestration — 8-step function chain does not justify a DAG framework
- System cron inside the container — replaced by APScheduler (env stripping, log invisibility, PID 1 conflicts)
- supercronic — APScheduler already solves the problem without an extra non-Python binary
- Alpine base image — breaks scikit-learn / lxml wheels (musl vs glibc)

## Traceability

Each REQ-ID maps to exactly one phase. Coverage: 54 / 54.

| REQ-ID | Phase |
|--------|-------|
| INFRA-01 | Phase 1: Foundations |
| INFRA-02 | Phase 1: Foundations |
| INFRA-03 | Phase 1: Foundations |
| INFRA-04 | Phase 1: Foundations |
| INFRA-05 | Phase 1: Foundations |
| INFRA-06 | Phase 1: Foundations |
| INFRA-07 | Phase 1: Foundations |
| INFRA-08 | Phase 1: Foundations |
| INFRA-09 | Phase 1: Foundations |
| INFRA-10 | Phase 1: Foundations |
| STORE-01 | Phase 2: Storage Layer |
| STORE-02 | Phase 2: Storage Layer |
| STORE-03 | Phase 2: Storage Layer |
| STORE-04 | Phase 2: Storage Layer |
| STORE-05 | Phase 2: Storage Layer |
| STORE-06 | Phase 2: Storage Layer |
| GATE-01 | Phase 3: Validation Gate |
| GATE-02 | Phase 3: Validation Gate |
| GATE-03 | Phase 3: Validation Gate |
| GATE-04 | Phase 3: Validation Gate |
| INGEST-01 | Phase 4: Ingestion |
| INGEST-02 | Phase 4: Ingestion |
| INGEST-03 | Phase 4: Ingestion |
| INGEST-04 | Phase 4: Ingestion |
| INGEST-05 | Phase 4: Ingestion |
| INGEST-06 | Phase 4: Ingestion |
| INGEST-07 | Phase 4: Ingestion |
| CLUSTER-01 | Phase 5: Cluster + Rank |
| CLUSTER-02 | Phase 5: Cluster + Rank |
| CLUSTER-03 | Phase 5: Cluster + Rank |
| CLUSTER-04 | Phase 5: Cluster + Rank |
| CLUSTER-05 | Phase 5: Cluster + Rank |
| CLUSTER-06 | Phase 5: Cluster + Rank |
| CLUSTER-07 | Phase 5: Cluster + Rank |
| SYNTH-01 | Phase 6: Synthesis |
| SYNTH-02 | Phase 6: Synthesis |
| SYNTH-03 | Phase 6: Synthesis |
| SYNTH-04 | Phase 6: Synthesis |
| SYNTH-05 | Phase 6: Synthesis |
| SYNTH-06 | Phase 6: Synthesis |
| SYNTH-07 | Phase 6: Synthesis |
| PUBLISH-01 | Phase 7: Publish |
| PUBLISH-02 | Phase 7: Publish |
| PUBLISH-03 | Phase 7: Publish |
| PUBLISH-04 | Phase 7: Publish |
| PUBLISH-05 | Phase 7: Publish |
| PUBLISH-06 | Phase 7: Publish |
| OPS-01 | Phase 8: End-to-End + Hardening |
| OPS-02 | Phase 8: End-to-End + Hardening |
| OPS-03 | Phase 8: End-to-End + Hardening |
| OPS-04 | Phase 8: End-to-End + Hardening |
| OPS-05 | Phase 8: End-to-End + Hardening |
| OPS-06 | Phase 8: End-to-End + Hardening |

---
*v1 requirement count: 54 across 8 categories — 100% mapped*
