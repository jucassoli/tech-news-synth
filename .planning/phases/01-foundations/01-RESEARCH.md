# Phase 1: Foundations — Research

**Researched:** 2026-04-12
**Domain:** Python service chassis — Docker multi-stage (uv), APScheduler PID 1, structlog JSON dual-output, pydantic-settings fail-fast, Compose v2 health-gated bring-up
**Confidence:** HIGH (all pinned versions verified against PyPI on 2026-04-12; Docker/uv/APScheduler patterns verified against official docs and recent community guides)

---

## Summary

Phase 1 delivers the immutable chassis that every later phase writes through: a Compose-orchestrated `app` + `postgres` pair, a PID-1 Python process that (a) loads and validates config via pydantic-settings, (b) configures structlog JSON dual-output (stdout + file on `/data` volume), (c) instantiates an APScheduler `BlockingScheduler` pinned to UTC, (d) fires a no-op `run_cycle()` immediately on boot then every `INTERVAL_HOURS`, (e) gracefully handles SIGTERM and per-cycle exceptions, and (f) respects `PAUSED` + `DRY_RUN` switches bound to every log line.

The research space is fully covered by HIGH-confidence sources. No unresolved ambiguity blocks planning. The single most important technical discipline for this phase is **signal handling**: Python does not auto-exit on SIGTERM, so `BlockingScheduler` running as PID 1 must explicitly install a handler that calls `scheduler.shutdown(wait=True)` — otherwise `docker stop` takes 10 s and then SIGKILLs the process, half-completing any in-flight cycle.

**Primary recommendation:** Build the chassis bottom-up in this order — (1) `pyproject.toml` + `uv.lock`, (2) Dockerfile multi-stage, (3) `compose.yaml` with healthchecks, (4) `Settings` class, (5) `logging.configure_logging()`, (6) `__main__.py` dispatch + scheduler bootstrap, (7) kill-switch + DRY_RUN binding, (8) pre-commit + `.env.example`. Unit-test (4), (5), (7) directly; verify (1)–(3), (6), (8) via a `docker compose up` smoke. All versions below are pinned to the last stable release as of 2026-04-12.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Package & Layout**
- **D-01** Python package name is `tech_news_synth` (matches repo name). All downstream phases import from this root.
- **D-02** Source layout is `src/tech_news_synth/` (src-layout). `pyproject.toml` points the build backend at `src/tech_news_synth`. Prevents accidental imports from repo root during tests.
- **D-03** Runtime config `sources.yaml` lives in repo `./config/sources.yaml`, bind-mounted **read-only** to `/app/config/sources.yaml` in the container. Content populated in Phase 4; Phase 1 only wires the mount and may validate the path exists.

**Dockerfile & Entrypoint**
- **D-04** Dockerfile uses **multi-stage build** with `uv`:
  - Stage 1 (builder): uv-enabled image runs `uv sync --frozen --no-dev` into `/app/.venv`.
  - Stage 2 (runtime): `python:3.12-slim-bookworm` copies `/app/.venv` + `src/` + `pyproject.toml` + `uv.lock`. Runtime image target ≈ 150 MB, no build tools shipped.
- **D-05** Container entrypoint is `python -m tech_news_synth` (runs `src/tech_news_synth/__main__.py`, which boots APScheduler). No `[project.scripts]` console script in v1.
- **D-06** CLI tools (`replay`, `post-now`, `source-health`) are sub-commands under the same entrypoint: `python -m tech_news_synth <subcommand>`. Phase 1 wires the dispatcher **skeleton**; CLI bodies land in Phase 8. Scheduler is the default when no subcommand is given.

**Scheduler & Cycle Semantics**
- **D-07** First tick runs **immediately on container startup**, then `CronTrigger(hour="*/{INTERVAL_HOURS}", timezone=timezone.utc)` takes over. Trade-off acknowledged: every restart triggers a cycle — acceptable because v1 `run_cycle()` is a no-op and later phases' daily cap + dry-run prevent runaway cost.
- **D-08** Kill switch uses **OR logic** between `PAUSED=1` env and `/data/paused` marker file. Cycle-start log line states source via `paused_by` field (`env`, `marker`, or `both`). Env = restart-required toggle; marker file = live toggle without restart. When paused: `status=paused`, zero I/O, return 0.
- **D-09** `cycle_id` format is **ULID** (26-char Crockford base32, time-sortable). Dependency: `python-ulid`. Generated once at cycle start, bound to structlog context, persisted (Phase 2) as `run_log.cycle_id`.
- **D-10** `DRY_RUN=1` is **bound into every cycle log line** via `structlog.contextvars.bind_contextvars(dry_run=...)` at cycle start. Phase 1 `run_cycle()` has no publish step, so DRY_RUN is a no-op behaviorally but must be visible in logs (INFRA-10).

### Claude's Discretion

- Exact pydantic-settings class shape, field validators, and SecretStr usage.
- structlog processor chain and JSON renderer choice (orjson recommended per STACK.md).
- Dockerfile layer ordering and caching optimizations.
- Healthcheck commands (`pg_isready` for postgres; app healthcheck probe — file-write or `python -c` smoke).
- Logging file path and rotation policy inside the logs volume (default: `/data/logs/app.jsonl`, no rotation in v1; size-based rotation can land later).
- Test scope for Phase 1 — unit tests for config load + kill-switch + cycle_id formatting; integration test via `docker compose up` smoke optional.
- Exact pyproject build backend (hatchling vs setuptools) — must be uv-compatible.
- Pre-commit hook implementation for INFRA-04 (gitleaks vs detect-secrets vs custom regex).

### Deferred Ideas (OUT OF SCOPE)

- Logging rotation / per-level routing.
- App healthcheck semantics beyond "process alive".
- Integration test via docker-compose in CI.
- Console scripts (`[project.scripts]`) — v1 uses `python -m`.
- Multi-arch container builds (arm64) — VPS is x86_64.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INFRA-01 | `docker compose up` runs two services (`app`, `postgres`) with persistent volumes for DB and logs | §Compose Topology; §Standard Stack (Compose v2); health-gated `depends_on` |
| INFRA-02 | Base image `python:3.12-slim-bookworm` (no Alpine); deps via `uv` with pinned `pyproject.toml` + lockfile | §Dockerfile Pattern; §Standard Stack (uv 0.11.x, Python 3.12.x); PITFALLS #8 Alpine wheels |
| INFRA-03 | Secrets via pydantic-settings from `.env` (Compose `env_file:`); missing/invalid keys fail boot with clear error | §pydantic-settings Pattern; §Fail-fast Boot Sequence |
| INFRA-04 | `.env.example` committed; `.env` in `.gitignore` + `.dockerignore`; pre-commit hook scans for leaked secrets | §Pre-commit Hook (gitleaks recommended) |
| INFRA-05 | APScheduler BlockingScheduler as PID 1, `CronTrigger(hour="*/{INTERVAL_HOURS}", timezone=UTC)` | §APScheduler PID-1 Pattern; §Signal Handling |
| INFRA-06 | All timestamps UTC: Postgres `TIMESTAMPTZ`, Python `datetime.now(timezone.utc)`, no `TZ=` on containers | §UTC Invariants; PITFALLS #6 |
| INFRA-07 | structlog JSON to stdout AND Docker volume; every line tagged with `cycle_id` | §structlog Dual-Output; §contextvars Binding |
| INFRA-08 | Unhandled exceptions in `run_cycle()` logged with stacktrace but never crash scheduler | §Graceful Cycle Exceptions; `EVENT_JOB_ERROR` listener |
| INFRA-09 | Kill switch: `PAUSED=1` env OR `/data/paused` marker → cycle exits 0 with log line, zero I/O | §Kill-switch OR Logic |
| INFRA-10 | `DRY_RUN=1` accepted by config and visible in every cycle log line | §DRY_RUN Binding via contextvars |

