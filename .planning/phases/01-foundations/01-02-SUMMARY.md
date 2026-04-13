---
phase: 01-foundations
plan: 02
subsystem: foundations
tags: [scheduler, apscheduler, docker, compose, signal-handlers, cli]
status: complete
requirements:
  - INFRA-01
  - INFRA-05
  - INFRA-08
dependency-graph:
  requires:
    - tech_news_synth.config.Settings
    - tech_news_synth.config.load_settings
    - tech_news_synth.logging.configure_logging
    - tech_news_synth.logging.get_logger
    - tech_news_synth.ids.new_cycle_id
    - tech_news_synth.killswitch.is_paused
  provides:
    - tech_news_synth.scheduler.build_scheduler
    - tech_news_synth.scheduler.run_cycle
    - tech_news_synth.scheduler.run
    - tech_news_synth.scheduler._install_signal_handlers
    - tech_news_synth.scheduler._job_error_listener
    - tech_news_synth.__main__.main (argparse dispatcher)
    - Dockerfile (multi-stage uv builder + python:3.12-slim runtime)
    - compose.yaml (app + postgres stack)
  affects:
    - phase-02-storage (Alembic consumes postgres service + /data volume; app import root ready)
tech-stack:
  added:
    - docker compose v2 topology
    - postgres:16-bookworm (pinned)
    - ghcr.io/astral-sh/uv:0.11.6 (pinned, multi-stage builder)
    - python:3.12-slim-bookworm (runtime base)
  patterns:
    - BlockingScheduler as PID 1 with signal-based graceful shutdown
    - D-07 first-tick-on-boot via next_run_time=datetime.now(UTC)
    - contextvars bind/clear bracket around run_cycle (INFRA-07/10 + T-02-03)
    - _run_cycle_body extraction point for per-phase monkeypatching in tests
    - EVENT_JOB_ERROR listener as belt-and-suspenders over per-cycle try/except
    - exec-form CMD for SIGTERM propagation (T-02-07)
    - env_file: .env + ${VAR:?...} interpolation for fail-fast compose boot
key-files:
  created:
    - src/tech_news_synth/scheduler.py
    - src/tech_news_synth/__main__.py
    - src/tech_news_synth/cli/__init__.py
    - src/tech_news_synth/cli/replay.py
    - src/tech_news_synth/cli/post_now.py
    - src/tech_news_synth/cli/source_health.py
    - Dockerfile
    - compose.yaml
    - config/sources.yaml.example
  modified:
    - tests/unit/test_scheduler.py (red stub → 5 real tests)
    - tests/unit/test_cycle_error_isolation.py (red stub → 3 real tests)
    - tests/unit/test_signal_shutdown.py (red stub → 3 real tests)
    - .dockerignore (unblock hatchling README.md requirement)
decisions:
  - Extracted _run_cycle_body() as module-level function so INFRA-08 tests
    monkeypatch a single seam instead of swapping the whole run_cycle. Keeps
    kill-switch + contextvar lifecycle honored by the injection tests too.
  - Kept README.md out of .dockerignore — hatchling reads it from the
    pyproject.toml `readme =` field during `uv sync --no-install-project`
    follow-up. Small deviation from the plan's implicit "README excluded"
    assumption; Rule 3 (blocking issue fix).
  - Did NOT run `docker compose up` as executor — that is the explicit
    checkpoint:human-verify gate (Task 4). Stack is built and parsed; the
    11-step smoke remains for the operator.
  - Config check against compose.yaml required a temporary .env (compose v2
    resolves env_file before interpolation). Smoke step 1 re-creates it.
metrics:
  started_at: "2026-04-12T20:36:00Z"
  completed_at: "2026-04-12T20:43:37Z"
  duration_seconds: 457
  tasks_completed: 3
  tasks_pending_checkpoint: 1
  commits: 3
  files_created: 9
  files_modified: 4
  tests_total: 64
  tests_passing: 64
  tests_skipped: 0
  coverage_percent: 72
  scheduler_coverage: 90
  image_size_mb: 665
