# Architecture Research

**Domain:** Automated tech-news curation + X auto-posting agent (batch pipeline, cron-driven)
**Researched:** 2026-04-12
**Confidence:** HIGH (standard ETL/pipeline patterns, well-established in Python ecosystem)

## Standard Architecture

### System Overview

```
┌────────────────────────────────────────────────────────────────────┐
│                     CONFIG / CONTROL LAYER                          │
│   ┌──────────────────┐   ┌──────────────────┐   ┌───────────────┐  │
│   │ sources.yaml     │   │ .env (secrets)   │   │ settings.py   │  │
│   │ (source registry)│   │ (X/Anthropic/DB) │   │ (tunables)    │  │
│   └──────────────────┘   └──────────────────┘   └───────────────┘  │
├────────────────────────────────────────────────────────────────────┤
│                   SCHEDULER (cron inside container)                 │
│                    ▼  every 2h → run_cycle()                        │
├────────────────────────────────────────────────────────────────────┤
│                      PIPELINE (function chain)                      │
│                                                                     │
│   ┌─────────┐   ┌──────────┐   ┌───────────┐   ┌────────┐          │
│   │ Fetcher │ → │Normalizer│ → │ Clusterer │ → │ Ranker │          │
│   │ (async) │   │          │   │ (TF-IDF)  │   │ (6h)   │          │
│   └────┬────┘   └────┬─────┘   └─────┬─────┘   └───┬────┘          │
│        │             │               │             │                │
│        ▼             ▼               ▼             ▼                │
│                                                  ┌───────────┐      │
│                                                  │Synthesizer│      │
│                                                  │(Claude H.)│      │
│                                                  └─────┬─────┘      │
│                                                        ▼            │
│                                                  ┌───────────┐      │
│                                                  │ Publisher │      │
│                                                  │ (tweepy)  │      │
│                                                  └─────┬─────┘      │
├────────────────────────────────────────────────────────┼────────────┤
│                     PERSISTENCE LAYER                  ▼            │
│   ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐    │
│   │articles │ │ clusters │ │  posts   │ │run_log │ │  sources │    │
│   │         │ │          │ │(history) │ │        │ │  (opt.)  │    │
│   └─────────┘ └──────────┘ └──────────┘ └────────┘ └──────────┘    │
│                         Postgres 16                                 │
├────────────────────────────────────────────────────────────────────┤
│                    OBSERVABILITY                                    │
│   structlog JSON → /var/log/app/*.jsonl (Docker volume)             │
└────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| **Config loader** | Load `sources.yaml` + env vars into typed settings | pydantic-settings + PyYAML |
| **Source registry** | List of sources with type (rss/json/api), URL, weight, enabled flag | YAML file mounted as volume |
| **Scheduler** | Trigger `run_cycle()` every N hours | cron inside container calling `python -m app.cycle` |
| **Fetcher** | Async HTTP fetch per source; isolate failures | httpx.AsyncClient + asyncio.gather(return_exceptions=True) |
| **Normalizer** | Parse RSS/JSON into unified Article dataclass; dedupe by URL/hash | feedparser + custom adapters per source_type |
| **Clusterer** | Group articles by title similarity (TF-IDF + cosine, threshold ~0.35) | sklearn TfidfVectorizer + AgglomerativeClustering |
| **Ranker** | Score clusters by coverage count × recency × source diversity; exclude themes posted in last 48h | Pure function over cluster list |
| **Synthesizer** | Call Claude Haiku with 3–5 articles from winning cluster; return PT post ≤ 280 chars | anthropic SDK, prompt template, char budget validator |
| **Publisher** | Post to X; return tweet_id or error | tweepy Client (OAuth 1.0a) |
| **Store** | Read/write Postgres; idempotency keys | SQLAlchemy 2.x + psycopg3 |
| **Run log** | Record cycle_id, phase timings, errors, chosen cluster, tweet_id | Single `run_log` table write per cycle |
| **Logger** | Structured JSON logs with cycle_id correlation | structlog |

## Recommended Project Structure

```
tech-news-synth/
├── app/
│   ├── __init__.py
│   ├── cycle.py                # Entry point: run_cycle() orchestrates pipeline
│   ├── config/
│   │   ├── settings.py         # pydantic-settings (env vars)
│   │   └── sources.py          # Load + validate sources.yaml
│   ├── fetch/
│   │   ├── base.py             # SourceAdapter protocol
│   │   ├── rss.py              # feedparser adapter
│   │   ├── hackernews.py       # Firebase API adapter
│   │   ├── reddit.py           # reddit.json adapter
│   │   └── runner.py           # async fetch-all with isolation
│   ├── normalize/
│   │   └── article.py          # Article dataclass + normalization
│   ├── cluster/
│   │   ├── vectorize.py        # TF-IDF over titles
│   │   └── group.py            # Cosine + agglomerative clustering (PURE)
│   ├── rank/
│   │   └── score.py            # Cluster scoring + 48h anti-repeat filter (PURE)
│   ├── synthesize/
│   │   ├── prompt.py           # Prompt template PT-BR jornalístico
│   │   ├── claude.py           # anthropic SDK wrapper
│   │   └── budget.py           # 280-char validator (URL 23 + hashtags)
│   ├── publish/
│   │   └── x_client.py         # tweepy wrapper + dry-run mode
│   ├── store/
│   │   ├── db.py               # engine, session factory
│   │   ├── models.py           # SQLAlchemy models
│   │   ├── repo_articles.py
│   │   ├── repo_clusters.py
│   │   ├── repo_posts.py
│   │   └── repo_runs.py
│   ├── observability/
│   │   └── logging.py          # structlog config
│   └── utils/
│       ├── hashing.py          # theme_hash, article_hash
│       └── text.py             # title cleanup, tokenization
├── migrations/                 # alembic
├── sources.yaml                # Source registry (mounted as volume)
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── crontab                     # `0 */2 * * * python -m app.cycle`
├── pyproject.toml
├── tests/
│   ├── unit/                   # Pure logic: cluster, rank, budget, hashing
│   ├── integration/            # DB-backed: repos, idempotency
│   └── fixtures/               # Sample RSS/JSON payloads
└── README.md
```

### Structure Rationale

- **`app/` vs `src/`:** flat `app/` package is idiomatic for small Python services; avoids `src-layout` overhead
- **Folder per pipeline stage:** mirrors the conceptual pipeline; each stage is independently testable
- **`store/` separated from domain:** repository pattern keeps domain logic (cluster/rank/synthesize) DB-agnostic
- **Pure functions in `cluster/` and `rank/`:** no I/O — trivially unit-testable with in-memory fixtures
- **Adapters in `fetch/`:** each source is a file implementing `SourceAdapter`; adding a new source is a single new file + YAML entry

## Architectural Patterns

### Pattern 1: Function Chain Pipeline (not Dagster/Prefect)

**What:** `run_cycle()` is a plain function calling stages in sequence, passing data as values.
**When to use:** Single-process batch jobs < 10 stages, no need for retries across process boundaries, no DAG branching.
**Trade-offs:**
- Plus: zero extra deps, trivial to debug, trivial to test (call `run_cycle(dry_run=True)`)
- Minus: no built-in retry/backoff (but at cycle granularity, cron handles this); no visual DAG UI

**Example:**
```python
def run_cycle(now: datetime, dry_run: bool = False) -> RunResult:
    cycle_id = uuid4()
    with log_context(cycle_id=cycle_id):
        sources = load_sources()
        raw = fetch_all(sources)              # async, failure-isolated
        articles = normalize(raw)
        store.save_articles(articles)         # idempotent upsert
        window = store.articles_in_window(hours=6)
        clusters = cluster_articles(window)   # pure
        winner = pick_winner(clusters, excluded=store.recent_themes(hours=48))  # pure
        if winner is None:
            return RunResult(status="no_content")
        post_text = synthesize(winner)
        tweet_id = publish(post_text, dry_run=dry_run)
        store.save_post(winner, post_text, tweet_id, cycle_id)
        return RunResult(status="posted", tweet_id=tweet_id)
