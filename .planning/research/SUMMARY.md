# Project Research Summary

**Project:** tech-news-synth
**Domain:** Automated tech-news curation + NLP clustering + LLM synthesis + single-account X auto-posting (headless Python agent on Ubuntu VPS)
**Researched:** 2026-04-12
**Confidence:** HIGH

## Executive Summary

tech-news-synth is a small-scale, cron-driven batch pipeline: every 2 hours, fetch from ~5 public feeds (TechCrunch/Verge/Ars RSS + Hacker News Firebase + Reddit r/technology JSON), dedupe and cluster by title similarity, synthesize the best-covered topic into one PT-BR tweet via Claude Haiku 4.5, and post to @ByteRelevant — targeting 12 posts/day. The ecosystem has well-established patterns for each stage; the unusual combination is the *integration* of semantic clustering + LLM synthesis + 48h anti-repetition in a single headless agent, which most OSS `rss-to-twitter` bots lack.

The recommended approach is a **functional-core / imperative-shell** pipeline: pure functions for clustering/ranking/budget-validation, with I/O (DB, HTTP, LLM, X API) confined to the edges. Stack is Python 3.12 + Postgres 16 + Docker Compose, with `anthropic` SDK, `tweepy` v2 (OAuth 1.0a User Context), `scikit-learn` TF-IDF + cosine, `feedparser` + `httpx`, `SQLAlchemy 2.0` + `psycopg 3` + `alembic`, `APScheduler` as PID 1 inside the container, and `structlog` for JSON logs. Build order follows dependencies: infra → storage → fetch/normalize → cluster/rank → synthesize → publish → scheduler/hardening.

The dominant risks are **external and time-sensitive, not code-complexity**: (1) the X API Free tier was deprecated on 2026-02-06 — this project runs on pay-per-use and must guard quota/cost; (2) Claude Haiku 3 retires 2026-04-19 (one week from today) — the model id must be pinned to `claude-haiku-4-5`; (3) the 280-char X budget uses weighted character count and a fixed 23-char t.co URL allocation — naive `len()` and naive LLM length control both fail; (4) naive string hashing for the 48h anti-repeat window loses to paraphrase — must use centroid cosine similarity; (5) system cron inside a container strips env vars and swallows logs — APScheduler in-process is the only clean answer. All five of these converged independently across the three research threads, which is the strongest signal in this corpus.

## Key Findings

### Recommended Stack

Python 3.12 + Postgres 16 on Docker Compose, with `python:3.12-slim-bookworm` as the base image (Alpine breaks scikit-learn/lxml wheels). Dependency management via `uv`, lint/format via `ruff`, tests via `pytest` + `respx` + `time-machine`. Single-provider (Anthropic) for synthesis; no queue, no Celery, no orchestration framework — plain function chain.

**Core technologies:**
- **anthropic 0.79.x** (`claude-haiku-4-5`) — synthesis. Haiku 3 retires 2026-04-19; **must** pin Haiku 4.5 explicitly, never an alias.
- **tweepy 4.14.0** (`Client.create_tweet` v2, OAuth 1.0a User Context) — posting. Bearer-token flow cannot post; app permissions must be Read+Write *before* generating access tokens.
- **scikit-learn 1.8** (`TfidfVectorizer` + `cosine_similarity`) — clustering. Deterministic, free, CPU-only, appropriate for v1; embeddings deferred unless empirical quality fails.
- **feedparser 6.0.11 + httpx 0.28 + beautifulsoup4/lxml** — ingestion. `httpx` is already transitively pulled by `anthropic`; avoid mixing `requests`.
- **SQLAlchemy 2.0 + psycopg 3 + alembic 1.18** — persistence (modern typed stack; dialect URL `postgresql+psycopg://`).
- **APScheduler 3.10 `BlockingScheduler`** — in-process scheduler as PID 1. NOT system cron, NOT supercronic — three independent research threads converged on this.
- **pydantic 2.9 + pydantic-settings 2.6** — typed `.env` loading with fail-fast validation at boot.
- **structlog 25** — JSON logs to stdout + Docker volume, with `cycle_id` bound per cycle.
- **tenacity 9** — retry/backoff wrapper for every external call.

### Expected Features