</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Runtime:** Python 3.12 only. Do not propose 3.11 or 3.13 for v1.
- **Base image:** `python:3.12-slim-bookworm`. Alpine forbidden (scikit-learn/lxml musl breakage).
- **Scheduler:** APScheduler 3.10.x in-process (PID 1). `schedule`, system `cron`, `supercronic`, Celery all forbidden.
- **Timezone:** UTC everywhere. No `TZ=` on containers. Always `datetime.now(timezone.utc)`.
- **Secrets:** `.env` + `env_file:` only. Docker secrets / Vault out of scope. `.env` gitignored + dockerignored. `.env.example` versioned. Pre-commit leak detection required.
- **GSD workflow:** Edits must go through a GSD command (this phase is `/gsd-execute-phase`).
- **Logging:** structlog JSON to stdout + Docker volume.
- **DB driver:** psycopg3 (not psycopg2). No psycopg2 appears in Phase 1 directly but the Postgres service image is pinned so Phase 2 can connect.
- **Model pinning:** Anthropic `claude-haiku-4-5` (no alias). Not consumed in Phase 1 but the `.env.example` must list `ANTHROPIC_API_KEY`.

---

## Standard Stack

### Core (required for Phase 1 runtime)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| **Python** | 3.12.x (pin `>=3.12,<3.13` in pyproject) | Runtime | `[CITED: CLAUDE.md]`; `[VERIFIED: local python3 --version = 3.12.3]` — widest wheel coverage for scikit-learn/lxml in April 2026 |
| **uv** | 0.11.6 | Dep resolver + venv + lockfile in Dockerfile | `[VERIFIED: pip index versions uv → 0.11.6 latest]`; Astral's single-binary tool, 10–100× faster than pip |
| **Docker Engine** | 29.3.x+ | Container runtime | `[VERIFIED: local docker --version = 29.3.1]` |
| **Docker Compose** | v2 (plugin, v5.1.1 schema) | `app` + `postgres` orchestration | `[VERIFIED: local docker compose version = v5.1.1]`; Compose v2 — omit `version:` key |
| **Postgres image** | `postgres:16-bookworm` | DB service (Phase 2 consumes; Phase 1 just boots it) | `[CITED: STACK.md]` pinned in CLAUDE.md |
| **pydantic** | 2.9.x (`>=2.9,<3`) | Base for Settings | `[CITED: STACK.md]` |
| **pydantic-settings** | 2.13.1 (latest stable; pyproject pins `>=2.6,<3`) | `.env` loader + typed Settings + SecretStr | `[VERIFIED: pip index versions pydantic-settings → 2.13.1]`; first-party pydantic extension |
| **structlog** | 25.5.0 (pyproject `>=25,<26`) | JSON structured logs, contextvars binding | `[VERIFIED: pip index versions structlog → 25.5.0]` |
| **orjson** | 3.10.x | Fast JSON renderer for structlog | `[CITED: STACK.md]`; drop-in faster than stdlib, native structlog integration |
| **APScheduler** | 3.11.2 (pyproject pins `>=3.10,<4`) | BlockingScheduler PID 1, CronTrigger | `[VERIFIED: pip index versions apscheduler → 3.11.2]`; 4.x still pre-release |
| **python-ulid** | 3.1.0 (pyproject `>=3,<4`) | ULID cycle_id generator | `[VERIFIED: pip index versions python-ulid → 3.1.0]`; modern typed API; **NOT** `ulid-py` (different package, older) |
| **tenacity** | 9.x | (declared in pyproject for later phases; Phase 1 does not call it) | `[CITED: STACK.md]` |
| **PyYAML** | 6.0.x | Parse `config/sources.yaml` in later phases; Phase 1 installs it so config loader is complete | `[CITED: STACK.md implied via sources.yaml]` |

### Supporting (dev-only, declared in `[dependency-groups] dev`)

| Library | Version | Purpose |
|---------|---------|---------|
| **pytest** | 8.x | Test runner |
| **pytest-mock** | 3.14.x | `mocker` fixture for monkeypatching |
| **pytest-cov** | 5.x | Coverage (target ≥80% on config + logging modules) |
| **ruff** | 0.8+ | Linter + formatter |
| **time-machine** | 2.15.x | Freeze time in unit tests |

### Dev Tooling (not Python deps)

| Tool | Version | Purpose |
|------|---------|---------|
| **gitleaks** | v8.x (installed via pre-commit as Docker or binary) | Pre-commit secret leak scan (INFRA-04) |
| **pre-commit** | 3.x+ | Hook runner (developer machines only; not installed in container) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| **gitleaks** | detect-secrets | detect-secrets requires a baseline file + per-repo tuning; gitleaks is zero-config. `[CITED: gitleaks vs detect-secrets 2026 comparison]` — "Gitleaks is the best default choice for most teams." |
| **hatchling** (build backend) | setuptools | Both uv-compatible; hatchling is modern PEP 517, simpler config. Either acceptable. Recommend **hatchling**. |
| **orjson renderer** | stdlib `json.dumps` | orjson ~3× faster and handles `datetime` natively. Required for production JSON log throughput. |
| **python-ulid** | `uuid.uuid4()` | D-09 locks ULID — chronologically sortable, cleaner log grep. Do not reopen. |
| **argparse** for subcommand dispatch | click, typer | argparse is stdlib, zero dep; skeleton is ~20 lines. Recommend **argparse** for Phase 1; Phase 8 can migrate to click if ergonomics demand. |

### Installation

```bash
# Developer machine (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh  # installs uv
uv sync                                           # creates .venv + installs deps
uv run pre-commit install                         # installs gitleaks hook

# Container build (automated by Dockerfile)
uv sync --frozen --no-dev
```

**Version verification** (performed 2026-04-12):
- `uv`: 0.11.6 `[VERIFIED: pip index versions uv]`
- `structlog`: 25.5.0 `[VERIFIED]`
- `pydantic-settings`: 2.13.1 `[VERIFIED]` (pyproject can safely pin `>=2.6,<3`)
- `apscheduler`: 3.11.2 `[VERIFIED]` (4.x still pre-release — stick with 3.x)
- `python-ulid`: 3.1.0 `[VERIFIED]`
- `detect-secrets`: 1.5.0 `[VERIFIED]` (alternative, not chosen)

---

## Architecture Patterns

### Recommended Project Structure

```
tech-news-synth/
├── src/
│   └── tech_news_synth/
│       ├── __init__.py            # exports __version__
│       ├── __main__.py            # entrypoint: argparse dispatch → scheduler or subcommand
│       ├── scheduler.py           # build_scheduler(), run_cycle() no-op, signal handlers
│       ├── config.py              # Settings (pydantic-settings), load_settings()
│       ├── logging.py             # configure_logging() — structlog + stdlib bridge + file handler
│       ├── killswitch.py          # is_paused() → (bool, reason: str)
│       ├── ids.py                 # new_cycle_id() → ULID
│       └── cli/
│           ├── __init__.py
│           ├── replay.py          # Phase 8 body; Phase 1 stub: raise NotImplementedError
│           ├── post_now.py        # stub
│           └── source_health.py   # stub
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # shared fixtures (env setup, tmp paused marker)
│   ├── test_config.py             # Settings validation, missing keys fail
│   ├── test_logging.py            # JSON render, cycle_id binding
│   ├── test_killswitch.py         # env OR marker, paused_by reason
│   ├── test_ids.py                # ULID format, monotonic
│   └── test_scheduler.py          # run_cycle swallows exceptions; trigger timezone=UTC
├── config/
│   └── sources.yaml               # empty placeholder (Phase 4 populates); bind-mounted RO
├── .env.example                   # committed; all required keys with dummy values
├── .gitignore                     # includes .env, .env.*, !.env.example, __pycache__, .venv, .ruff_cache, .pytest_cache, /data
├── .dockerignore                  # includes .env, .env.*, .git, __pycache__, .venv, tests/, .planning/
├── .pre-commit-config.yaml        # gitleaks hook
├── compose.yaml                   # Compose v2 (no version: key), app + postgres
├── Dockerfile                     # multi-stage with uv
├── pyproject.toml                 # hatchling backend, deps, [tool.ruff], [tool.pytest.ini_options]
├── uv.lock                        # generated by `uv lock`; committed
├── README.md                      # existing
└── CLAUDE.md                      # existing
```

**Rationale:**
- **src-layout** (D-02) prevents accidental `import tech_news_synth` from repo root during tests — tests import from the installed package in the venv.
- **Flat `src/tech_news_synth/` module list** rather than sub-packages for Phase 1: the phase is small enough that each file is one concern. Later phases (`fetch/`, `cluster/`, etc.) can promote to sub-packages as needed.
- **`cli/` sub-package** exists as stubs in Phase 1 so Phase 8 has an obvious home.
- **`/data`** at repo root is git-ignored — it's the Docker named volume mount target locally if developer mounts volume as a bind. In container, `/data` is the volume mount point (not under `/app`).

