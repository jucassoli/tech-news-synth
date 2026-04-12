---
phase: 01-foundations
plan: 02
type: execute
wave: 2
depends_on:
  - "01-foundations/01"
files_modified:
  - src/tech_news_synth/scheduler.py
  - src/tech_news_synth/__main__.py
  - src/tech_news_synth/cli/__init__.py
  - src/tech_news_synth/cli/replay.py
  - src/tech_news_synth/cli/post_now.py
  - src/tech_news_synth/cli/source_health.py
  - Dockerfile
  - compose.yaml
  - config/sources.yaml.example
  - tests/unit/test_scheduler.py
  - tests/unit/test_cycle_error_isolation.py
  - tests/unit/test_signal_shutdown.py
autonomous: false   # contains one checkpoint:human-verify for docker compose up smoke
requirements:
  - INFRA-01
  - INFRA-05
  - INFRA-08

must_haves:
  truths:
    - "Running `python -m tech_news_synth` (with valid .env) starts a BlockingScheduler as PID 1, fires one no-op `run_cycle()` immediately, then fires again on the cron cadence dictated by INTERVAL_HOURS, always in UTC."
    - "An exception raised inside `run_cycle()` is logged with a full stacktrace on both stdout and the log file; the scheduler keeps ticking (next cycle fires on schedule)."
    - "SIGTERM to the main process calls `scheduler.shutdown(wait=True)` and exits cleanly under `stop_grace_period: 30s`."
    - "When the kill-switch is active, `run_cycle()` emits one JSON log line with `status=paused` and `paused_by` in {env, marker, both} and performs zero other I/O."
    - "Every log line inside a cycle carries `cycle_id=<ULID>` and `dry_run=<bool>` via structlog contextvars."
    - "`docker compose up -d` on a clean host brings `app` and `postgres` services to `healthy`, with named volumes `pgdata` and `logs` mounted, and `./config/` bind-mounted read-only."
    - "`python -m tech_news_synth replay|post-now|source-health` dispatches to a stub that logs `NotImplementedError: Phase 8` and exits non-zero — dispatcher is wired, bodies are stubs."
  artifacts:
    - path: "src/tech_news_synth/scheduler.py"
      provides: "build_scheduler(settings), run() entrypoint, run_cycle() no-op with try/except, _install_signal_handlers, _job_error_listener"
      contains: "BlockingScheduler"
    - path: "src/tech_news_synth/__main__.py"
      provides: "argparse dispatcher: no args → scheduler.run; subcommands → CLI stubs; catches ValidationError and exits 2"
      contains: "argparse"
    - path: "src/tech_news_synth/cli/replay.py"
      provides: "Stub that raises NotImplementedError (Phase 8)"
    - path: "src/tech_news_synth/cli/post_now.py"
      provides: "Stub that raises NotImplementedError (Phase 8)"
    - path: "src/tech_news_synth/cli/source_health.py"
      provides: "Stub that raises NotImplementedError (Phase 8)"
    - path: "Dockerfile"
      provides: "Multi-stage build: ghcr.io/astral-sh/uv:0.11.6 builder → python:3.12-slim-bookworm runtime; non-root user app (UID 1000); /data owned by app; HEALTHCHECK importing tech_news_synth; exec-form CMD"
      contains: "FROM python:3.12-slim-bookworm"
    - path: "compose.yaml"
      provides: "Compose v2 stack: app + postgres; named volumes pgdata + logs; ./config bind-mount :ro; env_file: .env; depends_on postgres healthy; stop_grace_period: 30s; stop_signal: SIGTERM; no ports on postgres"
      contains: "services:"
    - path: "config/sources.yaml.example"
      provides: "Stub YAML file (contents populated in Phase 4); its presence proves the bind mount path resolves"
  key_links:
    - from: "src/tech_news_synth/scheduler.py::run_cycle"
      to: "tech_news_synth.killswitch.is_paused + tech_news_synth.ids.new_cycle_id"
      via: "direct call at cycle start; bind cycle_id+dry_run to contextvars before any log line"
      pattern: "bind_contextvars.*cycle_id"
    - from: "src/tech_news_synth/scheduler.py::build_scheduler"
      to: "APScheduler CronTrigger(hour=f\"*/{settings.interval_hours}\", timezone=timezone.utc) + next_run_time=datetime.now(timezone.utc)"
      via: "scheduler.add_job with both trigger and next_run_time (D-07 first-tick-on-boot)"
      pattern: "next_run_time"
    - from: "src/tech_news_synth/__main__.py"
      to: "tech_news_synth.config.load_settings + tech_news_synth.logging.configure_logging + tech_news_synth.scheduler.run"
      via: "main() sequence: load settings → configure logging → dispatch"
      pattern: "def main"
    - from: "Dockerfile CMD"
      to: "python -m tech_news_synth"
      via: "exec form JSON array so Python is PID 1"
      pattern: "CMD \\[\"python\""
    - from: "compose.yaml app service"
      to: "postgres service"
      via: "depends_on: postgres: condition: service_healthy"
      pattern: "condition: service_healthy"
---

<objective>
Turn the pure-core modules from Plan 01 into a running, containerized, scheduled process. This plan delivers: (a) `scheduler.py` with a BlockingScheduler as PID 1, SIGTERM handlers, first-tick-on-boot + cron cadence, graceful exception isolation, and a no-op `run_cycle()` that honors the kill-switch and binds `cycle_id`+`dry_run` to structlog contextvars, (b) `__main__.py` argparse dispatcher (default → scheduler; `replay|post-now|source-health` → stubs), (c) CLI stub files for Phase 8, (d) multi-stage `Dockerfile` with uv + non-root + exec-form CMD, (e) Compose v2 stack with app + postgres + named volumes + health-gated startup + bind-mounted config.