```

Dagster/Prefect are overkill here — the cycle is a single deterministic line of ~10 calls, idempotency lives in the DB layer, and cron already supplies scheduling.

### Pattern 2: Failure Isolation at the Fetch Boundary

**What:** One bad source must not abort the cycle. Wrap each source fetch in try/except; continue with survivors.
**When to use:** Any pipeline with N independent upstream sources.
**Trade-offs:** Silent degradation is a risk → must log per-source failures with WARNING level and record `failed_sources` on `run_log`.

**Example:**
```python
async def fetch_all(sources: list[Source]) -> list[FetchResult]:
    results = await asyncio.gather(
        *[fetch_one(s) for s in sources if s.enabled],
        return_exceptions=True,
    )
    out = []
    for src, r in zip(sources, results):
        if isinstance(r, Exception):
            log.warning("source_failed", source=src.name, error=str(r))
            continue
        out.append(r)
    return out
```

### Pattern 3: Idempotency via Content Hash + Upsert

**What:** Every article has `article_hash = sha1(normalized_url)`; every theme has `theme_hash = sha1(top_tfidf_terms)`. Writes use `INSERT ... ON CONFLICT DO NOTHING`.
**When to use:** Any pipeline where reruns are possible (cron late, manual replay, container restart mid-cycle).
**Trade-offs:** Requires stable hashing — changing tokenization invalidates existing hashes.

The 48h anti-repetition check is a query: `SELECT 1 FROM posts WHERE theme_hash = ? AND posted_at > now() - interval '48 hours'`.

### Pattern 4: Pure Core, Impure Shell (Functional Core / Imperative Shell)

**What:** `cluster/`, `rank/`, `synthesize/budget.py` are pure: input dataclasses → output dataclasses, no I/O. I/O (DB, HTTP, LLM) lives only in `fetch/`, `publish/`, `store/`, `synthesize/claude.py`.
**When to use:** Anywhere testability matters. Clustering and ranking are the highest-risk correctness-wise — keep them pure.
**Trade-offs:** None meaningful at this scale.

### Pattern 5: Config as Code + Data (sources.yaml + settings.py)

**What:** Tunables (thresholds, windows, API keys) in env via pydantic-settings; source registry in YAML mounted as volume.
**When to use:** Default for any config-driven pipeline.

**sources.yaml format:**
```yaml
sources:
  - name: techcrunch
    type: rss
    url: https://techcrunch.com/feed/
    weight: 1.0
    enabled: true
  - name: hackernews
    type: hackernews_firebase
    url: https://hacker-news.firebaseio.com/v0
    weight: 1.2
    enabled: true
  - name: reddit_technology
    type: reddit_json
    url: https://www.reddit.com/r/technology/.json
    weight: 0.8
    enabled: true