---

# Phase 1 Plan 2: Scheduler + Container Summary

Turned the pure-core modules from Plan 01-01 into a running, containerized, scheduled chassis. `BlockingScheduler` as PID 1 (with SIGTERM/SIGINT handlers, first-tick-on-boot, kill-switch honored, exceptions isolated), an argparse dispatcher exposing `replay | post-now | source-health` CLI stubs, a multi-stage uv Dockerfile producing a 665 MB non-root runtime image, and a Compose v2 stack with health-gated `postgres` + app + named volumes for DB data and logs.

## Overview

**One-liner:** APScheduler + Docker chassis — the no-op `run_cycle()` body is the replacement point every downstream phase plugs into.

This plan delivers INFRA-01 (compose up — structural; runtime health verified at checkpoint), INFRA-05 (BlockingScheduler + UTC CronTrigger + interval_hours), and INFRA-08 (exception isolation). All three previously-skipped red-stub test files from Plan 01-01 are now green with 11 real behavior tests.

## Tasks Completed

| # | Task | Commit | Notes |
|---|------|--------|-------|
| 1 | scheduler.py + 3 test files (replaces red stubs) | `7d6e7b2` | 11 tests — build_scheduler, first-tick, interval, paused-skip, contextvars, error isolation × 3, signal handlers × 3 |
| 2 | __main__ dispatcher + CLI stubs + Dockerfile + sources.yaml.example | `d79b607` | Image `tns:test` builds at 665 MB, Python 3.12.13, UID 1000, --help lists all subcommands |
| 3 | compose.yaml (app + postgres + volumes) | `9b29542` | `docker compose config --quiet` passes; stop_grace_period 30s, service_healthy gate, config:ro bind mount, no postgres ports |
| 4 | **PENDING: docker compose smoke** | — | `checkpoint:human-verify` — 11 operator steps defined in plan Task 4 |

## Architecture Decisions

1. **`_run_cycle_body(settings)` as an injection seam** — moved the no-op cycle body out of `run_cycle` into a module-level function so INFRA-08 tests can `monkeypatch.setattr(scheduler_mod, "_run_cycle_body", raising_fn)` and exercise the full `run_cycle` lifecycle (kill-switch → bind → body → exception log → clear). Without this seam the tests would have to replace `run_cycle` itself and miss the bound-contextvar verification.
2. **D-07 first-tick via `next_run_time=datetime.now(UTC)`** — simpler than `scheduler._process_jobs()` hackery or an explicit pre-start `run_cycle(settings)` call; APScheduler fires the job once at registration time, then the CronTrigger resumes.
3. **Both `BlockingScheduler` and `CronTrigger` take `timezone=UTC` explicitly** — PITFALLS #7 (T-02-04). Ruff auto-fix swapped `timezone.utc` → `UTC` (Python 3.11+ alias); functionally identical.
4. **SIGTERM + SIGINT handlers both wired to the same `_shutdown` inner fn** — tests verify both paths call `scheduler.shutdown(wait=True)` exactly once.
5. **Exec-form `CMD ["python", "-m", "tech_news_synth"]`** — T-02-07. Combined with the signal handlers it closes the "docker stop waits 30s then SIGKILLs" failure mode (T-02-01 / T-02-11).
6. **`PYTHONPATH=/app/src`** instead of an editable install in the runtime image — one fewer layer, faster startup, and no pip metadata shipped. `python -c "import tech_news_synth"` (healthcheck) proves it works.
7. **Fail-fast compose interpolation**: `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}` — Compose refuses to start if the variable isn't set, complementing pydantic-settings' own required-field check.
8. **No `ports:` on postgres** (T-02-09) — host access only via `docker compose exec`. Phase 2 (Alembic) reaches the DB via the compose bridge network, not a published port.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] `README.md` removed from `.dockerignore`**
- **Found during:** Task 2 (`docker build --target runtime`)
- **Issue:** `COPY README.md ./` in the builder stage failed with "not found" — `.dockerignore` from Plan 01-01 had excluded `README.md`, but hatchling's build reads `readme = "README.md"` from `pyproject.toml` and fails without it.
- **Fix:** Comment-replaced the `README.md` line in `.dockerignore` with an explanatory note.
- **Files modified:** `.dockerignore`
- **Commit:** folded into `d79b607` (Task 2)