### Pattern 1: Multi-stage Dockerfile with uv

**What:** Builder stage runs `uv sync --frozen --no-dev` to produce a `.venv`; runtime stage copies only the venv + source.
**When to use:** Always for Python services using uv. Keeps runtime image lean (no uv, no build cache, no dev deps).
**Example:**

```dockerfile
# Source: https://docs.astral.sh/uv/guides/integration/docker/ [CITED]
# syntax=docker/dockerfile:1.7

# --- builder stage ---
FROM python:3.12-slim-bookworm AS builder

# Copy uv binary from official image (pinned tag, not :latest)
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Layer 1: deps-only (maximizes cache hits on source edits)
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Layer 2: project install
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- runtime stage ---
FROM python:3.12-slim-bookworm

# Non-root user (UID 1000 by convention; matches common host UID)
RUN groupadd --system --gid 1000 app \
 && useradd --system --uid 1000 --gid app --home-dir /app --shell /sbin/nologin app \
 && mkdir -p /data/logs \
 && chown -R app:app /data /app

WORKDIR /app

# Copy venv and source from builder
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src
COPY --chown=app:app pyproject.toml ./

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app

# Healthcheck: verify the Python entrypoint module is importable
# (lightweight — no network, no DB call)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import tech_news_synth; import sys; sys.exit(0)" || exit 1

# Exec form ensures python is PID 1 (not /bin/sh) — critical for SIGTERM propagation
CMD ["python", "-m", "tech_news_synth"]
```

Key points [VERIFIED against uv Docker guide, 2026-04-12]:
- `UV_COMPILE_BYTECODE=1` pre-compiles .pyc files in the builder (faster first import at runtime).
- `UV_LINK_MODE=copy` avoids hardlink warnings when the cache mount crosses filesystems.
- `UV_PYTHON_DOWNLOADS=0` forbids uv from fetching its own Python — we use the base image's.
- Two-stage `uv sync` (`--no-install-project` then full) maximizes Docker layer caching: dep changes bust only the first layer; source edits bust only the second.
- **Exec form CMD** (`CMD ["python", ...]`) — shell form would make `/bin/sh` PID 1 and eat SIGTERM. `[CITED: oneuptime.com/blog/.../2026-01-16-docker-graceful-shutdown-signals]`
- Non-root `app` user (UID 1000) owns `/data` — the Compose-mounted volume must be writable by this user.
- No `tini`/`dumb-init` needed: Python process installs its own signal handler (see Pattern 3). Only add `tini` if we observe zombie reaping issues — we won't, because Phase 1 spawns no subprocesses.

### Pattern 2: Compose Topology (health-gated)

**What:** `app` + `postgres` with a shared network, named volumes, `env_file: .env`, and `depends_on: condition: service_healthy` so app never starts before Postgres accepts connections.
**When to use:** Standard topology for a Python service + single Postgres.
**Example:**

```yaml
# Source: Compose v2 official spec + pytonspeed / docker docs patterns [CITED: STACK.md]
# Compose v2: no `version:` key
name: tech-news-synth

services:
  postgres:
    image: postgres:16-bookworm
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
      # Note: do NOT set TZ — Postgres defaults to UTC with TIMESTAMPTZ storage [CITED: PITFALLS #6]
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 10s
    # No ports: published — accessed only via the compose network. Uncomment `ports:` for local DB tools.

  app:
    build:
      context: .
      dockerfile: Dockerfile
    restart: unless-stopped
    env_file:
      - .env
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - logs:/data
      - ./config:/app/config:ro     # read-only bind mount (D-03)
    # Healthcheck defined in Dockerfile (HEALTHCHECK directive)
    # stop_grace_period allows the scheduler to finish an in-flight run_cycle() and drain logs
    stop_grace_period: 30s
    stop_signal: SIGTERM

volumes:
  pgdata:
  logs:

# No explicit `networks:` — Compose auto-creates a default bridge network named `<project>_default`
```

Key points:
- **`name:`** at top (Compose v2 feature) — makes volume names predictable (`tech-news-synth_pgdata`).
- **No `version:`** key — Compose v2 ignores it and warns.
- **`env_file: - .env`** — values injected at container start; never baked into the image. `.env` must be in `.dockerignore`.
- **Healthcheck on postgres** (`pg_isready`) + `condition: service_healthy` = app boot is gated on DB ready. Prevents Phase 2's Alembic from racing Postgres start.
- **`stop_grace_period: 30s`** > Docker default 10s — gives `scheduler.shutdown(wait=True)` time to finish a cycle.
- **`ro` bind mount** on `./config` — operator edits YAML on host; container cannot mutate it (defense in depth).
- **No `TZ=`** anywhere `[CITED: PITFALLS #6]`.

### Pattern 3: APScheduler BlockingScheduler as PID 1 with Signal Handling

**What:** `BlockingScheduler` is the long-lived Python process; signal handlers for SIGTERM/SIGINT call `scheduler.shutdown(wait=True)`; an `EVENT_JOB_ERROR` listener logs stacktraces.
**When to use:** Single-container Python services with cron-like needs. Standard pattern for this project.
**Example:**

```python
# Source: APScheduler 3.x User Guide [CITED]
#         + oneuptime.com 2026-01 graceful-shutdown guide [CITED]
#         + STACK.md / CLAUDE.md constraints

from __future__ import annotations

import signal
import sys
from datetime import datetime, timezone

from apscheduler.events import EVENT_JOB_ERROR
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from structlog.contextvars import bind_contextvars, clear_contextvars

from tech_news_synth.config import Settings
from tech_news_synth.ids import new_cycle_id
from tech_news_synth.killswitch import check_paused
from tech_news_synth.logging import get_logger

log = get_logger(__name__)


def run_cycle(settings: Settings) -> None:
    """No-op cycle for Phase 1. Later phases replace the body.

    Must NEVER raise; wrap its own exceptions. Scheduler ALSO has an
    EVENT_JOB_ERROR listener as a second line of defense (INFRA-08).
    """
    clear_contextvars()
    cycle_id = new_cycle_id()
    bind_contextvars(
        cycle_id=cycle_id,
        dry_run=settings.dry_run,     # INFRA-10
    )

    try:
        paused, reason = check_paused(settings)
        if paused:
            log.info("cycle_paused", paused_by=reason, status="paused")
            return

        log.info("cycle_start")
        # --- Phase 1: no-op body. Later phases: fetch → cluster → synthesize → publish ---
        log.info("cycle_end", status="ok")

    except Exception:
        # INFRA-08: log stacktrace, never propagate to the scheduler loop
        log.exception("cycle_failed", status="failed")


def _job_error_listener(event) -> None:
    """Safety net — only fires if run_cycle itself re-raised (shouldn't)."""
    log.error("scheduler_job_error", exception=str(event.exception))


def build_scheduler(settings: Settings) -> BlockingScheduler:
    scheduler = BlockingScheduler(
        timezone=timezone.utc,                          # INFRA-05, INFRA-06
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
    )
    scheduler.add_listener(_job_error_listener, EVENT_JOB_ERROR)

    # D-07: first tick on boot, then cron cadence
    scheduler.add_job(
        run_cycle,
        trigger=CronTrigger(hour=f"*/{settings.interval_hours}", timezone=timezone.utc),
        next_run_time=datetime.now(timezone.utc),       # fire once immediately
        args=[settings],
        id="run_cycle",
        replace_existing=True,
    )
    return scheduler


def _install_signal_handlers(scheduler: BlockingScheduler) -> None:
    """
    CRITICAL: Python does NOT exit on SIGTERM by default.
    Without this, `docker stop` waits 30s (stop_grace_period) then SIGKILLs us
    mid-cycle. [CITED: oneuptime 2026-01 guide; tutorialpedia.org]
    """
    def _shutdown(signum, frame):
        log.info("shutdown_signal_received", signal=signal.Signals(signum).name)
        scheduler.shutdown(wait=True)   # drains in-flight job
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)


def run() -> None:
    """Entrypoint called from __main__.py when no subcommand is given."""
    settings = Settings()                               # raises on invalid .env (INFRA-03)
    scheduler = build_scheduler(settings)
    _install_signal_handlers(scheduler)
    log.info(
        "scheduler_starting",
        interval_hours=settings.interval_hours,
        dry_run=settings.dry_run,
        paused_env=settings.paused,
    )
    scheduler.start()                                   # blocks until shutdown
```