**Must have (table stakes — missing any one produces outages, spam, or bans):**
- Configurable source list (YAML, not DB)
- Per-source fetch with retries + timeout + conditional GET (ETag / If-Modified-Since) + descriptive User-Agent
- TF-IDF clustering over a 6h rolling window with deterministic winner selection (distinct-source count → recency → weight)
- Fallback picker when no strong cluster (cadence priority: 12/day is non-negotiable)
- 48h **semantic** anti-repetition via cluster centroid cosine (≥0.5), not title hash
- 280-char budget enforcement using weighted char count (URL = 23, hashtags accounted), validated in Python after LLM output
- Idempotent posting: insert `posts` row with `status=pending` *before* `create_tweet`, update to `posted` with `tweet_id` on success (prevents double-post on retry)
- X 429 handling: respect `x-rate-limit-reset`, plus local daily cap guard (`MAX_POSTS_PER_DAY`)
- Structured JSON logs with `cycle_id` on every line
- Dry-run mode (`DRY_RUN=1`) from day one — integration testing without burning quota
- Kill switch (file flag or DB row) checked at cycle start
- Per-cycle graceful failure (never crash the scheduler; exit 0 with logged traceback)
- `.env` + `.dockerignore` hygiene; `.env.example` versioned; pre-commit secret scanning

**Should have (quality + operator leverage):**
- Cluster-selection audit trail ("why this topic won") persisted per cycle
- Replay from DB (`replay --cycle-id=X`) for offline prompt iteration
- Per-cycle summary log line (cluster counts, char budget, token cost)
- Source-health tracking (consecutive failures → auto-disable at N)
- Manual post-override CLI (`post-now`) that respects all guardrails
- Curated hashtag allowlist (denylist for spammy/cringe tags)
- Haiku token-cost logging per call

**Defer (v2+):**
- Multi-account / cross-posting (LinkedIn, Mastodon, second handle)
- Threads (multi-tweet chains)
- Web UI / dashboard
- Active alerts (Discord/Telegram/Sentry) — logs + optional daily grep cron are sufficient
- Language detection / multilingual output
- Image/media generation
- Embeddings-based clustering (only if TF-IDF empirically fails)

### Architecture Approach

Batch pipeline driven by APScheduler in-process, structured as a **function chain** (not Dagster/Prefect/Airflow — overkill for ~10 sequential calls). **Functional core / imperative shell** is the dominant pattern: `cluster/`, `rank/`, `synthesize/budget.py` are pure functions over dataclasses; all I/O (HTTP, DB, LLM, X) is confined to `fetch/`, `store/`, `publish/`, and `synthesize/claude.py`. Idempotency is achieved at the DB layer via `article_hash UNIQUE` upserts and intent-row pattern for posts.

**Major components:**
1. **Scheduler** (APScheduler BlockingScheduler, PID 1, UTC timezone) — triggers `run_cycle(cycle_id)` every 2h.
2. **Fetcher** (`httpx.AsyncClient` + `asyncio.gather(return_exceptions=True)`) — per-source failure isolation; one bad feed never aborts the cycle.
3. **Normalizer** — maps per-source payloads to a unified `Article` dataclass; computes `article_hash = sha1(canonicalized_url)`.
4. **Clusterer + Ranker** (pure) — TF-IDF (char n-grams `(3,5)` for PT morphology tolerance) + cosine + agglomerative threshold; ranks by coverage × diversity × recency; filters against last-48h centroids.
5. **Synthesizer** — Claude Haiku 4.5 with grounded PT-BR prompt (titles + short descriptions only, never full bodies); `max_tokens=150`; enforced budget = `280 − 23 (t.co) − hashtag_budget ≈ 230 chars`; retry up to 2× with "shorten to N" re-prompt before last-resort whitespace truncation.
6. **Publisher** — `tweepy.Client.create_tweet`, OAuth 1.0a User Context; 429 respects `x-rate-limit-reset`; dry-run short-circuits here.
7. **Store** (SQLAlchemy 2.0 + psycopg 3) — tables: `articles`, `clusters`, `posts`, `run_log`. All timestamps `TIMESTAMPTZ`; all Python datetimes `datetime.now(timezone.utc)`. Short transactions per phase, never one big cycle-wide transaction.
8. **Observability** — structlog JSON → Docker volume; `cycle_id` bound via context; one `cycle_summary` line per run.

### Critical Pitfalls