Purpose: The chassis runs. Every later phase replaces the no-op body of `run_cycle()` with real work and inherits signal handling, exception isolation, logging context, and the kill-switch for free.

Output: `docker compose up -d` on a clean host yields two healthy containers; logs on stdout and `/data/logs/app.jsonl` show the first cycle firing immediately with its ULID `cycle_id`.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/REQUIREMENTS.md
@.planning/ROADMAP.md
@.planning/phases/01-foundations/01-CONTEXT.md
@.planning/phases/01-foundations/01-RESEARCH.md
@.planning/phases/01-foundations/01-VALIDATION.md
@.planning/phases/01-foundations/01-01-SUMMARY.md
@CLAUDE.md

<interfaces>
<!-- Inherited from Plan 01 — do NOT re-implement. Import and use. -->

From tech_news_synth.config:
```python
class Settings(BaseSettings): ...   # frozen, SecretStr-aware, interval_hours validated
def load_settings() -> Settings: ... # raises ValidationError on missing/invalid keys
```

From tech_news_synth.logging:
```python
def configure_logging(settings: Settings) -> None: ...   # idempotent, dual-output, UTC
def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger: ...
```

From tech_news_synth.ids:
```python
def new_cycle_id() -> str: ...   # 26-char Crockford base32 ULID
```

From tech_news_synth.killswitch:
```python
def is_paused(settings: Settings) -> tuple[bool, str | None]: ...
# returns (True, 'env' | 'marker' | 'both') or (False, None)
```

<!-- External contracts this plan consumes -->

APScheduler 3.11.x (pinned in Plan 01 pyproject):
```python
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR
scheduler = BlockingScheduler(timezone=timezone.utc, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 30})
scheduler.add_job(fn, CronTrigger(hour=f"*/{N}", timezone=timezone.utc), next_run_time=datetime.now(timezone.utc), id="run_cycle", replace_existing=True)
scheduler.add_listener(listener, EVENT_JOB_ERROR)
```
</interfaces>
</context>

<tasks>

<task type="auto" id="01.02.01" tdd="true">
  <name>Task 1: scheduler.py — BlockingScheduler PID 1, signal handlers, run_cycle no-op with kill-switch + exception isolation</name>
  <files>
    src/tech_news_synth/scheduler.py
    tests/unit/test_scheduler.py
    tests/unit/test_cycle_error_isolation.py
    tests/unit/test_signal_shutdown.py
  </files>
  <behavior>
    **test_scheduler.py (INFRA-05):**
    - Test 1 (build_scheduler): `build_scheduler(settings)` returns a `BlockingScheduler` whose `.timezone` is UTC; it has exactly one job registered with id `"run_cycle"`; the job's trigger is a `CronTrigger` with `hour="*/2"` when `settings.interval_hours=2`.
    - Test 2 (first-tick-on-boot — D-07): the registered job has `next_run_time` within 1 second of "now (UTC)" at registration time — proving first-tick-on-boot is wired via `next_run_time=datetime.now(timezone.utc)`.
    - Test 3 (interval respected): with `settings.interval_hours=6`, the trigger string is `hour="*/6"`.
    - Test 4 (kill-switch honored — INFRA-09 integration): monkeypatch `killswitch.is_paused` to return `(True, "env")`; call `run_cycle(settings)` directly; capture logs; assert exactly one log line with `event="cycle_skipped"` (or equivalent) AND `status="paused"` AND `paused_by="env"`; assert no other logs except cycle_start/cycle_end bracketing is emitted, and NO DB/network activity occurs (easy to assert: use respx or mock — but Phase 1 has no I/O yet, so just assert single "paused" log + return).
    - Test 5 (cycle_id + dry_run bound — INFRA-07/INFRA-10): call `run_cycle(settings)` with `settings.dry_run=True` (not paused); parse all log lines emitted during the call; assert every line contains a `cycle_id` (26-char) AND `dry_run=true`. After `run_cycle` returns, `clear_contextvars` was called — a subsequent log line does NOT have `cycle_id`.

    **test_cycle_error_isolation.py (INFRA-08):**
    - Test 1: Define a raising `run_cycle_body` that throws `RuntimeError("boom")`. Wrap `run_cycle` so its body raises. Call it; assert:
      (a) No exception propagates to caller.
      (b) At least one log line has `event="cycle_error"` (or `"cycle_exception"`) AND contains `exception` / `stack_info` fields with "boom" and a traceback.
      (c) Scheduler continues: invoke a fake second tick; it runs normally (no crash).
    - Test 2 (belt-and-suspenders EVENT_JOB_ERROR listener): construct a BlockingScheduler via `build_scheduler`, register a raising test job, use APScheduler's test helpers (or a real short-lived `BackgroundScheduler` swap for testability) to fire the listener; assert the listener logs `event="scheduler_job_error"` with the exception text. (If `BlockingScheduler` is awkward to test directly, verify the listener function in isolation given a mock `JobExecutionEvent`.)

    **test_signal_shutdown.py (cross-cutting SIGTERM / INFRA-05+INFRA-08):**
    - Test 1: Construct a scheduler and call the private `_install_signal_handlers(scheduler)`. Use `signal.getsignal(signal.SIGTERM)` to retrieve the installed handler; assert it's callable and NOT `signal.SIG_DFL` / `SIG_IGN`.
    - Test 2: Mock `scheduler.shutdown`. Invoke the installed handler with `(signal.SIGTERM, None)` directly. Assert `scheduler.shutdown` was called exactly once with `wait=True`. Invoke the SIGINT handler similarly; assert `shutdown` called once more (total 2). (This proves both handlers wire to the same cleanup.)
  </behavior>
  <action>
