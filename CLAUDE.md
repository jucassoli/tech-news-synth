<!-- GSD:project-start source:PROJECT.md -->
## Project

**tech-news-synth**

Agente Python automatizado que, a cada 2 horas, coleta notícias de tecnologia de múltiplas fontes públicas (RSS e APIs), agrupa notícias relacionadas por similaridade de título, sintetiza o tema de maior cobertura via Claude Haiku 4.5 em um post único em português, e publica no X na conta **@ByteRelevant**. Volume-alvo: ~12 posts/dia, operando em **tier pay-per-use** da API do X (Free tier antigo foi descontinuado em 2026-02-06 para contas novas).

**Core Value:** Transformar ruído de feeds de tecnologia em **um post por ciclo que destaca o tema com mais cobertura e o ângulo único de cada fonte** — sem repetir o mesmo assunto em 48h.

### Constraints

- **Tech stack:** Python 3.12, scikit-learn (TF-IDF/cosine), feedparser, `anthropic` SDK, tweepy v2, psycopg 3 + SQLAlchemy 2.0 + alembic, Postgres 16, APScheduler, structlog, pydantic-settings, httpx, ruff, pytest
- **Infra:** Docker Compose (base `python:3.12-slim-bookworm`), execução em VPS Ubuntu, APScheduler em-processo (PID 1) no container app
- **API X:** tier pay-per-use (posting pago) — meta 12/dia; gate de validação inicial confirma cap e custo real
- **Limite de post:** 280 chars totais (weighted char count), incluindo URL encurtada t.co (~23 chars) e hashtags
- **Janela anti-repetição:** 48h em Postgres — **por similaridade cosseno de centroide de cluster**, não hash de string (paraphrase-safe)
- **Janela de cluster:** 6h de histórico ao montar clusters (configurável)
- **Idioma de saída:** PT-BR, tom jornalístico neutro; grounding obrigatório (não inventar stats/citações)
- **Timezone:** UTC everywhere (`TIMESTAMPTZ` em Postgres, `datetime.now(timezone.utc)` em Python)
- **Secrets:** `.env` local, `.env.example` versionado, `.env` em `.gitignore`; pre-commit hook para detectar vazamento
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Recommended Stack
### Core Technologies
| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Python** | 3.11.x or 3.12.x (pin to 3.12) | Runtime | 3.11+ required by project; 3.12 has mature wheels for scikit-learn, psycopg, pydantic v2; 3.13 still maturing some C-extension wheels. Avoid 3.14 in v1 (too fresh for all deps). |
| **PostgreSQL** | 16 (Debian-based official image) | Persistence of post history, anti-repetition window, cluster hashes | Project constraint. 16 is current LTS line, stable, wide tooling. `postgres:16-bookworm` image. |
| **Docker / Compose** | Docker Engine 26+, Compose v2 (plugin) | Orchestration of app + postgres | Constraint from project. Use `compose.yaml` (v2 spec), `depends_on: condition: service_healthy`, named volumes. |
| **anthropic** (Python SDK) | 0.79.x (≥0.49 minimum) | Claude Haiku 4.5 synthesis in PT-BR | Official SDK. **Use `claude-haiku-4-5` model id.** Claude Haiku 3/3.5 deprecated (Haiku 3 retires 2026-04-19). SDK uses httpx internally for sync + async. HIGH confidence. |
| **tweepy** | 4.14.0 | X API v2 posting (`client.create_tweet`) via OAuth 1.0a User Context | De-facto Python client for X. `tweepy.Client` (v2) supports OAuth 1.0a User Context required for write endpoints on Free tier. HIGH confidence. |
| **scikit-learn** | 1.8.x | `TfidfVectorizer` + `cosine_similarity` for title clustering | Project constraint; 1.8.0 is current stable. Deterministic, no external API, CPU-only, fast on <10k docs. HIGH confidence. |
| **feedparser** | 6.0.11 | RSS/Atom parsing (TechCrunch, Verge, Ars Technica) | Gold standard for 15+ years; handles malformed feeds gracefully. Performance irrelevant at 5-10 feeds / 2h cycle. Active maintenance (kurtmckee fork). |
| **httpx** | 0.28.x | HTTP client for Hacker News Firebase API, Reddit JSON, arbitrary sources | Already a transitive dep of `anthropic`. Unified sync+async API, HTTP/2, timeouts/retries first-class. One fewer library than adding `requests`. |
| **SQLAlchemy** | 2.0.x (≥2.0.40) | ORM / Core for posts, clusters, sources tables | Modern typed API (`Mapped[...]`), async-capable, works with psycopg3. 2.0 is the current line; 2.1 coming but not required. |
| **psycopg** (psycopg3) | 3.2.x | Postgres driver | Modern successor; same-team as psycopg2; native async; `postgresql+psycopg://` dialect in SQLAlchemy 2.0. Preferred over psycopg2-binary for new projects. |
| **alembic** | 1.18.x (≥1.18.0, Jan 2026) | Schema migrations | Canonical SQLAlchemy migration tool. 1.18 adds bulk reflection for Postgres (faster autogenerate). |
| **pydantic** | 2.9.x | Config validation (settings from env), source definitions, tweet payload schemas | Industry standard; pydantic-settings handles `.env` + env var loading with typed fields. |
| **pydantic-settings** | 2.6.x | `.env` loading + typed `Settings` class | First-party pydantic extension; replaces `python-dotenv` for structured config. Still allows `.env` file. |
| **structlog** | 25.x | Structured JSON logs to stdout + file (Docker volume) | Purpose-built for structured/JSON. Orjson renderer is fast. Integrates with stdlib `logging`. Explicit context binding (source, cluster_id, post_id) beats Loguru's string-first approach for this use case. |
| **APScheduler** | 3.10.x (stable; avoid 4.x pre-release) | In-process cron scheduler ("every 2h") inside the container | Keeps scheduler + job in one Python process → easy logging, exception handling, shared DB pool. System `cron` inside a container is an anti-pattern (no stdout capture, no shared env, PID 1 issues). APScheduler 4 is still pre-release — stick with 3.10 `BlockingScheduler` + `CronTrigger`. |
### Supporting Libraries
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **tenacity** | 9.x | Retry w/ exponential backoff for Anthropic + X + feed fetches | Wrap every external call. Handles `anthropic.APIStatusError`, `tweepy.TooManyRequests`, `httpx.HTTPError`. |
| **beautifulsoup4** + **lxml** | bs4 4.12.x, lxml 5.x | Strip HTML from RSS `<description>` / `content:encoded` before feeding to LLM | feedparser returns raw HTML in many fields; BS4 + `get_text(" ", strip=True)` cleans it. lxml as fast parser backend. |
| **orjson** | 3.10.x | Fast JSON for structlog renderer + Reddit/HN response parsing | Drop-in faster than stdlib `json`. structlog integrates natively. |
| **python-slugify** | 8.x | Normalize cluster topic → anti-repetition hash key | Stable PT-BR handling (accents → ASCII), deterministic. |
| **unidecode** | 1.3.x | ASCII-fold PT text before TF-IDF vectorization | Improves cluster quality across sources that mix acentuação inconsistently. |
| **httpx[http2]** | (same 0.28.x) | HTTP/2 extra for faster multiplexed fetches | Optional — enable if fetch latency matters. |
### Development Tools
| Tool | Purpose | Notes |
|------|---------|-------|
| **uv** (Astral, 0.5.x+) | Dependency resolver + virtualenv + lockfile | 10-100× faster than pip; single binary; use `uv pip compile` → `requirements.txt` or full `pyproject.toml` + `uv.lock`. Recommended in Dockerfile multi-stage build. |
| **ruff** | Linter + formatter (replaces black, flake8, isort, pyupgrade) | v0.8+; configure in `pyproject.toml` under `[tool.ruff]`. One tool, one config. |
| **pytest** 8.x | Test runner | Standard. Use `pytest-asyncio` if any async test needed (likely minimal in v1). |
| **pytest-mock** | `mocker` fixture | Cleaner than `unittest.mock.patch` decorators for mocking Anthropic + tweepy clients. |
| **respx** | Mock httpx calls in tests | Purpose-built for httpx (feedparser fetches, HN/Reddit calls). |
| **freezegun** or **time-machine** | Freeze time in tests (6h cluster window, 48h anti-repeat) | `time-machine` is faster/more correct; use it. |
| **pytest-cov** | Coverage reporting | Target ≥80% on clustering + synthesis + publishing modules. |
| **mypy** (optional v1, recommended v2) | Static typing | Add post-MVP; pydantic v2 already gives runtime validation. |
## Installation
# --- build stage ---
# --- runtime stage ---
## Alternatives Considered
| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| **scikit-learn TF-IDF + cosine** | `sentence-transformers` embeddings + FAISS | If cross-lingual clustering or semantic nuance matters more than speed/simplicity. Not needed here — titles are short English/PT tech headlines; TF-IDF handles them fine and is free. |
| **scikit-learn TF-IDF + cosine** | OpenAI/Voyage/Cohere embeddings API | Only if you need multilingual semantic clustering. Adds cost, latency, and a second API key. Overkill for 5-10 sources × 2h cycle. |
| **Claude Haiku 4.5** | Claude Sonnet 4.5 / Opus 4.5 | If synthesis quality at 280 chars is insufficient after prompt iteration. Haiku is ~10× cheaper and fast enough; reserve Sonnet only if A/B tests show quality gap. |
| **Claude Haiku 4.5** | GPT-4.1-mini / Gemini Flash | If you need multi-provider fallback. Single provider is simpler for v1. |
| **APScheduler (in-process)** | System cron + separate one-shot container | Valid if the scheduler process itself is unreliable or if you want jobs fully decoupled. In-process is simpler for a single-tenant agent. |
| **APScheduler (in-process)** | Celery beat + worker + Redis | Overkill. You have 12 jobs/day, single-node; Celery adds 2 services and no benefit. |
| **psycopg3** | psycopg2-binary | If a critical lib pins psycopg2 (rare in 2026). SQLAlchemy works with both. |
| **httpx** | requests | If every call is sync + simple and you want the broadest ecosystem. `anthropic` already pulls httpx, so adding requests just duplicates. |
| **structlog** | loguru | If DX/ergonomics matter more than strict structured context. Loguru is nicer locally but weaker for production JSON pipelines. |
| **feedparser** | fastfeedparser | If parsing 1000s of feeds/minute. Not your bottleneck — LLM call dominates latency. |
| **uv** | pip + pip-tools | If corporate policy forbids new tooling. uv is already pip-compatible; no downside for a solo project. |
## What NOT to Use
| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **`claude-3-haiku-20240307`** | Retires 2026-04-19 (one week after this research). Hard-coding it in v1 = immediate breakage. | `claude-haiku-4-5` (latest Haiku). |
| **`anthropic` SDK <0.49** | Older SDKs predate Haiku 4.5 model IDs, structured outputs, and current retry/streaming API. | anthropic 0.79.x. |
| **python-dotenv alone** | Loads env but does not validate or type-convert. Easy to ship broken config. | `pydantic-settings` (still reads `.env`, adds typed validation). |
| **System `cron` inside app container** | No stdout capture (breaks JSON log pipeline), needs second process manager, PID 1 reaping issues, env-var propagation pain. | `APScheduler` BlockingScheduler as PID 1 in the container. |
| **Alpine base image (`python:3.12-alpine`)** | musl libc → no manylinux wheels for scikit-learn/lxml/psycopg → compiles from source → 10-50× slower builds, larger final images. | `python:3.12-slim-bookworm`. |
| **`requests` + `aiohttp` mixed** | Two HTTP stacks, two retry strategies, two timeout configs. | `httpx` only (sync or async as needed). |
| **Embedding-based clustering (v1)** | Adds API cost, latency, and a vector store. Titles are short and lexically overlapping — TF-IDF is sufficient and deterministic. | scikit-learn TF-IDF + cosine_similarity; revisit only if cluster quality is provably bad. |
| **`schedule` library** | Doesn't persist jobs, no cron syntax, no timezone handling, abandoned-ish. | APScheduler. |
| **`tweepy.API` (v1.1)** | v1.1 endpoints are deprecated/paywalled for posting on Free tier. | `tweepy.Client.create_tweet` (v2) with OAuth 1.0a User Context. |
| **Docker secrets / Vault** | Explicitly out of scope per PROJECT.md. | `.env` + `env_file:` in compose, `.env` in `.gitignore`, `.env.example` versioned. |
| **black + flake8 + isort separately** | 3 tools, 3 configs, 10-100× slower than ruff. | `ruff check` + `ruff format`. |
| **psycopg2-binary for new code** | Sync-only, slower memory profile, older codebase. | `psycopg[binary,pool]` (v3). |
| **Storing API keys in Python constants** | Trivial leak vector. | `pydantic-settings` reading from env, never logged. Use `SecretStr`. |
## Stack Patterns by Variant
- Wrap `client.create_tweet` with `tenacity.retry(retry=retry_if_exception_type(tweepy.TooManyRequests), wait=wait_exponential(min=60, max=900), stop=stop_after_attempt(3))`.
- On `TooManyRequests`, read `x-rate-limit-reset` header and sleep until then. Tweepy exposes this via `e.response.headers`.
- Budget: `280 − 23 (t.co URL) − len(hashtags + spaces) = ~240 chars` for the synthesis body.
- Instruct Haiku via system prompt with a hard char budget **and** validate post-generation with `len(text) <= 280`. Retry with a "shorten to N chars" follow-up prompt if over.
- Never trust the model to count — always validate in Python.
- Generate `consumer_key`, `consumer_secret`, `access_token`, `access_token_secret` in the X Developer Portal for @ByteRelevant.
- App must have **Read and Write** permission BEFORE generating access tokens (regenerate if permission was toggled after).
- Store all four in `.env`; load via `pydantic-settings`.
- After selecting winning cluster, compute `hashlib.sha1(slugify(canonical_title, lowercase=True, separator="-"))` → store in `posts.topic_hash`.
- Before publishing, query `SELECT 1 FROM posts WHERE topic_hash = :h AND posted_at > NOW() - INTERVAL '48 hours'`.
- Move Anthropic calls to async (`anthropic.AsyncAnthropic`) + `asyncio.gather` for parallel source fetches.
- Consider embeddings for dedup quality.
- structlog → OpenTelemetry exporter is a config swap, not a rewrite. Choose structlog now to keep that door open.
## Version Compatibility
| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `SQLAlchemy 2.0.40+` | `psycopg 3.2.x` | Dialect URL: `postgresql+psycopg://user:pw@db:5432/dbname`. Do NOT use `postgresql+psycopg2://` if you install psycopg3 only. |
| `alembic 1.18` | `SQLAlchemy 2.0.x` and `2.1.x` | For SQLAlchemy 2.1, set `isolate_from_table=True` in env.py. For 2.0, no action needed. |
| `anthropic 0.79` | `httpx 0.28.x` | anthropic pins a compatible httpx range; pin your own `httpx` within that range to avoid resolver churn. |
| `tweepy 4.14` | `requests 2.32+` (transitive) | tweepy still uses `requests` internally for v2 client — that's fine; you don't import it directly. |
| `pydantic 2.9` | `pydantic-settings 2.6` | Both pydantic v2 line. Do not mix pydantic v1. |
| `scikit-learn 1.8` | `numpy 2.x`, `scipy 1.13+` | 1.8 supports NumPy 2; no action needed if installing fresh. |
| `Python 3.12` | All above | 3.13 mostly fine too, but 3.12 has the broadest wheel coverage in April 2026. |
| `Postgres 16` | `psycopg 3.2` | Full compatibility; 3.2 supports PG 10-17. |
## Sources
- [anthropic-sdk-python — GitHub](https://github.com/anthropics/anthropic-sdk-python) — HIGH: SDK version 0.79.0 (Feb 2026), Haiku 4.5 support
- [anthropic — PyPI](https://pypi.org/project/anthropic/) — HIGH: latest release dates
- [Claude Models Overview](https://platform.claude.com/docs/en/about-claude/models/overview) — HIGH: Haiku 3 deprecation 2026-04-19, Haiku 4.5 current
- [tweepy 4.14.0 Client docs](https://docs.tweepy.org/en/stable/client.html) — HIGH: `create_tweet` + OAuth 1.0a User Context
- [tweepy Authentication docs](https://docs.tweepy.org/en/stable/authentication.html) — HIGH
- [scikit-learn 1.8 TfidfVectorizer](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html) — HIGH: current stable
- [scikit-learn cosine_similarity](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.pairwise.cosine_similarity.html) — HIGH
- [feedparser — kurtmckee GitHub](https://github.com/kurtmckee/feedparser) — HIGH: 6.0.11, active maintenance
- [SQLAlchemy 2.1 PostgreSQL dialect docs](https://docs.sqlalchemy.org/en/21/dialects/postgresql.html) — HIGH: psycopg3 dialect URL
- [psycopg 3 — Differences from psycopg2](https://www.psycopg.org/psycopg3/docs/basic/from_pg2.html) — HIGH
- [Alembic 1.18.4 docs / releases](https://alembic.sqlalchemy.org/en/latest/changelog.html) — HIGH: 1.18.0 (Jan 2026), SQLAlchemy 2.0 bulk reflection
- [Ruff docs / v0.15.0 announcement](https://astral.sh/blog/ruff-v0.15.0) — HIGH: replaces black/flake8/isort
- [uv docs](https://docs.astral.sh/uv/) — HIGH: 10-100× pip, Docker guide
- [structlog performance docs](https://www.structlog.org/en/stable/performance.html) — HIGH: orjson renderer, production patterns
- [httpx vs requests comparison (Decodo, 2026)](https://decodo.com/blog/httpx-vs-requests-vs-aiohttp) — MEDIUM: adoption by anthropic/openai SDKs
- [Python Docker base image guidance (pythonspeed, Feb 2026)](https://pythonspeed.com/articles/base-image-python-docker-images/) — HIGH: slim-bookworm over alpine for Python
- [Alpine Python build issue (pythonspeed)](https://pythonspeed.com/articles/alpine-docker-python/) — HIGH: musl vs glibc wheel problem
- [APScheduler PyPI + BetterStack guide](https://betterstack.com/community/guides/scaling-python/apscheduler-scheduled-tasks/) — HIGH: in-process scheduling patterns
- PROJECT.md — constraints (Python 3.11+, Postgres 16, Docker Compose, X Free tier, PT-BR, 280-char budget)
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, or `.github/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