1. **X Free Tier gone (2026-02-06) → pay-per-use only.** Decision recorded in PROJECT.md: accept pay-per-use at ~$20–50/mo, validate actual cost/permission in a pre-implementation gate (smoke-test `client.get_me()` + one real post). Implement hard daily/monthly caps as env-var kill switches.
2. **Claude Haiku 3 retires 2026-04-19 (7 days from this research).** Pin `claude-haiku-4-5` explicitly; never use short aliases like `claude-haiku`.
3. **280-char compliance must be validated in Python, not trusted to the LLM.** Use weighted char count (`len(text.encode('utf-16-le')) // 2` as conservative proxy, or `twitter-text` library); reserve 23 for t.co + hashtag budget; max 2 re-prompt retries; last-resort truncate on whitespace with "…".
4. **48h anti-repetition by centroid cosine similarity, not title hash.** Store top-K TF-IDF terms or pickled centroid per `posts` row; query last 48h and reject if cosine ≥ 0.5. Title hashing loses to paraphrase.
5. **UTC everywhere.** `TIMESTAMPTZ` in Postgres, `datetime.now(timezone.utc)` in Python, APScheduler `timezone=pytz.UTC`. Never set `TZ=` on containers. Convert `feedparser.published_parsed` (naive UTC struct_time) to aware UTC explicitly.
6. **APScheduler, never system cron inside the container.** Cron strips env vars (your `.env` secrets are invisible), swallows stdout (your structured logs vanish), and PID 1 semantics conflict. APScheduler = one process, one container, env inherited, logs native.
7. **tweepy 403 on posting = OAuth or permissions issue.** Must be OAuth 1.0a User Context (4 secrets). App permissions must be Read+Write **before** generating access tokens; if toggled after, regenerate. Add a boot-time `get_me()` smoke test.
8. **LLM hallucination grounding.** PT-BR prompt must explicitly say "use APENAS informações das manchetes/resumos fornecidos; NÃO invente datas, nomes, citações; mantenha nomes próprios intactos (ex: 'Vision Pro' não traduz)". First week in dry-run with human review.
9. **Feed robustness.** One malformed feed must never kill the cycle: isolated try/except per source; check `feedparser` `bozo`; defensive `.get()` on entry fields; fetch via `httpx` with timeout, pass bytes to `feedparser.parse()`.
10. **Reddit JSON requires descriptive User-Agent** (`ByteRelevant/0.1 (+https://x.com/ByteRelevant)`). Default `python-requests/*` UA gets 429/403 instantly.
11. **Secrets hygiene.** `.gitignore` + `.dockerignore` both include `.env`; `env_file:` in compose reads at runtime (never baked into image); pre-commit hook (gitleaks/detect-secrets).
12. **Anthropic input budget.** Never feed full article bodies; only titles + short descriptions (≤500 chars each × 3). Set `max_tokens=150`. Log tokens/cost per call.

## Implications for Roadmap

Based on research, build order is constrained by dependencies: **infrastructure → storage → ingestion → pure logic (cluster/rank) → LLM → X publisher → end-to-end scheduler wiring + hardening**. Each phase produces a gate that validates the previous layer before adding more surface area.

### Phase 1: Foundations (Docker + Config + Observability + Scheduler Skeleton)
**Rationale:** Everything else depends on a running container with validated secrets, structured logs, and a scheduler. Secrets hygiene and UTC-everywhere must be established as invariants on day one, not retrofitted.
**Delivers:** `docker compose up` runs an app container with Postgres, APScheduler triggers a no-op `run_cycle()` every 2h that writes a `run_log` row; JSON logs visible in Docker volume; `.env` + `.env.example` + `.dockerignore` + `.gitignore` + pre-commit secret scan wired.
**Addresses (features):** Configurable source list scaffolding (YAML loader), `.env` fail-fast validation, kill switch, dry-run flag plumbing, structured JSON logs with `cycle_id`.
**Avoids (pitfalls):** #5 UTC-everywhere, #6 APScheduler-not-cron, #11 secrets hygiene, secret leak to image layer.

### Phase 2: Storage Layer
**Rationale:** Persistence is the spine of every downstream feature (dedup, 48h window, audit, replay, daily cap). Schema + migrations must be stable before any domain logic writes through them.
**Delivers:** Alembic + 4 tables (`articles`, `clusters`, `posts`, `run_log`) with all indexes; SQLAlchemy models + repos; idempotent upsert for articles; unit tests proving reruns don't duplicate.
**Uses:** SQLAlchemy 2.0 + psycopg 3 + alembic; `TIMESTAMPTZ` exclusively.
**Implements:** Store component; intent-row pattern for posts (`status` column: pending/posted/failed/dry_run).
**Avoids (pitfalls):** #4 semantic dedup needs `theme_terms`/centroid columns from the start; #5 UTC storage; in-memory state anti-pattern.