Write all three test files first (RED), then implement `scheduler.py` per RESEARCH.md Pattern 3. Replace the red-stub files from Plan 01 Task 5 with real tests.

**scheduler.py** — the canonical pattern, fully specified in RESEARCH.md §Pattern 3. Key structural requirements:

```python
from __future__ import annotations

import signal
import sys
from datetime import datetime, timezone

from apscheduler.events import EVENT_JOB_ERROR, JobExecutionEvent
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from structlog.contextvars import bind_contextvars, clear_contextvars

from tech_news_synth.config import Settings
from tech_news_synth.ids import new_cycle_id
from tech_news_synth.killswitch import is_paused
from tech_news_synth.logging import configure_logging, get_logger

log = get_logger(__name__)


def run_cycle(settings: Settings) -> None:
    """
    Phase 1: no-op cycle. Logs start + (pause|end), nothing else.
    Later phases replace the body between cycle_start and cycle_end.

    Invariants:
      - Never raises (INFRA-08). All exceptions caught and logged with stacktrace.
      - Binds cycle_id (ULID) and dry_run into structlog contextvars (INFRA-07 / INFRA-10).
      - Honors kill-switch first thing (INFRA-09); zero I/O when paused.
      - Clears contextvars on exit (so shutdown lines don't carry stale cycle_id).
    """
    cycle_id = new_cycle_id()
    bind_contextvars(cycle_id=cycle_id, dry_run=bool(settings.dry_run))
    try:
        paused, reason = is_paused(settings)
        if paused:
            log.info("cycle_skipped", status="paused", paused_by=reason)
            return

        log.info("cycle_start", interval_hours=settings.interval_hours)
        try:
            # Phase 1 no-op. Later phases insert: fetch → cluster → synth → publish.
            pass
        except Exception:
            # INFRA-08: never propagate; log full stacktrace.
            log.exception("cycle_error")
            return
        log.info("cycle_end", status="ok")
    finally:
        clear_contextvars()


def _job_error_listener(event: JobExecutionEvent) -> None:
    """Safety net (PITFALLS #7) — run_cycle's try/except should catch everything,
    but if anything slips past, APScheduler's EVENT_JOB_ERROR fires here."""
    log.error(
        "scheduler_job_error",
        exception=str(event.exception),
        traceback=event.traceback,
        job_id=event.job_id,
    )


def build_scheduler(settings: Settings) -> BlockingScheduler:
    """D-07: first tick immediately, then cron cadence."""
    scheduler = BlockingScheduler(
        timezone=timezone.utc,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 30},
    )
    scheduler.add_listener(_job_error_listener, EVENT_JOB_ERROR)
    scheduler.add_job(
        run_cycle,
        CronTrigger(hour=f"*/{settings.interval_hours}", timezone=timezone.utc),
        kwargs={"settings": settings},
        id="run_cycle",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),  # D-07 first-tick-on-boot
    )
    return scheduler


def _install_signal_handlers(scheduler: BlockingScheduler) -> None:
    """Critical: Python doesn't auto-exit on SIGTERM. Without this, docker stop
    waits stop_grace_period then SIGKILLs mid-cycle. (RESEARCH.md PITFALLS #1)"""
    def _shutdown(signum: int, frame) -> None:  # noqa: ARG001
        log.info("shutdown_signal_received", signal=signal.Signals(signum).name)
        scheduler.shutdown(wait=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)


def run(settings: Settings) -> None:
    """Entrypoint called by __main__.py when no subcommand is given."""
    configure_logging(settings)
    scheduler = build_scheduler(settings)
    _install_signal_handlers(scheduler)
    log.info(
        "scheduler_starting",
        interval_hours=settings.interval_hours,
        dry_run=bool(settings.dry_run),
        paused_env=bool(settings.paused),
    )
    scheduler.start()   # blocks until shutdown
```