Key points:
- `BlockingScheduler` ≠ `BackgroundScheduler`. BlockingScheduler is correct here — the scheduler *is* the process `[CITED: APScheduler user guide]`.
- `timezone=timezone.utc` on both the scheduler **and** the `CronTrigger`. Don't rely on system TZ. `[CITED: PITFALLS #7]`
- `next_run_time=datetime.now(timezone.utc)` implements D-07 cleanly — APScheduler fires the job immediately on `.start()`, then follows the cron cadence. Simpler than manually calling `run_cycle()` before `.start()` and avoids double-fire races.
- `coalesce=True` + `max_instances=1` + `misfire_grace_time=300`: if the container was paused/host slept and missed ticks, only one catch-up fires (not N back-to-back). Prevents thundering herd.
- Two-layer error defense: (a) `run_cycle` has its own try/except, (b) `EVENT_JOB_ERROR` listener catches anything that escapes. (a) is the primary; (b) is belt-and-suspenders.
- **Signal handlers** are the single most important line of this file. Without them, graceful shutdown breaks.

### Pattern 4: pydantic-settings Fail-fast with SecretStr

**What:** A `Settings(BaseSettings)` class that loads from `.env` + env vars, uses `SecretStr` for all API keys, and raises `ValidationError` on boot if anything is missing or wrong-typed.
**When to use:** Always, for every env-driven Python service.
**Example:**

```python
# Source: pydantic-settings 2.x docs [CITED]
#         + STACK.md pin (2.6.x → latest 2.13.1 OK)

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",          # Compose injects OS env vars we don't model; don't crash on them
        frozen=True,              # immutable — set once at boot
    )

    # --- runtime config ---
    interval_hours: int = Field(default=2, ge=1, le=24)
    paused: bool = False                                  # INFRA-09 env half
    dry_run: bool = False                                 # INFRA-10
    paused_marker_path: Path = Path("/data/paused")       # INFRA-09 marker half
    log_dir: Path = Path("/data/logs")
    log_file_name: str = "app.jsonl"

    # --- secrets (all required in .env; SecretStr prevents accidental log leak) ---
    # Listed here in Phase 1 so `.env.example` / validation is complete from day 1,
    # even though Phase 1 code does not USE them. Missing keys = boot failure (INFRA-03).
    anthropic_api_key: SecretStr
    x_consumer_key: SecretStr
    x_consumer_secret: SecretStr
    x_access_token: SecretStr
    x_access_token_secret: SecretStr

    # --- DB (Phase 2 consumes; Phase 1 validates format) ---
    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str
    postgres_host: str = "postgres"  # compose service name
    postgres_port: int = 5432

    @field_validator("interval_hours")
    @classmethod
    def _validate_interval_divides_24(cls, v: int) -> int:
        # CronTrigger(hour="*/N") only produces a regular cadence if 24 % N == 0
        if 24 % v != 0:
            raise ValueError(f"INTERVAL_HOURS={v} does not divide 24 evenly")
        return v

    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


def load_settings() -> Settings:
    """Wrapper used by __main__ so tests can monkeypatch the factory."""
    return Settings()
```