### Phase 3: Pre-Implementation Validation Gate
**Rationale:** Per PROJECT.md, a gate confirms X pay-per-use reality (quota, cost per post, OAuth flow) **before** building the full pipeline. Deferring this risks building on a broken economic assumption.
**Delivers:** Dev X account smoke test: `client.get_me()` works, one real `create_tweet` succeeds, actual cost per post and daily cap documented. Haiku 4.5 access confirmed via a minimal synthesis call.
**Addresses:** Economic validation, OAuth 1.0a Read+Write permissions, token regeneration if needed.
**Avoids (pitfalls):** #1 X Free Tier dead reality check, #2 OAuth 403 discovery late in the build.

### Phase 4: Ingestion (Fetch + Normalize)
**Rationale:** Pure I/O layer; produces the `Article` stream that all downstream logic consumes. Must be robust to feed failures from day one.
**Delivers:** `SourceAdapter` protocol + RSS adapter (TechCrunch/Verge/Ars) + HN Firebase + Reddit JSON; async runner with per-source isolation; conditional GET (ETag/Last-Modified); descriptive UA; upserts to `articles`.
**Uses:** `feedparser`, `httpx.AsyncClient`, `beautifulsoup4` for HTML stripping, `tenacity` for retries.
**Avoids (pitfalls):** #9 feedparser bozo, #10 Reddit UA, synchronous-fetch performance trap, one-bad-feed-kills-cycle.

### Phase 5: Cluster + Rank (Pure Core)
**Rationale:** Highest correctness risk and highest testability leverage. Pure functions enable fixture-based regression tests. Clustering quality is a measurable metric, not vibes.
**Delivers:** TF-IDF (char n-grams 3–5) + cosine + agglomerative clustering; ranker with 48h centroid anti-repeat filter; deterministic winner selection; fallback picker for slow news days; labeled fixture set of ~50 headline pairs to tune thresholds.
**Uses:** scikit-learn 1.8, unidecode, PT stopwords.
**Avoids (pitfalls):** #3 TF-IDF short-text failures, #4 semantic-not-lexical anti-repeat, mixing I/O into pure logic anti-pattern.

### Phase 6: Synthesize (Claude Haiku 4.5)
**Rationale:** Once clusters + winners are stable, the LLM can be layered in. Quality and cost invariants established here.
**Delivers:** Prompt template (PT-BR jornalístico neutro, grounded, nomes próprios intactos); `anthropic` SDK wrapper with retries + timeout; weighted-char budget enforcer; token/cost logging; first week runs in `DRY_RUN=1` for human review.
**Uses:** `anthropic 0.79.x`, pinned `claude-haiku-4-5`, `max_tokens=150`.
**Avoids (pitfalls):** #2 Haiku 3 retirement, #3 char-limit compliance, #8 hallucination grounding, #12 input-budget explosion.

### Phase 7: Publish (X API)
**Rationale:** Last I/O edge. Idempotency pattern from storage layer is consumed here; daily cap and rate-limit handling applied at the boundary.
**Delivers:** `tweepy.Client.create_tweet` wrapper; intent-row pattern (pending → posted); 429 `x-rate-limit-reset` respect; local daily cap guard; dry-run short-circuit; attribution invariant (source link always present).
**Uses:** `tweepy 4.14.0`, OAuth 1.0a User Context.
**Avoids (pitfalls):** #1 daily cap guard, #2 OAuth validated in Phase 3, double-post on retry (idempotency), legal/ToS attribution.

### Phase 8: End-to-End + Hardening
**Rationale:** Wire the full `run_cycle()`; run dry for 48h; flip to live; add operator tools.
**Delivers:** Full pipeline live on @ByteRelevant with 48h zero-repeat verified; operational runbook (log grep patterns, pause file, replay, manual post-override); per-cycle `cycle_summary` metrics line; source-health auto-disable.
**Avoids (pitfalls):** Silent degradation (source-health), unrecoverable state (replay + kill switch).

### Phase Ordering Rationale

- **Infra and storage before domain logic** because every feature reads/writes through the same tables; schema instability propagates.
- **Validation gate (Phase 3) between storage and ingestion** because X pay-per-use + OAuth could invalidate the project economics; fail fast.
- **Ingestion before clustering** because clustering needs real fixture data from live feeds to tune thresholds empirically.
- **Cluster/rank before synthesis** because the LLM consumes cluster outputs; debugging a bad post starts with "did we pick the right cluster?" — that answer needs to be trusted first.
- **Synthesis before publish** because dry-run mode is the safety net, and dry-run tests synthesis end-to-end without touching X.
- **Publish last** because it's the only truly irreversible side effect.