**2. [Ruff auto-fix] `timezone.utc` → `UTC` alias**
- `ruff check --fix` applied `UP` rule `from datetime import UTC`. Semantically identical; no test changes needed.

No architectural changes. No user decisions needed. Pattern 1/2/3 from RESEARCH.md followed verbatim aside from the README.md dockerignore tweak.

### Authentication Gates

None.

## Verification

### Automated (green)

```bash
uv run pytest tests/ -q
# 64 passed in 0.47s

uv run pytest tests/ --cov=tech_news_synth --cov-report=term
# scheduler.py 90%, overall 72% (only __main__.py and CLI stubs uncovered — both dispatch-only)

uv run ruff check . && uv run ruff format --check .
# clean

docker build --target runtime -t tns:test .
# 665 MB runtime image

docker run --rm tns:test python -c "import sys, tech_news_synth; assert sys.version_info[:2]==(3,12)"
docker run --rm tns:test python -m tech_news_synth --help   # lists replay, post-now, source-health
docker run --rm tns:test id -u                               # 1000

docker compose config --quiet                                # parses clean (with .env present)
```

### Manual / deferred

**`docker compose up` smoke is Task 4 — CHECKPOINT PENDING.** See Handoff section.

## Requirements Coverage

| Requirement | Where Verified | Status |
|-------------|----------------|--------|
| INFRA-01 | `docker compose config --quiet` (structural) + Task 4 smoke steps 2–6 (runtime) | structural ✓, runtime pending |
| INFRA-05 | `tests/unit/test_scheduler.py` (5 tests — UTC, CronTrigger, interval, first-tick, kill-switch) | ✓ |
| INFRA-08 | `tests/unit/test_cycle_error_isolation.py` (3 tests — injection, listener, next-tick) | ✓ |
| INFRA-03 (cross-check) | Task 4 smoke step 9 (remove ANTHROPIC_API_KEY → fail-fast) | pending |
| INFRA-09 (cross-check) | Task 4 smoke steps 7–8 (marker + env toggles at runtime) | pending |

## Known Stubs

| File | Function | Reason |
|------|----------|--------|
| src/tech_news_synth/cli/replay.py | `main` | Phase 8 OPS-02 |
| src/tech_news_synth/cli/post_now.py | `main` | Phase 8 OPS-03 |
| src/tech_news_synth/cli/source_health.py | `main` | Phase 8 OPS-04 |
| src/tech_news_synth/scheduler.py | `_run_cycle_body` | Phase 2+ replace with fetch→cluster→synth→publish |
| config/sources.yaml.example | — | Phase 4 INGEST-01 populates schema |

All stubs are intentional per plan; downstream phases own the fills. Dispatcher is live today — `python -m tech_news_synth replay` raises `NotImplementedError` with the Phase 8 reference string, so Phase 8 has a clear target.

## Checkpoint Pending: Docker Compose Smoke (11 Steps) — Blocking Phase Verification