```

YAML (not DB-backed) because: the operator edits it, it versions cleanly in git, no admin UI exists in v1, a redeploy is trivial.

## Data Flow

### Cycle Flow (happy path)

```
cron tick (every 2h)
   ↓
load sources.yaml + env
   ↓
fetch_all(sources)  ──[httpx async, 10s timeout each]──> raw payloads
   ↓                    (failed sources logged, skipped)
normalize()         ──> [Article(url, title, source, published_at, hash)]
   ↓
store.upsert_articles()  [ON CONFLICT (article_hash) DO NOTHING]
   ↓
store.fetch_window(6h)   ──> articles for clustering
   ↓
cluster_articles()  ──[TF-IDF over titles, cosine ≥ 0.65]──> [Cluster(articles, theme_hash)]
   ↓
pick_winner(clusters, excluded=recent_theme_hashes_48h)
   ↓                          (score = size × diversity × recency)
   ├─ winner found ──> synthesize(winner)
   │                       ↓ Claude Haiku: 3–5 articles → PT post
   │                       ↓ enforce_budget(text, url=23ch, hashtags=2)
   │                   publish(text)  [or dry_run]
   │                       ↓
   │                   store.save_post(theme_hash, tweet_id, cluster_id)
   │
   └─ no winner    ──> pick best-available cluster (cadence priority)
                       (same synthesize/publish path)
   ↓