### Research Flags

Phases likely needing deeper research during planning (`/gsd-research-phase`):
- **Phase 5 (Cluster + Rank):** TF-IDF threshold tuning for short PT-BR headlines is empirical; char n-grams vs. word n-grams vs. stemming tradeoffs; acceptance criteria (precision/recall on labeled pairs) need definition.
- **Phase 6 (Synthesize):** PT-BR prompt engineering for grounding + tone + char budget; retry/truncation policy edge cases; cost/latency benchmarks per cluster size.
- **Phase 7 (Publish):** X pay-per-use cost modeling once Phase 3 reveals actual per-post pricing; daily-cap self-throttle policy (skip cycle vs. defer to next); 429 replay behavior.

Phases with standard patterns (skip dedicated research):
- **Phase 1 (Foundations):** Dockerfile + compose + pydantic-settings + structlog are well-documented; follow STACK.md directly.
- **Phase 2 (Storage):** SQLAlchemy 2.0 + alembic + psycopg 3 is canonical; schema is already sketched in ARCHITECTURE.md.
- **Phase 4 (Ingestion):** feedparser + httpx + async-gather isolation is the textbook pattern; adapters are mechanical.
- **Phase 8 (Hardening):** Observability and runbook patterns are standard.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified against official PyPI / docs as of 2026-04-12; three research threads converged on APScheduler, TF-IDF, and Haiku 4.5. |
| Features | HIGH | PROJECT.md constraints well-scoped; ecosystem patterns (conditional GET, idempotent posting, dry-run) verified across multiple sources. |
| Architecture | HIGH | Function-chain + functional-core/imperative-shell is a well-established Python batch-pipeline idiom; DB schema is straightforward. |
| Pitfalls | HIGH (X/Docker/Postgres/feedparser specifics) / MEDIUM (TF-IDF short-text quality, LLM length control) | The empirical pitfalls (clustering threshold, LLM compliance rate) have no silver bullet — must validate in Phase 5/6. |

**Overall confidence:** HIGH.

### Gaps to Address

- **X pay-per-use actual cost/day and hard cap** — resolved in Phase 3 validation gate, not estimable from research alone.
- **TF-IDF clustering threshold and n-gram configuration for PT-BR tech headlines** — needs labeled fixture set of ~50 pairs built during Phase 5; treat clustering quality as a measurable metric.
- **Haiku 4.5 PT-BR char-budget compliance rate** — measure during Phase 6 dry-run week; if retries exceed 10% of cycles, prompt needs hardening or fallback policy revision.
- **Centroid storage format** (pickled `BYTEA` vs. top-K terms `TEXT[]` vs. both) — decide during Phase 2 schema; research shows both work, no strong preference.
- **Source-health auto-disable threshold** (3 warnings / 20 disable) — starting heuristic, tune during Phase 8 based on real feed behavior.

## Sources

### Primary (HIGH confidence)
- Anthropic SDK (GitHub + PyPI + platform docs) — Haiku 3 deprecation 2026-04-19, Haiku 4.5 model id, SDK 0.79.x features
- tweepy 4.14.0 docs (Client, Authentication) — OAuth 1.0a User Context for `create_tweet`
- scikit-learn 1.8 docs — `TfidfVectorizer`, `cosine_similarity`, char n-grams
- feedparser (kurtmckee GitHub + readthedocs) — bozo handling, `published_parsed` semantics, conditional GET
- SQLAlchemy 2.1 + psycopg 3 + alembic 1.18 official docs — dialect URL, typed Mapped API, migrations
- X API docs (rate limits, pay-per-use pricing 2026)
- APScheduler + BetterStack guide — in-process scheduling, CronTrigger DST behavior
- pythonspeed — slim-bookworm vs. alpine for Python wheels
- structlog performance docs — orjson renderer, context binding
- PROJECT.md (binding constraints)

### Secondary (MEDIUM confidence)
- Community posts on X Free Tier deprecation (Feb 2026) — corroborating cost figures
- Tweepy 429 handling GitHub discussions
- Simon Willison TIL on Reddit JSON scraping
- Najkov (Medium) + Feedly engineering — news clustering patterns
- httpx vs requests comparison (Decodo, 2026) — adoption by anthropic/openai SDKs

### Tertiary (LOW confidence — validate in phases)
- arxiv 2508.13805 on LLM length-controlled generation — informs retry strategy, needs empirical validation
- Per-source weight heuristics — operator-tunable, no external source

---
*Research completed: 2026-04-12*
*Ready for roadmap: yes*