Task 4 is a `checkpoint:human-verify` gate. The executor has NOT run `docker compose up`. Operator must execute the 11 steps below (from `01-VALIDATION.md` "Manual-Only Verifications" plus Task 4's expanded script):

1. **Clean environment:** `docker compose down -v`; `cp .env.example .env`; edit `.env` with any non-empty values (Phase 1 makes no external calls); set `INTERVAL_HOURS=2`, `DRY_RUN=1`, `PAUSED=0`.
2. **Build and start:** `docker compose up -d --build` — expect both services to start.
3. **Health gate:** wait ~30s then `docker compose ps` — both `app` and `postgres` show `Up ... (healthy)`.
4. **Volumes exist:** `docker volume ls | grep tech-news-synth` — both `tech-news-synth_pgdata` and `tech-news-synth_logs` present.
5. **First cycle fires immediately (D-07):** `docker compose logs app | head -30` — expect `scheduler_starting` → `cycle_start` → `cycle_end` JSON lines; every line after `scheduler_starting` carries `cycle_id` + `dry_run=true`; timestamps end in `+00:00`.
6. **Logs written to volume (INFRA-07 dual output):** `docker compose exec app tail -n 5 /data/logs/app.jsonl` — each line valid JSON with same `cycle_id` fields.
7. **Kill-switch marker (INFRA-09):** `docker compose exec app touch /data/paused` → `docker compose restart app` → `docker compose logs app --tail 10` — expect `cycle_skipped status=paused paused_by=marker`. Remove marker; next cycle runs normally.
8. **Kill-switch env (INFRA-09):** edit `.env`: `PAUSED=1`; `docker compose up -d`; logs show `paused_by=env` (or `both` if marker from step 7 remains).
9. **Fail-fast on missing secret (INFRA-03):** `cp .env .env.backup && sed -i '/^ANTHROPIC_API_KEY=/d' .env && docker compose up -d app` — logs contain `Configuration error:` on stderr naming `anthropic_api_key`; container exits non-zero. Restore `.env`.
10. **Graceful SIGTERM (INFRA-05 / INFRA-08):** `time docker compose down` — completes under 10s (must be well inside `stop_grace_period: 30s`).
11. **Exception isolation (INFRA-08):** temporarily edit `src/tech_news_synth/scheduler.py` `_run_cycle_body` to `raise RuntimeError("smoke-test")`; `docker compose up -d --build`; after 5s `docker compose logs app --tail 30` — expect a `cycle_error` line with stacktrace containing `smoke-test`; scheduler stays up (no crash loop). Revert edit and rebuild.

**Cleanup:** `docker compose down -v`.

**Resume signal:** Operator replies "approved" once all 11 steps pass, or "failed at step N: {observation}" to triage.

## Handoff to Phase 2

Integration points Alembic work (Phase 2, STORE-01) will build on:

- **`compose.yaml` postgres service** — reachable over internal DNS as `postgres:5432`, credentials from `.env`, data persisted in `tech-news-synth_pgdata` volume.
- **`/data` volume** — already mounted at `/data` in app container; Phase 2 can add `/data/alembic.lock` if needed for migration coordination.
- **`env_file: .env`** — `POSTGRES_HOST/PORT/DB/USER/PASSWORD` already in Settings; `Settings.database_url` returns a ready `postgresql+psycopg://` DSN.
- **`app` import root** — `tech_news_synth.scheduler.run_cycle`'s body (`_run_cycle_body`) is the replacement point; Phase 2 inserts `alembic upgrade head` logic either at container startup (entrypoint script) or as a one-shot `migrate` compose service (Phase 2's call).
- **Contextvars** — any code called from `run_cycle` inherits `cycle_id` + `dry_run` on every log line for free. Do not re-bind; do not clear.

## Self-Check: PASSED

- All 9 created files exist on disk.
- All 4 modified files present with expected changes.
- 3 commits verified: `7d6e7b2`, `d79b607`, `9b29542`.
- `uv run pytest tests/ -q` → 64 passed, 0 skipped, 0 failed.
- `uv run ruff check .` and `uv run ruff format --check .` clean.
- `docker build --target runtime -t tns:test .` succeeds (665 MB image).
- `docker compose config --quiet` passes with a populated `.env`.
- No TODO/FIXME in production code; only documented Phase-N stubs.