store.save_run_log(cycle_id, phase_timings, errors, outcome)
```

### State Transitions

- **Article:** fetched → normalized → stored (one lifecycle per URL)
- **Cluster:** ephemeral in-cycle; persisted only if chosen (for post → cluster → articles lineage)
- **Post:** synthesized → published → stored (with tweet_id OR failure reason)
- **Run:** always persisted, even on full failure (for observability)

## DB Schema Sketch

```sql
-- Articles ingested from sources
CREATE TABLE articles (
  id              BIGSERIAL PRIMARY KEY,
  article_hash    TEXT NOT NULL UNIQUE,     -- sha1(normalized_url)
  url             TEXT NOT NULL,
  title           TEXT NOT NULL,
  source          TEXT NOT NULL,            -- matches sources.yaml name
  published_at    TIMESTAMPTZ,
  fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  raw             JSONB                     -- original payload for debugging
);
CREATE INDEX idx_articles_fetched ON articles(fetched_at DESC);
CREATE INDEX idx_articles_source_published ON articles(source, published_at DESC);

-- Clusters chosen (only winners persisted)
CREATE TABLE clusters (
  id              BIGSERIAL PRIMARY KEY,
  theme_hash      TEXT NOT NULL,            -- sha1(top-N TF-IDF terms, sorted)
  top_terms       TEXT[] NOT NULL,
  article_ids     BIGINT[] NOT NULL,        -- FK-ish to articles.id
  size            INT NOT NULL,
  score           REAL NOT NULL,
  cycle_id        UUID NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_clusters_theme_created ON clusters(theme_hash, created_at DESC);

-- Posts published (history + 48h anti-repeat source of truth)
CREATE TABLE posts (
  id              BIGSERIAL PRIMARY KEY,
  theme_hash      TEXT NOT NULL,
  cluster_id      BIGINT REFERENCES clusters(id),
  text            TEXT NOT NULL,
  primary_url     TEXT NOT NULL,
  tweet_id        TEXT,                     -- NULL if dry-run or publish failed
  status          TEXT NOT NULL,            -- 'posted' | 'failed' | 'dry_run'
  error           TEXT,
  cycle_id        UUID NOT NULL,
  posted_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_posts_theme_posted ON posts(theme_hash, posted_at DESC);
CREATE INDEX idx_posts_posted_at ON posts(posted_at DESC);

-- One row per cycle run (observability)
CREATE TABLE run_log (
  cycle_id            UUID PRIMARY KEY,
  started_at          TIMESTAMPTZ NOT NULL,
  finished_at         TIMESTAMPTZ,
  status              TEXT NOT NULL,        -- 'posted'|'no_content'|'failed'|'dry_run'
  articles_fetched    INT,
  articles_new        INT,
  clusters_found      INT,
  chosen_cluster_id   BIGINT,
  tweet_id            TEXT,
  failed_sources      TEXT[],
  phase_timings_ms    JSONB,                -- {"fetch": 1200, "cluster": 80, ...}
  error               TEXT
);
```

**Key design choices:**
- `article_hash UNIQUE` is the idempotency anchor for rerun-safe cycles
- `posts.theme_hash` indexed with `posted_at DESC` supports the hot 48h anti-repeat query
- `raw JSONB` on articles keeps original payloads for debugging / reclassification without re-fetching
- No separate `sources` table in v1 — `sources.yaml` is the registry; `articles.source` is a denormalized string reference

## Recommended Build Order

Infrastructure and boundaries first, then data, then logic, then I/O.

1. **Phase A — Foundations (infra + config)**
   - Dockerfile + docker-compose.yml (app + postgres + volumes)
   - `.env.example`, pydantic-settings loader
   - sources.yaml loader with schema validation
   - structlog config + cycle_id context
   - cron skeleton calling a no-op `run_cycle()` that writes one `run_log` row
   - **Gate:** `docker compose up` runs a cycle every 2h and persists a run_log entry

2. **Phase B — Storage layer**
   - Alembic + migrations for all 4 tables
   - SQLAlchemy models + repos (articles, clusters, posts, runs)
   - Idempotent upsert for articles
   - **Gate:** unit tests green for repos; reruns don't duplicate articles

3. **Phase C — Fetch + Normalize**
   - SourceAdapter protocol + RSS adapter first (TechCrunch, Verge, Ars)
   - HN + Reddit adapters
   - Async runner with per-source isolation
   - Normalization to Article dataclass
   - **Gate:** cycle populates `articles` table from all 5 sources; one source down ≠ cycle death

4. **Phase D — Cluster + Rank (pure logic, highest test coverage)**
   - TF-IDF vectorization over titles
   - Cosine-based clustering with threshold tuning on real fixtures
   - Ranker with 48h anti-repeat filter (reads `posts.theme_hash`)
   - **Gate:** given fixture articles, picks deterministic winner; excludes recent themes

5. **Phase E — Synthesize (LLM)**
   - Prompt template PT-BR jornalístico
   - anthropic SDK call with retries + timeout
   - Character-budget enforcer (280 − 23 URL − hashtag budget)
   - **Gate:** synthesize(winner) returns compliant text; costs logged

6. **Phase F — Publish**
   - tweepy client wrapper, OAuth 1.0a
   - `dry_run` mode (logs what it would post, writes `status='dry_run'`)
   - Error mapping → `posts.status='failed'` with reason
   - **Gate:** posting to a test account works; dry-run works end-to-end

7. **Phase G — End-to-end + hardening**
   - Wire full `run_cycle()`; run real cycles in dry-run first
   - Flip to live posting on @ByteRelevant
   - Operational runbook (logs, manual replay, enable/disable source)
   - **Gate:** 48h of unattended operation at 12 posts/day with zero theme repeats

## Scaling Considerations

This service is fundamentally small-scale (12 posts/day, ~5 sources, ~hundreds of articles/cycle). Real scaling concerns are minimal.

| Scale | Adjustments |
|-------|-------------|
| Current (5 sources, 12 posts/day) | Single container + single Postgres. Done. |
| 20+ sources | Still fine. Fetch is async; TF-IDF on a few thousand titles is milliseconds. |
| 100+ sources or sub-hour cadence | Move scheduler out of container to host cron or a proper scheduler; consider embeddings cache |
| Multi-account posting | Extract Publisher as a service with a queue (rq/Celery); add `account_id` to posts table |

### Likely First Bottleneck

Not compute — it's **X API rate limits** (Free tier ~17/day). Guardrail: publisher must check `posts` count in last 24h before posting and abort gracefully.

## Anti-Patterns

### Anti-Pattern 1: Orchestration framework for a 10-step linear pipeline

**What people do:** Reach for Dagster / Prefect / Airflow because "it's a pipeline."
**Why it's wrong:** Adds a server, a DB (or reuses yours), a UI, deployment complexity, and a learning curve — all to run one deterministic function every 2 hours.
**Instead:** Plain Python function chain. Re-evaluate only if you add: multiple DAGs, backfills, human-in-the-loop, or cross-service retries.

### Anti-Pattern 2: In-memory state between cycles

**What people do:** Cache clusters or "seen themes" in a Python set/dict in module globals.
**Why it's wrong:** Container restart = lost state = duplicate posts. Anti-repeat must be DB-backed.
**Instead:** Every anti-repeat / dedupe decision queries Postgres. No exceptions.

### Anti-Pattern 3: Mixing I/O into clustering/ranking

**What people do:** Clusterer queries the DB for articles itself, or writes clusters mid-loop.
**Why it's wrong:** Destroys testability; entangles retry semantics; makes the "winner picked" moment ambiguous.
**Instead:** Pure functions: `cluster(articles) -> [Cluster]`, `pick_winner(clusters, excluded) -> Cluster | None`. All I/O at the edges.

### Anti-Pattern 4: Source registry in the database

**What people do:** Put sources in a `sources` table with a CRUD admin UI.
**Why it's wrong:** There's no admin. The operator is the developer. YAML + git is simpler, versioned, and reviewable.
**Instead:** `sources.yaml` mounted as volume. Revisit only if non-devs need to manage sources.

### Anti-Pattern 5: One big transaction per cycle

**What people do:** Wrap the entire `run_cycle()` in a single DB transaction for "atomicity."
**Why it's wrong:** LLM calls and X posting are long and can fail partway. Long-held transactions block vacuum and other writers.
**Instead:** Short transactions per phase (upsert articles, save cluster, save post, save run_log). Use `run_log.status` + retries for recovery semantics.

### Anti-Pattern 6: Fetching all sources synchronously

**What people do:** Loop over sources with `requests.get`, one slow source stalls the cycle.
**Why it's wrong:** A single 30s RSS timeout blocks the whole pipeline.
**Instead:** `httpx.AsyncClient` + `asyncio.gather(..., return_exceptions=True)` with per-request timeout (e.g. 10s).

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| TechCrunch / Verge / Ars RSS | httpx GET → feedparser | Some feeds throttle aggressive polling; 2h is fine |
| Hacker News (Firebase) | httpx GET /topstories.json → fan-out /item/{id}.json (cap top 30) | No auth; watch for deleted/dead items |
| Reddit `.json` | httpx GET with custom User-Agent | 429 if UA is default/empty — set descriptive UA |
| Anthropic Claude Haiku | anthropic SDK | Set explicit timeout (30s); retry once on 429/5xx |
| X API v2 | tweepy Client, OAuth 1.0a User Context | Free tier: check rate limit headers; handle 403 duplicate content |
| Postgres 16 | psycopg3 via SQLAlchemy 2.x | Connection pool sized 2–5 (low concurrency) |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| fetch ↔ normalize | Function call, dataclasses | No shared state |
| normalize ↔ store | Repo function (upsert_articles) | Idempotent |
| store ↔ cluster | Repo returns `list[Article]` | Pure in, pure out |
| cluster ↔ rank | Pure data | Both pure, composable |
| rank ↔ synthesize | Pure data (chosen cluster) | Synthesizer does I/O internally |
| synthesize ↔ publish | String (post text) + primary URL | Budget check before publish |
| publish ↔ store | Repo (save_post) | Always write, success or failure |

## Sources

- Python batch-pipeline patterns (functional core / imperative shell): Gary Bernhardt's talks, widely applied in Python ETL systems — MEDIUM confidence (well-established idiom)
- SQLAlchemy 2.x repository pattern: official docs — HIGH
- pydantic-settings for 12-factor config: official docs — HIGH
- tweepy OAuth 1.0a User Context for posting: tweepy docs — HIGH
- structlog cycle-id context: structlog docs — HIGH
- Failure isolation via `asyncio.gather(return_exceptions=True)`: Python stdlib docs — HIGH
- "Don't use Airflow/Prefect for small pipelines" consensus: recurring advice across r/dataengineering and Python communities — MEDIUM

---
*Architecture research for: automated tech-news curation + X posting agent*
*Researched: 2026-04-12*