**Critical points (do not deviate):**
- `BlockingScheduler`, NOT `BackgroundScheduler` (scheduler IS the process — PID 1).
- `timezone=timezone.utc` on BOTH the scheduler and the CronTrigger (PITFALLS #7).
- `next_run_time=datetime.now(timezone.utc)` for D-07 first-tick — simpler than manual pre-start call, avoids double-fire.
- Exec-form CMD in Dockerfile (Task 2) is what makes this work — signal handlers require Python as PID 1.
- `clear_contextvars()` in `finally` — otherwise logs emitted during shutdown still carry the last cycle's cycle_id, which is misleading.
- `coalesce=True` + `max_instances=1` — if the host was paused (laptop sleep) and 3 cycles missed, fire one catch-up, not three.

**Testing note:** Tests should NOT start the BlockingScheduler (it blocks). Test `build_scheduler` by inspection (`scheduler.get_jobs()`, `scheduler._jobstore_list`, `job.next_run_time`, `job.trigger`) and test `run_cycle` / `_job_error_listener` / `_install_signal_handlers` directly as pure functions.

**Decision refs:** D-07 (first tick), D-08 (kill-switch consumption), D-09 (ULID cycle_id), D-10 (DRY_RUN bound); INFRA-05, INFRA-07, INFRA-08, INFRA-09, INFRA-10.

**Threat refs:** T-02-01-sigterm-eaten (mitigated by signal handlers + Task 2's exec-form CMD), T-02-02-exception-propagation (mitigated by try/except + EVENT_JOB_ERROR listener), T-02-03-stale-contextvars (mitigated by `clear_contextvars` in finally), T-02-04-crontrigger-wrong-tz (mitigated by explicit `timezone=timezone.utc` on both scheduler and trigger).
  </action>
  <verify>
<automated>uv run pytest tests/unit/test_scheduler.py tests/unit/test_cycle_error_isolation.py tests/unit/test_signal_shutdown.py -q</automated>
  </verify>
  <done>
    - All behavior tests pass.
    - `run_cycle(settings)` never raises regardless of what its body does.
    - Signal handlers are installed for both SIGTERM and SIGINT.
    - CronTrigger uses UTC and the configured `interval_hours`.
    - First-tick-on-boot verified by `next_run_time` being ≈ now.
    - ruff clean.
  </done>
</task>

<task type="auto" id="01.02.02">
  <name>Task 2: __main__.py dispatcher + CLI stubs + Dockerfile (multi-stage with uv) + sources.yaml.example</name>
  <files>
    src/tech_news_synth/__main__.py
    src/tech_news_synth/cli/__init__.py
    src/tech_news_synth/cli/replay.py
    src/tech_news_synth/cli/post_now.py
    src/tech_news_synth/cli/source_health.py
    Dockerfile
    config/sources.yaml.example
  </files>
  <action>
Wire the entrypoint and the container image. These bind together into one task because the Dockerfile's `CMD ["python", "-m", "tech_news_synth"]` is useless without `__main__.py`, and `__main__.py` is untested without the image that boots it.

**src/tech_news_synth/__main__.py** (per RESEARCH.md Pattern 7 + D-05/D-06):
```python
"""Entrypoint: `python -m tech_news_synth [subcommand]`."""
from __future__ import annotations

import argparse
import sys

from pydantic import ValidationError


def _dispatch_scheduler() -> None:
    from tech_news_synth.config import load_settings
    from tech_news_synth.scheduler import run

    try:
        settings = load_settings()
    except ValidationError as e:
        # Printed to stderr BEFORE configure_logging runs — intentional (PITFALLS #5).
        print(f"Configuration error:\n{e}", file=sys.stderr)
        sys.exit(2)

    run(settings)


def _dispatch_cli(subcommand: str, argv: list[str]) -> int:
    # Phase 1 ships stubs; Phase 8 implements bodies. Dispatcher is live today.
    if subcommand == "replay":
        from tech_news_synth.cli import replay
        return replay.main(argv)
    if subcommand == "post-now":
        from tech_news_synth.cli import post_now
        return post_now.main(argv)
    if subcommand == "source-health":
        from tech_news_synth.cli import source_health
        return source_health.main(argv)
    raise SystemExit(f"Unknown subcommand: {subcommand}")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        prog="python -m tech_news_synth",
        description="tech-news-synth — autonomous tech-news synthesizer for @ByteRelevant",
    )
    sub = parser.add_subparsers(dest="subcommand")
    sub.add_parser("replay", help="Re-run synthesis on a past cycle (Phase 8)")
    sub.add_parser("post-now", help="Force an off-cadence cycle (Phase 8)")
    sub.add_parser("source-health", help="Show per-source fetch status (Phase 8)")

    args, rest = parser.parse_known_args(argv)
    if args.subcommand is None:
        _dispatch_scheduler()   # default: run scheduler (D-06)
        return 0
    return _dispatch_cli(args.subcommand, rest)


if __name__ == "__main__":
    raise SystemExit(main())
```

**src/tech_news_synth/cli/__init__.py**: empty.

**src/tech_news_synth/cli/replay.py**:
```python
"""replay CLI stub — implemented in Phase 8 (OPS-02)."""
def main(argv: list[str]) -> int:
    raise NotImplementedError("replay CLI is implemented in Phase 8 (OPS-02)")
```

**src/tech_news_synth/cli/post_now.py** and **cli/source_health.py**: same pattern with their respective OPS IDs (OPS-03, OPS-04).

**config/sources.yaml.example** — stub file proving the bind-mount path resolves (Phase 4 fills real content):
```yaml
# tech-news-synth — sources configuration (Phase 4 populates this).
# Copy to config/sources.yaml before first run.
# Schema defined in Phase 4 (INGEST-01).
version: 1
sources: []
```

**Dockerfile** (verbatim structure from RESEARCH.md Pattern 1 with pinned tags):
```dockerfile
# syntax=docker/dockerfile:1.7

# --- builder stage: uv resolves deps into /app/.venv from the lockfile ---
FROM python:3.12-slim-bookworm AS builder

# Pin uv via official image (tag locked per A6)
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Layer 1: deps-only (maximizes cache hits on source edits)
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Layer 2: project install
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- runtime stage: slim, no build tools, non-root ---
FROM python:3.12-slim-bookworm AS runtime

# Non-root user (T-02-05: never run container as root)
RUN groupadd --system --gid 1000 app \
 && useradd --system --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Copy venv + source from builder
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src

# Data directory for logs + paused marker (volume mount target)
RUN mkdir -p /data/logs /app/config \
 && chown -R app:app /data /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

USER app

# INFRA-01 healthcheck — lightweight import smoke, no DB dependency (see RESEARCH Open Q #1).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import tech_news_synth" || exit 1

# Exec form — CRITICAL for SIGTERM propagation (PITFALLS #2).
CMD ["python", "-m", "tech_news_synth"]
```

**Verification subtleties:**
- Build cache: `uv sync --frozen --no-dev --no-install-project` layer is cached across source changes — only `pyproject.toml` / `uv.lock` edits bust it.
- `PYTHONPATH=/app/src` makes `src/tech_news_synth` importable without an editable install.
- Healthcheck is intentionally shallow (import smoke). Phase 2 will extend it to probe DB.
- No `tini`/`dumb-init` — Phase 1 spawns no subprocesses (A5), so native Python signal handling is sufficient and simpler.

**Decision refs:** D-04 (multi-stage uv), D-05 (entrypoint), D-06 (subcommand dispatcher skeleton, stubs live).

**Threat refs:**
- T-02-05-root-container: mitigated by `USER app` (UID 1000).
- T-02-06-image-supply-chain: mitigated by pinned tags (`python:3.12-slim-bookworm`, `ghcr.io/astral-sh/uv:0.11.6`).
- T-02-07-shell-form-cmd: mitigated by exec-form CMD.
- T-02-08-env-leaked-to-image: mitigated by `.dockerignore` from Plan 01 Task 1.
  </action>
  <verify>
<automated>docker build --target runtime -t tns:test . && docker run --rm tns:test python -c "import sys, tech_news_synth; assert sys.version_info[:2]==(3,12), sys.version_info" && docker run --rm tns:test python -m tech_news_synth --help 2>&1 | grep -q "replay"</automated>
  </verify>
  <done>
    - `docker build --target runtime` succeeds.
    - Runtime image's Python is 3.12.
    - `python -m tech_news_synth --help` lists subcommands `replay`, `post-now`, `source-health`.
    - Running `python -m tech_news_synth replay` inside the image raises NotImplementedError with "Phase 8" in the message (manual check).
    - `docker history tns:test` shows no layer containing `.env` or secret material (manual inspection — threat T-02-08 verification).
    - Image runs as UID 1000 (`docker run --rm tns:test id -u` → `1000`).
  </done>
</task>

<task type="auto" id="01.02.03">
  <name>Task 3: compose.yaml — app + postgres with volumes, healthchecks, bind mount, graceful stop</name>
  <files>
    compose.yaml
  </files>
  <action>
Create the Compose v2 topology per RESEARCH.md Pattern 2.

```yaml
# Compose v2 — no version: key.
name: tech-news-synth

services:
  postgres:
    image: postgres:16-bookworm   # pinned (threat T-02-06 supply chain)
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-tech_news_synth}
      POSTGRES_USER: ${POSTGRES_USER:-app}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-app} -d ${POSTGRES_DB:-tech_news_synth}"]
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 10s
    # INFRA-01: no `ports:` — Postgres reachable only on the compose bridge network.
    # (Threat T-02-09 postgres-exposed-to-host: mitigated by omission.)
    stop_grace_period: 30s

  app:
    build:
      context: .
      dockerfile: Dockerfile
      target: runtime
    image: tech-news-synth:local
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    env_file:
      - .env                          # INFRA-03 source of truth for secrets
    volumes:
      - logs:/data                    # INFRA-07 logs + INFRA-09 paused marker
      - ./config:/app/config:ro       # D-03 bind-mount read-only (threat T-02-10 tampered config)
    # Healthcheck defined in Dockerfile (HEALTHCHECK directive).
    stop_grace_period: 30s            # > default 10s — lets scheduler.shutdown(wait=True) drain
    stop_signal: SIGTERM

volumes:
  pgdata:
    name: tech-news-synth_pgdata
  logs:
    name: tech-news-synth_logs

# No explicit `networks:` — Compose auto-creates tech-news-synth_default (bridge).
```

**Subtleties:**
- `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?...}` — Compose fails to start if the host env has no value. Complements `env_file: .env` (Compose reads `.env` into its own env first so `${VAR}` interpolation works).
- `condition: service_healthy` — `app` waits for `pg_isready` to succeed, not just for Postgres to start accepting TCP.
- `stop_grace_period: 30s` matches A3; Phase 8 re-evaluates if real cycles need longer.
- `./config:/app/config:ro` — `:ro` is defense in depth against a bug in the app writing to the config dir. Ubuntu VPS (no SELinux per A1), so no `:z`/`:Z` needed; document in DEPLOY.md (Phase 8).
- `name:` on volumes makes them predictable (`tech-news-synth_pgdata`, `tech-news-synth_logs`).
- No `ports:` on postgres — host access for DB tooling is operator's explicit choice via `docker compose exec postgres psql ...` or by temporarily uncommenting.

**Decision refs:** D-03 (bind-mount :ro), D-04 (image target runtime), D-08 (marker file in /data = logs volume).

**Threat refs:**
- T-02-06-supply-chain: pinned `postgres:16-bookworm`.
- T-02-09-postgres-exposed: no `ports:` published; compose bridge network only.
- T-02-10-config-tampered: `:ro` on bind mount.
- T-02-11-sigterm-killed: `stop_grace_period: 30s` + `stop_signal: SIGTERM` aligns with scheduler.shutdown(wait=True).
  </action>
  <verify>
<automated>docker compose config --quiet && grep -qE "stop_grace_period: 30s" compose.yaml && grep -qE "condition: service_healthy" compose.yaml && grep -qE "\./config:/app/config:ro" compose.yaml && ! grep -qE "^\s+ports:\s*$" compose.yaml</automated>
  </verify>
  <done>
    - `docker compose config` parses the file cleanly (exit 0).
    - `depends_on: postgres: condition: service_healthy` present on app service.
    - `./config:/app/config:ro` bind mount present.
    - No `ports:` section on postgres service.
    - Named volumes `pgdata` and `logs` both declared with predictable names.
  </done>
</task>

<task type="checkpoint:human-verify" id="01.02.04" gate="blocking">
  <name>Task 4: Docker Compose smoke test — `docker compose up` on clean host</name>
  <what-built>
    Plans 01+02 combined produce: a running two-container stack (`app` + `postgres`), both healthy, with:
    - Persistent named volumes for DB data and logs
    - App running as UID 1000 with BlockingScheduler as PID 1
    - First no-op `run_cycle()` fired immediately on boot
    - Cron cadence `hour="*/2"` (or whatever `INTERVAL_HOURS` is set to) taking over for subsequent ticks
    - JSON logs on stdout AND `/data/logs/app.jsonl` with `cycle_id` + `dry_run` on every line
    - Kill-switch (PAUSED env + `/data/paused` marker) functional
    - Graceful SIGTERM shutdown under 30s
  </what-built>
  <how-to-verify>
    **Pre-reqs:** Docker Engine ≥ 26, Docker Compose v2, `uv` on dev machine.

    1. **Clean environment:**
       ```bash
       docker compose down -v 2>/dev/null   # remove any prior state (destructive — fresh test)
       cp .env.example .env
       # Edit .env: set real dummy values for all SecretStr fields (any non-empty string works for Phase 1 — no external calls yet).
       # Set INTERVAL_HOURS=2, DRY_RUN=1, PAUSED=0.
       ```

    2. **Build and start:**
       ```bash
       docker compose up -d --build
       ```
       Expect: build succeeds, both services start.

    3. **Health gate (wait ~30s then check):**
       ```bash
       docker compose ps
       ```
       Expected output: both `app` and `postgres` show `Up ... (healthy)`. If `postgres` is `starting`, wait 10 more seconds and re-check.

    4. **Volumes exist:**
       ```bash
       docker volume ls | grep tech-news-synth
       ```
       Expected: `tech-news-synth_pgdata` and `tech-news-synth_logs` both present.

    5. **First cycle fired immediately (D-07):**
       ```bash
       docker compose logs app | head -30
       ```
       Expected JSON lines (in order):
       - `{"event":"scheduler_starting","interval_hours":2,"dry_run":true,"paused_env":false,...}`
       - `{"event":"cycle_start","cycle_id":"<26-char ULID>","dry_run":true,"interval_hours":2,...}`
       - `{"event":"cycle_end","cycle_id":"<same ULID>","dry_run":true,"status":"ok",...}`

       Verify: every line after `scheduler_starting` has a `cycle_id` AND `dry_run=true`. Timestamps end in `+00:00` (UTC).

    6. **Logs written to volume (INFRA-07 dual output):**
       ```bash
       docker compose exec app tail -n 5 /data/logs/app.jsonl | python -m json.tool --no-ensure-ascii | head -5
       ```
       Expected: each line is valid JSON with the same `cycle_id` and `dry_run` fields as stdout.

    7. **Kill-switch live toggle (INFRA-09 — marker file):**
       ```bash
       docker compose exec app touch /data/paused
       # Wait until the next cron tick (up to INTERVAL_HOURS). For a faster test, set INTERVAL_HOURS=1 in .env and `docker compose up -d` to restart.
       # OR: `docker compose restart app` — restart triggers first-tick-on-boot (D-07), which will observe the marker.
       docker compose logs app --tail 10
       ```
       Expected: a line like `{"event":"cycle_skipped","status":"paused","paused_by":"marker","cycle_id":"...","dry_run":true,...}`. Remove marker: `docker compose exec app rm /data/paused` → next cycle runs normally.

    8. **Kill-switch env toggle (INFRA-09 — PAUSED env):**
       ```bash
       # Edit .env: PAUSED=1, then:
       docker compose up -d
       docker compose logs app --tail 10
       ```
       Expected: next cycle logs `paused_by=env`. With marker still present from step 7 (if not removed), `paused_by=both`.

    9. **Fail-fast on missing secret (INFRA-03):**
       ```bash
       cp .env .env.backup
       sed -i '/^ANTHROPIC_API_KEY=/d' .env
       docker compose up -d app 2>&1 | tail -20
       docker compose logs app --tail 20
       ```
       Expected: app container exits non-zero; logs contain `Configuration error:` on stderr, naming `anthropic_api_key` as missing. Restore: `mv .env.backup .env && docker compose up -d`.

    10. **Graceful SIGTERM shutdown (INFRA-08 cross-check):**
        ```bash
        time docker compose down
        ```
        Expected: completes in under 10s (well inside `stop_grace_period: 30s`). If it takes exactly 30s, signal handlers are NOT installed correctly — investigate.

    11. **Exception isolation (INFRA-08 — manual injection):**
        Temporarily edit `src/tech_news_synth/scheduler.py` `run_cycle` to insert `raise RuntimeError("smoke-test")` right after `log.info("cycle_start"...)`. Rebuild and run:
        ```bash
        docker compose up -d --build
        sleep 5
        docker compose logs app --tail 30
        ```
        Expected: one `cycle_error` log line with a full stacktrace containing `"smoke-test"`; scheduler stays up (no crash loop). Revert the edit and rebuild.

    **Cleanup:** `docker compose down -v` (destroys volumes — fine for Phase 1).

    **If any step fails:** Resume with "failed at step N: {observation}" and we'll triage.
  </how-to-verify>
  <resume-signal>Type "approved" if all 11 steps pass, or describe any step that failed.</resume-signal>
</task>

</tasks>

<validation_refs>
Per `.planning/phases/01-foundations/01-VALIDATION.md`:

| Task | Requirement | Automated Command (from VALIDATION.md) |
|------|-------------|----------------------------------------|
| 01.02.01 | INFRA-05, INFRA-08 | `uv run pytest tests/unit/test_scheduler.py tests/unit/test_cycle_error_isolation.py tests/unit/test_signal_shutdown.py -q` |
| 01.02.02 | INFRA-02 (image build path) | `docker build --target runtime -t tns:test .` + Python version assert |
| 01.02.03 | INFRA-01 (compose structural) | `docker compose config --quiet` |
| 01.02.04 | INFRA-01 + INFRA-09 integration + INFRA-03 fail-fast + SIGTERM manual | Manual checkpoint (only reproducible with Docker daemon) |

After all tasks: full suite `uv run pytest tests/ -v --cov=tech_news_synth` — must be green with zero skips (Plan 01's red-stub skips have been replaced with real tests).
</validation_refs>

<threat_model>
## Trust Boundaries (delta from Plan 01)

| Boundary | Description |
|----------|-------------|
| Host OS → container process | SIGTERM from `docker stop` crosses here; Python signal handlers are the only defense against data loss mid-cycle |
| Compose network (bridge) → app container | Postgres accessed over internal DNS (`postgres:5432`), no TLS — acceptable for single-host deployment |
| Image registry → local Docker cache | `python:3.12-slim-bookworm`, `postgres:16-bookworm`, `ghcr.io/astral-sh/uv:0.11.6` crossed only at build/pull time |
| Container PID namespace → kernel | `USER app` (UID 1000) restricts what a container escape could do; no CAP_SYS_ADMIN requested |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-02-01-sigterm-eaten | Denial of Service / Integrity | Python PID 1 without signal handler | mitigate | `_install_signal_handlers()` installs SIGTERM+SIGINT → `scheduler.shutdown(wait=True)` + `sys.exit(0)` (Task 1). `test_signal_shutdown.py` verifies handlers installed and call shutdown exactly once (Task 1). |
| T-02-02-exception-propagation | Denial of Service (crash loop) | `run_cycle()` exception propagating to scheduler | mitigate | try/except wrap inside `run_cycle` + `EVENT_JOB_ERROR` listener as safety net (Task 1). `test_cycle_error_isolation.py` exercises both paths. |
| T-02-03-stale-contextvars | Integrity (log misattribution) | `cycle_id` leaking from one cycle into shutdown logs or the next cycle's early steps | mitigate | `clear_contextvars()` in `finally` of `run_cycle` (Task 1); `new_cycle_id()` fresh per cycle. Test 5 of test_scheduler.py verifies. |
| T-02-04-crontrigger-wrong-tz | Integrity (cadence contract drift) | `CronTrigger` using system TZ if `timezone=` omitted | mitigate | Explicit `timezone=timezone.utc` on BOTH `BlockingScheduler` and `CronTrigger` (Task 1); no `TZ=` env var anywhere in Dockerfile or compose (Tasks 2+3). PITFALLS #7. |
| T-02-05-root-container | Elevation of Privilege | Container running as root → host write via volume escape | mitigate | `USER app` (UID 1000) in Dockerfile (Task 2); `chown -R app:app /data /app`. Threat register item from RESEARCH.md §Security Domain. |
| T-02-06-image-supply-chain | Tampering | `:latest` tags can be re-pointed; unsigned mirrors | mitigate | Pinned tags: `python:3.12-slim-bookworm`, `postgres:16-bookworm`, `ghcr.io/astral-sh/uv:0.11.6` (Tasks 2+3). A6 acknowledges Astral tag stability assumption. |
| T-02-07-shell-form-cmd | Denial of Service (SIGTERM loss — cousin of T-02-01) | `CMD python -m tech_news_synth` interpreted as `/bin/sh -c ...` making shell PID 1 | mitigate | Exec-form JSON array `CMD ["python", "-m", "tech_news_synth"]` in Dockerfile (Task 2). PITFALLS #2. |
| T-02-08-env-leaked-to-image | Information Disclosure | `COPY . .` pulling `.env` into an image layer | mitigate | `.dockerignore` from Plan 01 Task 1 excludes `.env`. Dockerfile only `COPY`s `pyproject.toml`, `uv.lock`, and `src/` — never `.`. Manual `docker history` check in Task 4 step 5 (Task 2 done criterion). |
| T-02-09-postgres-exposed | Information Disclosure | Postgres port 5432 published to host → accessible from LAN | mitigate | No `ports:` section on `postgres` service in compose.yaml (Task 3). Access only via `docker compose exec postgres psql` or compose bridge network. |
| T-02-10-config-tampered | Tampering | App code writing to `./config/sources.yaml` → drift between git and runtime | mitigate | `:ro` flag on `./config:/app/config:ro` bind mount (Task 3). Any write attempt raises `OSError` — caught at boot (Phase 4) or at cycle (Phase 4+). |
| T-02-11-sigterm-killed | Integrity (half-completed cycle) | Docker sends SIGKILL after `stop_grace_period` if SIGTERM handler too slow | mitigate | `stop_grace_period: 30s` on app service (Task 3) — greater than default 10s. `scheduler.shutdown(wait=True)` in signal handler waits for in-flight job. A3 acknowledges 30s is likely sufficient; revisit in Phase 8. |
| T-02-12-healthcheck-false-green | Integrity (operator trusts a broken service) | `HEALTHCHECK CMD python -c "import tech_news_synth"` passes even if the scheduler crashed | accept | In Phase 1, import smoke is the deepest check we can do without a DB. Phase 2 extends healthcheck to include a DB ping. Open Question #1 in RESEARCH.md captures this. Low severity because crash-loop logs are visible in `docker compose logs`. |
| T-02-13-crontrigger-stride-trap | Integrity (cadence contract) | Operator sets `INTERVAL_HOURS=5` expecting 5h periods; cron fires at 00,05,10,15,20 then 00 (4h gap) | mitigate | `Settings.interval_hours` validator rejects non-divisors of 24 at boot (Plan 01 Task 2, cross-plan reference). PITFALLS #3. |

**ASVS coverage (delta):** V7 (error logs with stacktraces, no secret payloads) — T-02-02, T-02-03. V10 (Malicious Code — supply chain) — T-02-06. V13 (API) — N/A Phase 1. V14 (Config — container hardening) — T-02-05, T-02-07, T-02-08, T-02-09, T-02-10.

**Accepted risks:** T-02-12 (shallow healthcheck) — accepted for Phase 1, owner: Phase 2 will upgrade. Documented in Open Questions #1.
</threat_model>

<verification>
After all 4 tasks:

1. **Full unit suite green, zero skips:**
   ```bash
   uv run pytest tests/ -v --cov=tech_news_synth --cov-report=term-missing
   ```
   Coverage target ≥80% on `scheduler.py`, `config.py`, `logging.py`, `killswitch.py`, `ids.py`.

2. **Lint clean:**
   ```bash
   uv run ruff check . && uv run ruff format --check .
   ```

3. **Image builds cleanly:**
   ```bash
   docker build --target runtime -t tns:test .
   ```

4. **Compose config valid:**
   ```bash
   docker compose config --quiet
   ```

5. **Manual compose-up smoke** (Task 4 checkpoint): all 11 steps pass.

6. **Requirement coverage check** (every INFRA requirement has a green automated or checkpoint verify):
   - INFRA-01: Task 4 steps 2–4 (compose up, healthy, volumes)
   - INFRA-02: Task 2 (image build, Python 3.12 assert)
   - INFRA-03: Task 4 step 9 (fail-fast missing env)
   - INFRA-04: Plan 01 Task 5 test_secrets_hygiene + pre-commit gitleaks
   - INFRA-05: Task 1 test_scheduler (UTC + CronTrigger + interval) + Task 4 step 5 (first-tick-on-boot observed)
   - INFRA-06: Plan 01 Task 4 test_utc_invariants + Task 4 step 5 (UTC timestamps in logs)
   - INFRA-07: Plan 01 Task 4 test_logging + Task 4 step 6 (dual output observed)
   - INFRA-08: Task 1 test_cycle_error_isolation + Task 4 step 11 (injected exception, scheduler survives)
   - INFRA-09: Task 1 test_scheduler Test 4 + Task 4 steps 7–8 (marker + env triggers observed)
   - INFRA-10: Plan 01 Task 4 test_dry_run_logging + Task 4 step 5 (`dry_run=true` on every line)
</verification>

<success_criteria>
This plan (and therefore Phase 1) is complete when:

1. `docker compose up -d` on a clean host brings `app` and `postgres` to `healthy` within 30s with named volumes created.
2. `docker compose logs app` shows the `scheduler_starting` line followed by an immediate `cycle_start` / `cycle_end` pair carrying a ULID `cycle_id` and `dry_run=<bool>`; subsequent cycles fire on the configured cron cadence.
3. Removing a required env var and restarting `app` produces a `Configuration error:` stderr line naming the missing field and exits non-zero.
4. Setting `PAUSED=1` OR creating `/data/paused` causes the next cycle to emit one `cycle_skipped` log line with the correct `paused_by` reason and do nothing else.
5. Injecting `raise RuntimeError(...)` inside `run_cycle` body produces a `cycle_error` log line with stacktrace but does NOT stop the scheduler — the next tick fires normally.
6. `docker compose down` completes in under 10s (graceful SIGTERM shutdown well inside the 30s grace period).
7. `uv run pytest tests/ -v` — 100% of tests pass (no skips — Plan 01's red stubs are now real and green).
8. Every requirement ID INFRA-01..INFRA-10 is backed by a passing automated test OR a completed checkpoint step.
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundations/01-02-SUMMARY.md` documenting:
- Final file tree produced by Plans 01+02 (matches RESEARCH.md §Code Examples summary table ~650 LOC / ~250 test LOC)
- Actual image size (`docker images tns:test`) and build time (layer cache hit/miss summary)
- Confirmation that `next_run_time` first-tick trick works in practice (Task 4 step 5 log evidence)
- Any deviations from RESEARCH.md Pattern 1/2/3 and rationale
- Any PITFALLS hit during smoke (from Task 4)
- Handoff note to Phase 2: `compose.yaml` postgres service + `/data` volume + `env_file:` + `app` import root are the integration points Alembic work will build on; `run_cycle()` body is still a no-op ready for Phase 2 to add `alembic upgrade head` at container startup (via entrypoint script or a separate one-shot `migrate` service — Phase 2 decides).

Phase transition: after this plan's SUMMARY lands, `/gsd-transition` moves the roadmap to Phase 2.
</output>