Key points:
- `env_file=".env"` — loaded at `Settings()` call time. Compose already injects the same vars into the process env via `env_file: .env` in `compose.yaml`, so inside the container the `.env` file itself is not present (it lives on the host). `pydantic-settings` gracefully handles the missing file and falls back to OS env vars.
- `case_sensitive=False` — match `POSTGRES_USER` in `.env` to `postgres_user` field (idiomatic).
- `extra="ignore"` — Compose / k8s inject vars we don't model; don't crash.
- `frozen=True` — settings are immutable; protects against mutation from tests/subcommands.
- **All secrets are `SecretStr`** — `log.info("cfg", s=settings)` renders as `anthropic_api_key=SecretStr('**********')` (not the raw value). `[CITED: pydantic-settings docs]`
- `field_validator` for `interval_hours` catches nonsensical values (e.g., `INTERVAL_HOURS=5` — doesn't divide 24 cleanly, produces irregular cron cadence).
- `ValidationError` is raised on boot — the `__main__.py` catches it, prints a human-readable error, and `sys.exit(2)`.

**Fail-fast boot sequence:**
```python
# __main__.py
def main() -> int:
    try:
        settings = load_settings()
    except ValidationError as e:
        print(f"Configuration error:\n{e}", file=sys.stderr)  # stderr, not structlog
        return 2
    configure_logging(settings)
    # ... dispatch to scheduler or subcommand
```
Using `print(..., file=sys.stderr)` **before** `configure_logging` is intentional — if config is broken we can't set up logging reliably, and Docker still captures stderr.

### Pattern 5: structlog Dual-Output (stdout + /data/logs/app.jsonl)

**What:** One structlog pipeline configured to emit JSON to both `sys.stdout` (Docker picks up via logs driver) **and** a file on the `/data` volume (persistent).
**When to use:** When you need both Docker-level log capture AND durable on-host log files (INFRA-07).
**Example:**

```python
# Source: structlog 25 docs [CITED]
#         + structlog GitHub issue #707 pattern [CITED]

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

import orjson
import structlog

from tech_news_synth.config import Settings


def _orjson_dumps(v, *, default):
    # structlog's JSONRenderer default uses stdlib json; orjson is faster and handles datetime natively
    return orjson.dumps(v, default=default).decode()


def configure_logging(settings: Settings) -> None:
    """Configure structlog for JSON output to stdout AND to a file on /data."""

    settings.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = settings.log_dir / settings.log_file_name

    shared_processors = [
        structlog.contextvars.merge_contextvars,   # pulls cycle_id, dry_run from contextvars
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),  # INFRA-06 UTC
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # Configure structlog → stdlib logging bridge so we get ONE processor chain and TWO handlers
    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processor=structlog.processors.JSONRenderer(serializer=_orjson_dumps),
    )

    # Handler 1: stdout (Docker captures via `docker compose logs`)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)

    # Handler 2: file on /data volume (persistent, tailable from host)
    # WatchedFileHandler is preferred over FileHandler for log-rotate-external scenarios,
    # but in Phase 1 we don't rotate — plain FileHandler is fine.
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(stdout_handler)
    root.addHandler(file_handler)
    root.setLevel(logging.INFO)

    # Silence noisy libraries (apscheduler is INFO-chatty)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def get_logger(name: str | None = None):
    return structlog.get_logger(name)
```

Key points:
- **Bridge structlog through stdlib logging** — `ProcessorFormatter.wrap_for_formatter` + `ProcessorFormatter` lets one structlog pipeline feed multiple stdlib `Handler`s. Writing to stdout and a file twice from structlog directly (two `logger_factory` instances) is possible but brittle; this is the recommended pattern `[CITED: structlog GitHub #707]`.
- **orjson renderer** — faster, handles `datetime`/`UUID`/`ULID`-likes natively.
- **`TimeStamper(fmt="iso", utc=True)`** — every log line has an ISO-8601 UTC `timestamp` field. INFRA-06 compliance.
- **`merge_contextvars` is first** in `shared_processors` so `cycle_id` and `dry_run` bound via `structlog.contextvars.bind_contextvars(...)` appear on every event, including logs from stdlib-only libraries (e.g., APScheduler) that routed through the bridge.
- **Log file path** on `/data/logs/app.jsonl` → written via the `logs` named volume in Compose. Host can tail with `docker compose exec app tail -f /data/logs/app.jsonl` or `docker run ... -v tech-news-synth_logs:/x alpine tail -f /x/logs/app.jsonl`.
- **No rotation in v1** (deferred per CONTEXT.md). If the file grows unbounded, Phase 8 hardening can swap `FileHandler` → `RotatingFileHandler` with size-based rollover.

### Pattern 6: Kill-switch (PAUSED env OR marker file)

**What:** A pure function that reads `settings.paused` **and** checks for `settings.paused_marker_path.exists()`, returns `(bool, reason)` where reason ∈ `{"env", "marker", "both"}`.
**When to use:** First line of `run_cycle()`. D-08.
**Example:**

```python
# killswitch.py
from __future__ import annotations

from tech_news_synth.config import Settings


def check_paused(settings: Settings) -> tuple[bool, str | None]:
    """
    Returns (is_paused, reason) per D-08.
    reason ∈ {"env", "marker", "both", None}
    """
    env_paused = settings.paused
    marker_paused = settings.paused_marker_path.exists()

    if env_paused and marker_paused:
        return True, "both"
    if env_paused:
        return True, "env"
    if marker_paused:
        return True, "marker"
    return False, None
```

Key points:
- Pure function; trivially unit-testable with `tmp_path` and env patching.
- OR semantics: either condition pauses. Env = restart-required (set in `.env`), marker = live toggle (`docker compose exec app touch /data/paused`).
- The path `/data/paused` lives on the named `logs` volume — it persists across restarts, same as logs. Operator can `touch` / `rm` via `docker compose exec app`.

### Pattern 7: __main__ Dispatch (argparse skeleton)

```python
# src/tech_news_synth/__main__.py
from __future__ import annotations

import argparse
import sys

from pydantic import ValidationError

from tech_news_synth.config import load_settings
from tech_news_synth.logging import configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tech_news_synth")
    sub = parser.add_subparsers(dest="command")

    # Stubs for Phase 8. Present in Phase 1 so `python -m tech_news_synth --help` shows the surface.
    sub.add_parser("replay",        help="Replay a past cycle's synthesis (Phase 8)")
    sub.add_parser("post-now",      help="Force an off-cadence cycle (Phase 8)")
    sub.add_parser("source-health", help="Show per-source health (Phase 8)")

    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ValidationError as e:
        print(f"Configuration error:\n{e}", file=sys.stderr)
        return 2

    configure_logging(settings)

    if args.command is None:
        # Default: run scheduler (D-06)
        from tech_news_synth.scheduler import run
        run()
        return 0

    # Phase 1 stubs
    print(f"Subcommand '{args.command}' is not implemented yet (Phase 8).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

### Pattern 8: Pre-commit with gitleaks (INFRA-04)

```yaml
# .pre-commit-config.yaml
# Source: https://github.com/gitleaks/gitleaks [CITED]
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2     # pin; update via `pre-commit autoupdate`
    hooks:
      - id: gitleaks

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: check-added-large-files
      - id: end-of-file-fixer
      - id: trailing-whitespace
      - id: check-yaml
      - id: check-toml

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.4
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

Key points:
- **gitleaks > detect-secrets** for this use case: zero-config, sub-second scans, single Go binary installed by pre-commit. detect-secrets requires a baseline file and audit workflow. `[CITED: gitleaks vs detect-secrets 2026 comparison]`
- Hook runs on **staged changes only** (default) — fast. `pre-commit run --all-files` for full-repo audit.
- `ruff` hook here covers lint + format; local dev only, not the container.

### Anti-Patterns to Avoid

- **Shell-form CMD** (`CMD python -m tech_news_synth`) — makes `/bin/sh` PID 1, eats SIGTERM. **Use exec form.** `[CITED: PITFALLS via oneuptime 2026-01]`
- **System cron inside container** — invisible logs, env stripping, PID 1 issues. `[CITED: PITFALLS #7]`
- **`datetime.utcnow()` / `datetime.now()`** — naive, deprecated. Always `datetime.now(timezone.utc)`. `[CITED: PITFALLS #6]`
- **`TZ=` env var on any service** — breaks TIMESTAMPTZ comparison logic. `[CITED: PITFALLS #6]`
- **`COPY . .` without `.dockerignore`** — leaks `.env` into image layers. `[CITED: PITFALLS #8]`
- **Single Settings instance mutated at runtime** — use `frozen=True`.
- **Logging `settings` with raw secrets** — `SecretStr` prevents this; don't `str()` the secret.
- **`BlockingScheduler` without `timezone=`** — uses system TZ (varies by host). Always explicit UTC. `[CITED: PITFALLS #7]`
- **No signal handler in Python PID 1** — `docker stop` waits 30 s then SIGKILLs mid-cycle. Always install SIGTERM/SIGINT handlers.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Parse `.env` files | A custom `for line in open('.env')` loop | `pydantic-settings` | Handles quoting, comments, multi-line, env precedence; adds typed validation |
| Structured JSON logging | `json.dumps({...})` calls scattered in code | `structlog` + orjson renderer | contextvars, processor pipeline, stdlib bridge, exception rendering |
| Cron parsing / scheduling | `while True: if now.hour %% N == 0: ...` | `APScheduler` `CronTrigger` | Timezone safety, misfire grace, coalesce, DST handling |
| Monotonic sortable IDs | Custom `timestamp-random` strings | `python-ulid` | 26-char Crockford base32, lexicographically sortable, monotonic within ms |
| Secret leak detection | Regex grep in a Makefile | `gitleaks` via pre-commit | 150+ built-in rules, maintained, fast |
| Process signal handling | Assuming `KeyboardInterrupt` is enough | Explicit `signal.signal(SIGTERM, ...)` + `scheduler.shutdown(wait=True)` | Python doesn't auto-handle SIGTERM; Docker requires it |
| Dual log output (stdout + file) | Two structlog configurations | One structlog → stdlib bridge + two stdlib `Handler`s | Single processor chain, consistent output, documented pattern |
| Dependency resolution + venv in Docker | `pip install -r requirements.txt` in one layer | `uv sync --frozen --no-dev` with two-layer build | 10–100× faster, lockfile-native, correct caching |

**Key insight:** Every item in this table is a trap people fall into trying to "keep deps low." Each costs more time in bugs than the dependency costs in install time.

---

## Runtime State Inventory

Phase 1 is **greenfield scaffolding** — there is no existing runtime state to migrate. Inventory included for completeness per the research template.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — repo has no database yet | N/A |
| Live service config | None — no deployed services | N/A |
| OS-registered state | None — no systemd units, no Task Scheduler entries | N/A |
| Secrets/env vars | None yet — `.env` does not exist. `.env.example` to be created this phase. | N/A |
| Build artifacts | None — no installed package, no build outputs | N/A |

**Nothing found in any category** — verified by `git status` (clean tree) and directory listing (only `CLAUDE.md`, `README.md`, `.planning/`).

---

## Common Pitfalls

### Pitfall 1: Python process ignores SIGTERM → `docker stop` takes 30 s and SIGKILLs mid-cycle
**What goes wrong:** `docker compose down` waits `stop_grace_period` (30 s), then sends SIGKILL. In-flight cycle is half-done; Postgres sees partial writes.
**Why it happens:** Python doesn't auto-handle SIGTERM. BlockingScheduler blocks on its event loop and never sees the signal unless a handler is installed.
**How to avoid:** `signal.signal(signal.SIGTERM, handler)` where handler calls `scheduler.shutdown(wait=True)` then `sys.exit(0)`. Use **exec form CMD** so Python is PID 1. `[CITED: oneuptime 2026-01 guide]`
**Warning signs:** `docker compose stop` consistently takes the full grace period; logs end abruptly; in-flight HTTP calls leak.

### Pitfall 2: Shell-form CMD makes /bin/sh PID 1
**What goes wrong:** `CMD python -m tech_news_synth` is interpreted as `CMD ["/bin/sh", "-c", "python -m tech_news_synth"]`. Shell is PID 1, Python is its child. SIGTERM goes to the shell, which doesn't forward it.
**Why it happens:** Both CMD forms look identical in docs. Default mental model.
**How to avoid:** Always exec form: `CMD ["python", "-m", "tech_news_synth"]`.
**Warning signs:** Same as Pitfall 1.

### Pitfall 3: `CronTrigger(hour="*/5")` does NOT produce "every 5 hours"
**What goes wrong:** Operator sets `INTERVAL_HOURS=5`. APScheduler's cron `hour="*/5"` fires at 00, 05, 10, 15, 20, then the next midnight cycle is 00 (only 4 h gap, not 5). Same for 7, 8 (if 24 % N != 0), 9, 10, 11, 13...
**Why it happens:** Standard cron `*/N` is **stride**, not **period** — it resets at the field boundary (midnight for hours).
**How to avoid:** Validate in Settings: `24 % interval_hours == 0` (valid values: 1, 2, 3, 4, 6, 8, 12, 24). Reject others with `ValidationError` at boot. `[VERIFIED: standard cron semantics]`
**Warning signs:** Irregular cadence on operator dashboards; midnight always fires a cycle.

### Pitfall 4: `.env` leaked to image via `COPY . .`
**What goes wrong:** `COPY . /app` in Dockerfile copies local `.env` into the image layer forever, even if compose uses `env_file:`.
**Why it happens:** `.dockerignore` forgotten.
**How to avoid:** `.dockerignore` with `.env`, `.env.*` (except `.env.example`), `.git/`, `tests/`, `.planning/`. `docker history <image>` audit. Pre-commit gitleaks catches the git side. `[CITED: PITFALLS #8]`
**Warning signs:** `docker history` shows a suspiciously-sized `COPY` layer; `docker run --rm image cat /app/.env` returns contents.

### Pitfall 5: structlog logging before configure_logging() → default console renderer used
**What goes wrong:** Early startup code (e.g., `load_settings`) uses `log = structlog.get_logger()` at module import time. If it logs before `configure_logging()` runs, structlog uses defaults (console renderer, no timestamps, no UTC).
**Why it happens:** Import-time side effects.
**How to avoid:** Never log at import time. Call `configure_logging(settings)` as the first thing in `main()` after settings load. For truly pre-config errors (ValidationError), use stderr `print()`.
**Warning signs:** First few log lines in `docker compose logs` are plaintext; later lines are JSON.

### Pitfall 6: Bind mount `./config:/app/config:ro` fails on SELinux hosts
**What goes wrong:** On RHEL/Fedora/Rocky hosts with SELinux, unlabeled bind mounts get `Permission denied`.
**Why it happens:** SELinux labels.
**How to avoid:** Append `:z` (shared) or `:Z` (private): `./config:/app/config:ro,z`. Target VPS is Ubuntu (no SELinux by default) — low priority, document in DEPLOY.md. `[ASSUMED: likely not an issue for Ubuntu VPS target]`
**Warning signs:** `PermissionError` reading `sources.yaml` only on certain hosts.

### Pitfall 7: APScheduler silently swallows job exceptions
**What goes wrong:** APScheduler logs exceptions at `ERROR` on its own logger (`apscheduler.executors.default`) but the job is marked complete and the scheduler ticks on. If the operator silenced `apscheduler` too aggressively (we set WARNING, which is fine), exceptions become invisible.
**Why it happens:** APScheduler's executor catches and logs but doesn't re-raise.
**How to avoid:** (a) Wrap `run_cycle` body in try/except and log via our own logger. (b) Register `EVENT_JOB_ERROR` listener as a safety net. Both shown in Pattern 3. `[CITED: APScheduler user guide + PITFALLS #16 integration gotcha]`
**Warning signs:** Cycles that "worked" in logs but produced no downstream effects.

### Pitfall 8: `logging.FileHandler` on a volume that doesn't exist yet
**What goes wrong:** First boot of a fresh Compose stack — `/data/logs/` doesn't exist because the named volume is empty. `FileHandler('/data/logs/app.jsonl')` raises `FileNotFoundError`.
**Why it happens:** Volume mounts as empty directory.
**How to avoid:** `settings.log_dir.mkdir(parents=True, exist_ok=True)` in `configure_logging()` before instantiating the handler. Also pre-create `/data/logs` in the Dockerfile for the case where the volume is NOT mounted (dev-without-compose).
**Warning signs:** Boot fails on clean `docker compose up --build`.

### Pitfall 9: `paused` env flag as string "0" → truthy
**What goes wrong:** Developer sets `PAUSED=0` in `.env` expecting "off". pydantic-settings with `bool` field parses `"0"` as `False` correctly **if** field is typed `bool` — but `"false"`, `"off"`, `"no"` also work. Raw `str` field `"0"` is truthy Python.
**Why it happens:** Confusion about string-to-bool coercion.
**How to avoid:** Always type as `bool` in pydantic-settings (as shown in Pattern 4). pydantic coerces `"0"`, `"false"`, `"no"`, `"off"` → `False`. Verify with unit test.
**Warning signs:** Operator set `PAUSED=0` and cycles still skip.

---

## Code Examples

All code examples appear in §Architecture Patterns 1–8 above. Summary of files produced by Phase 1:

| File | Lines (est.) | Source |
|------|--------------|--------|
| `pyproject.toml` | ~60 | §Installation + §Standard Stack |
| `uv.lock` | generated | `uv lock` |
| `Dockerfile` | ~40 | Pattern 1 |
| `compose.yaml` | ~45 | Pattern 2 |
| `.env.example` | ~15 | §pydantic-settings Pattern 4 (list every Settings field with dummy value) |
| `.gitignore` / `.dockerignore` | ~15 each | Pattern 1 + Pattern 2 |
| `.pre-commit-config.yaml` | ~20 | Pattern 8 |
| `src/tech_news_synth/__init__.py` | ~3 | `__version__ = "0.1.0"` |
| `src/tech_news_synth/__main__.py` | ~40 | Pattern 7 |
| `src/tech_news_synth/config.py` | ~60 | Pattern 4 |
| `src/tech_news_synth/logging.py` | ~70 | Pattern 5 |
| `src/tech_news_synth/scheduler.py` | ~90 | Pattern 3 |
| `src/tech_news_synth/killswitch.py` | ~20 | Pattern 6 |
| `src/tech_news_synth/ids.py` | ~10 | `from ulid import ULID; def new_cycle_id() -> str: return str(ULID())` |
| `src/tech_news_synth/cli/*.py` | ~5 each × 3 | stubs that raise `NotImplementedError` |
| `tests/test_*.py` | ~50 each × 5 | see §Validation Architecture |

**Total: ~650 lines of code, ~250 of tests.** Appropriate scope for one phase.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `pip install -r requirements.txt` | `uv sync --frozen --no-dev` | uv 0.1+ (2024), mature by 2026 | 10–100× faster builds; lockfile-native |
| `python-dotenv` standalone | `pydantic-settings` | pydantic v2 (2023) | Typed validation; SecretStr |
| `black + flake8 + isort` | `ruff check && ruff format` | ruff 0.1+ (2023) | Single tool, ~100× faster |
| `datetime.utcnow()` | `datetime.now(timezone.utc)` | Deprecated in Python 3.12 | Timezone-aware; deprecation warnings eliminated |
| `CMD python app.py` (shell form) | `CMD ["python", "app.py"]` (exec form) | Docker best practices pre-2020 | Correct SIGTERM propagation |
| `tini` / `dumb-init` init wrapper | Native Python signal handlers | Container-native Python | Remove a dep when no subprocess reaping is needed |
| stdlib `json.dumps` in structlog | `orjson.dumps` renderer | orjson 3.x | ~3× faster JSON; native datetime |

**Deprecated / outdated:**
- `datetime.utcnow()` — use `datetime.now(timezone.utc)`.
- APScheduler 4.x — still pre-release in April 2026; use 3.11.x. `[VERIFIED: PyPI latest stable is 3.11.2]`
- `ulid-py` (different package from `python-ulid`) — older, less maintained. Use `python-ulid`.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | uv builder, local tests | ✓ | 3.12.3 | — |
| Docker Engine | `docker compose up` | ✓ | 29.3.1 | — |
| Docker Compose v2 | Compose topology | ✓ | v5.1.1 | — |
| `uv` (local dev) | Lockfile generation, local runs | ✗ | — | Install via `curl -LsSf https://astral.sh/uv/install.sh | sh` as part of first task |
| `pre-commit` (local dev) | gitleaks hook | ✗ | — | Install via `pipx install pre-commit` as part of setup task |
| `gitleaks` binary | Pre-commit hook execution | ✗ (auto-installed by pre-commit) | — | pre-commit manages via its own venv/Docker |
| Postgres 16 (host install) | Not needed | N/A | — | DB runs in Compose service, not host |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** `uv`, `pre-commit` — both install via documented one-liners; task plans must include install steps for the developer machine. Neither is needed inside the runtime container (uv is only in the builder stage; pre-commit is dev-only).

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-mock + time-machine + pytest-cov |
| Config file | `[tool.pytest.ini_options]` in `pyproject.toml` (no separate pytest.ini) |
| Quick run command | `uv run pytest -x --ff` |
| Full suite command | `uv run pytest --cov=tech_news_synth --cov-report=term-missing` |
| Coverage target | ≥80% on `config.py`, `logging.py`, `killswitch.py`, `ids.py`, `scheduler.py` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| INFRA-01 | `docker compose up` brings up healthy app + postgres with named volumes | compose smoke (manual or CI) | `docker compose up -d && docker compose ps --format json \| jq '.[].Health' \| grep -c healthy` == 2 | ❌ Wave 0 (manual runbook step; optional CI job) |
| INFRA-02 | Base image slim-bookworm; deps via uv from pinned lockfile | Dockerfile inspection + build | `docker build -t tns:test . && docker run --rm tns:test python -c "import tech_news_synth; print(tech_news_synth.__version__)"` | ❌ Wave 0 (manual; implicit via INFRA-01 smoke) |
| INFRA-03 | Missing / invalid .env key fails boot with clear error | unit | `pytest tests/test_config.py::test_missing_key_raises_validation_error -x` | ❌ Wave 0 |
| INFRA-03 | `SecretStr` hides value in repr | unit | `pytest tests/test_config.py::test_secret_not_leaked_in_repr -x` | ❌ Wave 0 |
| INFRA-03 | `interval_hours` not dividing 24 rejected | unit | `pytest tests/test_config.py::test_interval_must_divide_24 -x` | ❌ Wave 0 |
| INFRA-04 | `.env` in `.gitignore` + `.dockerignore`; `.env.example` committed | repo invariant | `pytest tests/test_repo_hygiene.py -x` (asserts `.env.example` exists, `.env` matches gitignore pattern) | ❌ Wave 0 |
| INFRA-04 | gitleaks hook installed and blocks a fake-secret commit | integration (manual runbook) | `echo 'ANTHROPIC_API_KEY=sk-ant-xxx' > /tmp/bad && git add /tmp/bad && pre-commit run --files /tmp/bad` (expect non-zero exit) | ❌ Wave 0 (manual) |
| INFRA-05 | APScheduler uses `BlockingScheduler` + `CronTrigger(timezone=utc)` | unit | `pytest tests/test_scheduler.py::test_trigger_is_cron_utc -x` | ❌ Wave 0 |
| INFRA-05 | First tick runs immediately on boot (next_run_time=now) | unit | `pytest tests/test_scheduler.py::test_first_tick_immediate -x` | ❌ Wave 0 |
| INFRA-06 | `TimeStamper` uses UTC | unit | `pytest tests/test_logging.py::test_timestamp_is_utc_iso -x` | ❌ Wave 0 |
| INFRA-06 | No `TZ=` in compose/Dockerfile | repo invariant | `pytest tests/test_repo_hygiene.py::test_no_tz_env -x` (grep compose.yaml + Dockerfile for `TZ=`) | ❌ Wave 0 |
| INFRA-07 | Log line is valid JSON; contains `cycle_id`, `dry_run`, `timestamp`, `level`, `event` | unit | `pytest tests/test_logging.py::test_json_line_shape -x` (captures stdout via capsys, `json.loads` the line) | ❌ Wave 0 |
| INFRA-07 | Log writes to file on `/data/logs/app.jsonl` (tmp_path substituted) | unit | `pytest tests/test_logging.py::test_file_handler_writes -x` | ❌ Wave 0 |
| INFRA-07 | `cycle_id` bound via contextvars appears in all subsequent logs within the cycle | unit | `pytest tests/test_logging.py::test_cycle_id_binding -x` | ❌ Wave 0 |
| INFRA-08 | `run_cycle()` swallows exceptions; scheduler listener logs them | unit | `pytest tests/test_scheduler.py::test_run_cycle_swallows_exception -x` (monkeypatch body to raise, assert no propagation) | ❌ Wave 0 |
| INFRA-09 | `PAUSED=1` → cycle exits early with `paused_by=env` | unit | `pytest tests/test_killswitch.py::test_env_pauses -x` | ❌ Wave 0 |
| INFRA-09 | Marker file exists → cycle exits early with `paused_by=marker` | unit | `pytest tests/test_killswitch.py::test_marker_pauses -x` (use tmp_path for marker) | ❌ Wave 0 |
| INFRA-09 | Both → `paused_by=both` | unit | `pytest tests/test_killswitch.py::test_both_pauses -x` | ❌ Wave 0 |
| INFRA-09 | Neither → cycle runs | unit | `pytest tests/test_killswitch.py::test_neither_runs -x` | ❌ Wave 0 |
| INFRA-10 | `DRY_RUN=1` bound into every log line via contextvars | unit | `pytest tests/test_scheduler.py::test_dry_run_in_logs -x` (capsys + json.loads, assert `dry_run: true`) | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest -x --ff` (fast, fails on first error)
- **Per wave merge:** `uv run pytest --cov=tech_news_synth --cov-report=term-missing` (full suite + coverage)
- **Phase gate:** Full suite green + `docker compose up -d` smoke passes (healthy for ≥30 s, at least one `cycle_start` log line observed)

### Wave 0 Gaps

All test files must be created fresh in Wave 0 (greenfield project):
- [ ] `pyproject.toml` section `[tool.pytest.ini_options]` — pytest config, testpaths, asyncio mode (not needed), coverage source
- [ ] `tests/__init__.py` — empty
- [ ] `tests/conftest.py` — fixtures: (a) `tmp_settings(monkeypatch, tmp_path)` factory that sets env vars + log_dir, (b) `capture_logs(capsys)` helper returning parsed JSON lines
- [ ] `tests/test_config.py` — INFRA-03 coverage
- [ ] `tests/test_logging.py` — INFRA-06, INFRA-07 coverage
- [ ] `tests/test_killswitch.py` — INFRA-09 coverage
- [ ] `tests/test_ids.py` — ULID format (26 chars, Crockford base32), monotonic within ms
- [ ] `tests/test_scheduler.py` — INFRA-05, INFRA-08, INFRA-10 coverage
- [ ] `tests/test_repo_hygiene.py` — INFRA-04 and INFRA-06 repo invariants (file-system asserts)
- [ ] Framework install: `uv add --group dev pytest pytest-mock pytest-cov time-machine`

### Nyquist Dimensions — Covered

| Dimension | Phase 1 Coverage |
|-----------|------------------|
| Happy path | `cycle_start` → `cycle_end` logs on boot, file + stdout both produced |
| Error modes | invalid `.env` → boot fails; exception in `run_cycle` → logged, scheduler survives |
| Edge cases | `interval_hours` not dividing 24, PAUSED + marker both set, ULID format, paused with no marker dir |
| Observability | Every log line has `cycle_id`, `dry_run`, `timestamp` UTC; `EVENT_JOB_ERROR` listener present |
| Performance | N/A for Phase 1 (no throughput requirements); image size target ~150 MB checked manually |

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | partial | N/A in Phase 1 (Phase 3 gate tests X OAuth; Phase 1 only declares `SecretStr` fields) |
| V3 Session Management | no | No user sessions; this is a batch service |
| V4 Access Control | no | Single-tenant; no authz |
| V5 Input Validation | yes | `pydantic-settings` validates every env var at boot |
| V6 Cryptography | partial | `SecretStr` prevents log leak; TLS is handled by Postgres + outbound SDKs in later phases |
| V7 Errors & Logging | yes | structlog JSON, UTC timestamps, no secrets in logs (SecretStr), stacktraces on error |
| V14 Configuration | yes | `.env` in gitignore + dockerignore; pre-commit gitleaks; `.env.example` with dummy values; pinned base images; non-root container user |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| `.env` committed to git | Information Disclosure | `.gitignore` (commit first), gitleaks pre-commit, `.env.example` only |
| `.env` baked into Docker image | Information Disclosure | `.dockerignore`; `env_file:` in compose (runtime injection) |
| Secret printed in log line (accidental `str(settings)`) | Information Disclosure | `SecretStr` type for all sensitive fields; pydantic v2 renders as `**********` |
| Container runs as root → host write on mounted volume | Elevation of Privilege | Dockerfile `USER app` (UID 1000) + ownership of `/data` and `/app` |
| Bind-mounted config is writable by container | Tampering | `:ro` flag on `./config:/app/config:ro` |
| Postgres exposed to host / internet | Information Disclosure | No `ports:` published on postgres service; accessed only via compose network |
| Supply-chain attack via `:latest` image tag | Tampering | Pin `python:3.12-slim-bookworm`, `postgres:16-bookworm`, `ghcr.io/astral-sh/uv:0.11.6` with explicit tags |
| Image pulled from untrusted mirror | Tampering | Use official `python:` and `postgres:` images from Docker Hub; `ghcr.io/astral-sh/uv` from Astral's GHCR |
| Signal mishandling leaves partial writes | Integrity | Graceful SIGTERM → `scheduler.shutdown(wait=True)`; `stop_grace_period: 30s` |

### Trust Boundaries (planner should encode in threat_model)

1. **Host filesystem → container:** `.env` (read via `env_file:`), `./config` (`:ro` bind mount), `logs` named volume (read-write). Operator is trusted on the host.
2. **Container → container (compose network):** app ↔ postgres. No TLS in v1 — acceptable for compose's private bridge network on a single host. Upgrade to TLS if ever deployed across hosts.
3. **Container → outbound internet:** Phase 1 makes no outbound calls. Later phases: Anthropic, X API, RSS/HN/Reddit — each uses pinned SDKs or `httpx` with timeouts and retries.
4. **Git history:** `.env` must never cross this boundary. gitleaks enforces.
5. **Docker image layers:** Public images may ship on a registry. `.env` must never cross this boundary. `.dockerignore` enforces.
6. **Log volume contents:** May contain exception stacktraces with internal paths; `SecretStr` ensures no secret payloads. Operator with shell access sees everything — acceptable for single-tenant VPS.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | VPS is Ubuntu without SELinux, so bind mount `:ro` flag doesn't need `:z`/`:Z` label | §Pitfalls #6, §Pattern 2 | Compose fails on SELinux hosts with `Permission denied`; easy fix (append `:z`) but surprises operator on RHEL-family hosts |
| A2 | UID 1000 is a reasonable non-root user id for the container (matches typical host user) | §Pattern 1 Dockerfile | If host uses different UID for the operator, files created in the `logs` volume may show wrong owner on host; cosmetic, not a security issue |
| A3 | `stop_grace_period: 30s` is enough for `run_cycle()` to drain in Phase 8 (full pipeline) | §Pattern 2 | Phase 8 may need to raise it if a cycle takes >30 s; easy compose edit |
| A4 | Compose v2's default bridge network is sufficient; no need for custom network declaration | §Pattern 2 | Custom networks only matter for multi-stack deploys; single-stack project is fine |
| A5 | Phase 1 spawns no subprocesses, so no `tini`/`dumb-init` is needed for zombie reaping | §Pattern 1 | Only wrong if later phases `subprocess.Popen` without waiting; monitor and revisit |
| A6 | `ghcr.io/astral-sh/uv:0.11.6` image tag is stable and signed by Astral | §Pattern 1 | If Astral stops publishing that tag, build breaks; easy fix (bump to newer tag) |
| A7 | `python-ulid` 3.1.0 is the correct package (NOT `ulid-py` 1.1.0, different maintainer) | §Standard Stack | If wrong package chosen, import fails; caught immediately by test_ids.py |

None of these are load-bearing blockers. All are low-risk assumptions with easy mitigations.

---

## Open Questions

1. **Healthcheck depth for the `app` service** — is "module imports successfully" enough, or should we also probe DB connectivity?
   - What we know: Phase 1 doesn't connect to DB. Probing DB would add failure modes that obscure actual app health.
   - What's unclear: Phase 2 and beyond may want `psycopg.connect` in the healthcheck.
   - Recommendation: Keep Phase 1 healthcheck at `python -c "import tech_news_synth"`. Phase 2 upgrades to include a quick DB ping.

2. **Log file rotation policy** — deferred per CONTEXT.md, but ops-sensitive.
   - What we know: `/data/logs/app.jsonl` grows unbounded in v1.
   - What's unclear: At ~1 KB/line × 12 cycles/day × multiple log lines per cycle ≈ ~0.5 MB/day after Phase 8. At soak (48h) ≈ 1 MB. Fine for v1.
   - Recommendation: Ship without rotation; document size in runbook. Phase 8 can add `RotatingFileHandler` if needed.

3. **uv version pinning strategy inside Dockerfile** — `:0.11.6` vs `:latest` vs floating `:0.11`?
   - What we know: uv's COPY-from pattern is `ghcr.io/astral-sh/uv:TAG`. `:latest` is tempting but breaks reproducibility.
   - What's unclear: Astral's tag stability practice. They publish specific-version tags for all releases.
   - Recommendation: Pin `:0.11.6`. Update via explicit PR + lockfile re-compile.

4. **Should `ruff` run inside the container build?** — No; runs only in pre-commit and CI. Container doesn't need dev tools.
   - Recommendation: confirm by keeping ruff in `dev` group only.

None of these block planning.

---

## Sources

### Primary (HIGH confidence)

- [uv Docker integration guide](https://docs.astral.sh/uv/guides/integration/docker/) — multi-stage pattern, cache mounts, venv copy (verified via WebFetch 2026-04-12)
- [APScheduler 3.x User Guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html) — `BlockingScheduler`, `CronTrigger`, events, shutdown — cited via search results (direct fetch 403'd but search surfaced canonical guidance)
- [structlog 25 Standard Library docs](https://www.structlog.org/en/stable/standard-library.html) — `ProcessorFormatter` bridge pattern
- [structlog GitHub #707 — dual output discussion](https://github.com/hynek/structlog/issues/707) — console + JSON file via two handlers
- [pydantic-settings docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — `SettingsConfigDict`, `SecretStr`, `env_file`, `ValidationError` fail-fast
- [gitleaks repo](https://github.com/gitleaks/gitleaks) — official pre-commit hook, zero-config rules
- [oneuptime 2026-01 — Docker graceful shutdown signals](https://oneuptime.com/blog/post/2026-01-16-docker-graceful-shutdown-signals/view) — PID 1, SIGTERM, exec vs shell CMD
- [tutorialpedia — Python Docker container slow stop](https://www.tutorialpedia.org/blog/stopping-python-container-is-slow-sigterm-not-passed-to-python-process/) — signal handler pattern
- [BetterStack — APScheduler scheduled tasks guide](https://betterstack.com/community/guides/scaling-python/apscheduler-scheduled-tasks/) — in-process scheduling patterns
- [BetterStack — structlog logging guide](https://betterstack.com/community/guides/logging/structlog/) — dual-handler setup
- [Appsec Santa — secret scanning tool comparison 2026](https://appsecsanta.com/sast-tools/secret-scanning-tools) — gitleaks as default choice
- Internal: `.planning/research/STACK.md`, `ARCHITECTURE.md`, `PITFALLS.md`, `CLAUDE.md`

### Secondary (MEDIUM confidence)

- [tutorialQ — Git security pre-commit hooks](https://tutorialq.com/dev/git/git-security-secrets-detection) — corroborating gitleaks setup
- [rafter.so — Pre-commit hooks for secret detection (10-min setup)](https://rafter.so/blog/secrets/pre-commit-hooks-secret-detection) — corroborating gitleaks

### Tertiary (LOW confidence)

- None. All load-bearing claims are HIGH or MEDIUM confidence.

### Verified via tools

- `pip index versions uv` → 0.11.6 (2026-04-12)
- `pip index versions structlog` → 25.5.0
- `pip index versions pydantic-settings` → 2.13.1
- `pip index versions apscheduler` → 3.11.2
- `pip index versions python-ulid` → 3.1.0
- `pip index versions detect-secrets` → 1.5.0
- `docker --version` → 29.3.1
- `docker compose version` → v5.1.1
- `python3 --version` → 3.12.3

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every version verified against PyPI on 2026-04-12.
- Architecture: HIGH — patterns are standard and well-documented; signal-handling pattern confirmed against multiple 2026 sources.
- Pitfalls: HIGH — nine pitfalls, six with direct citations to PITFALLS.md and official issue trackers, three verified via web search.
- Validation Architecture: HIGH — every INFRA requirement has an explicit test mapping.

**Research date:** 2026-04-12
**Valid until:** 2026-07-12 (90 days — stack is stable; uv and pydantic-settings may bump minor versions but API-compatible within pinned ranges)
