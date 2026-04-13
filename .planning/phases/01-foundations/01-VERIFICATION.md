---
phase: 01
slug: foundations
status: passed
verified: 2026-04-12
verdict: PASS
score: "10/10 must-haves verified"
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 9/10
  gaps_closed:
    - "test_settings_missing_required non-hermetic when .env exists in cwd"
  gaps_remaining: []
  regressions: []
gaps: []
human_verification: []
---

# Phase 1: Foundations Verification Report

**Phase Goal:** A running, observable, scheduled container with validated secrets and UTC invariants — the chassis every later phase writes through.

**Verified:** 2026-04-12 (re-verification after hermeticity fix)
**Status:** passed (PASS)
**Re-verification:** Yes — gap from initial verification closed

## Verdict

**PASS.** All five success criteria are structurally satisfied, the Docker image builds, ruff is clean, all 64 unit tests pass deterministically regardless of whether a real `.env` is present in the working directory, and the operator has approved the 11-step `docker compose up` smoke. The prior hermeticity defect (`test_settings_missing_required` non-hermetic when `.env` exists in cwd) is closed by commit `3d30900` — `load_settings()` now passes `_env_file=_env_file_for_settings()` at instance-construction time, overriding the class-body `env_file=".env"` per call. The leftover `.env.backup` has been removed. `01-02-SUMMARY.md` status is now `complete`. Phase 1 is ready for Phase 2 to build on.

## Revision History

| Date | Change | Evidence |
|------|--------|----------|
| 2026-04-12 (initial) | Verdict REVISE — 9/10, one hermeticity gap on `test_settings_missing_required` | See gaps in previous frontmatter |
| 2026-04-12 (this rev) | Verdict PASS — hermeticity fix landed (commit `3d30900`), `.env.backup` deleted, SUMMARY flipped to `complete`, 64/64 green with `.env` present | `uv run pytest tests/ -q` → `64 passed in 0.21s` with `.env` in cwd; `src/tech_news_synth/config.py::load_settings` passes `_env_file=` at call time |

## Goal Achievement — Success Criteria

| # | Success Criterion | Status | Evidence |
|---|-------------------|--------|----------|
| 1 | `docker compose up` brings up healthy `app` + `postgres` with named volumes for DB + logs | ✓ VERIFIED | `compose.yaml` defines both services, healthchecks on each, named volumes `pgdata` + `logs`, `depends_on: postgres.condition: service_healthy`; operator manually approved 11-step smoke (steps 2-4) |
| 2 | Boot fails fast on missing/malformed `.env`; `.env.example` present; `.env` gitignored | ✓ VERIFIED | Production path: `config.py::load_settings` raises on missing required `SecretStr` fields; `__main__._dispatch_scheduler` catches `ValidationError` and returns exit code 2 with stderr message; `.env.example` tracked; `.gitignore` excludes `.env`; `.dockerignore` excludes `.env`; operator smoke step 9 confirmed; **regression test now hermetic**: `test_settings_missing_required` passes with a real `.env` present in cwd because `load_settings()` passes `_env_file=_env_file_for_settings()` at instance construction time, so the `PYDANTIC_SETTINGS_DISABLE_ENV_FILE=1` env var set by the `monkeypatch_env` fixture is honored per-call rather than baked in at class-body time. |
| 3 | APScheduler (PID 1, UTC) fires no-op `run_cycle()` every 2h configurable; JSON log on stdout AND volume with unique `cycle_id` | ✓ VERIFIED | `scheduler.py::build_scheduler` uses `BlockingScheduler(timezone=UTC)` + `CronTrigger(hour=f"*/{interval_hours}", timezone=UTC)` + `next_run_time=datetime.now(UTC)` for D-07 first-tick; Dockerfile exec-form CMD; dual-sink via `StreamHandler(sys.stdout)` + `FileHandler(log_dir/app.jsonl)`; `cycle_id` bound via `structlog.contextvars`; 4 scheduler tests green; operator smoke steps 5-6 confirmed |
| 4 | Exception in `run_cycle()` logged with stacktrace; scheduler keeps ticking — no crash loop | ✓ VERIFIED | `run_cycle` wraps body in `try/except Exception: log.exception("cycle_error")`; `_job_error_listener` on `EVENT_JOB_ERROR` as safety net; 3 passing tests; operator smoke step 11 |
| 5 | `PAUSED=1` or `/data/paused` pauses next cycle (exit 0, log line, zero I/O); `DRY_RUN=1` accepted and visible in cycle log | ✓ VERIFIED | `killswitch.py::is_paused` returns `(bool, reason)` OR-logic (D-08); `run_cycle` emits `cycle_skipped` and returns before `cycle_start` when paused; `Settings.dry_run` bound into contextvars; all kill-switch + dry-run tests green; operator smoke steps 7-8 |

**Score:** 5/5 success criteria fully verified = **10/10 must-haves**.

## Requirements Coverage (INFRA-01..INFRA-10)

| REQ-ID | Description | Status | Evidence |
|--------|-------------|--------|----------|
| INFRA-01 | `docker compose up` with `app` + `postgres` + persistent volumes | ✓ SATISFIED | `compose.yaml`; operator smoke |
| INFRA-02 | Base `python:3.12-slim-bookworm`; deps via `uv` + lockfile | ✓ SATISFIED | `Dockerfile` L4+L27; `pyproject.toml` pins `>=3.12,<3.13`; `uv.lock` present; builder uses pinned uv 0.11.6 |
| INFRA-03 | Secrets via pydantic-settings from `.env`; missing/invalid fail boot | ✓ SATISFIED | Production verified (smoke step 9); regression test now hermetic (see Revision History) |
| INFRA-04 | `.env.example` committed; `.env` in `.gitignore` + `.dockerignore`; pre-commit secret scan | ✓ SATISFIED | `.env.example` tracked; `.gitignore` + `.dockerignore` block `.env`; `gitleaks` v8.21.2 in `.pre-commit-config.yaml`; 6 passing hygiene tests |
| INFRA-05 | APScheduler `BlockingScheduler` PID 1, `CronTrigger(hour="*/{INTERVAL_HOURS}")`, `timezone=UTC` | ✓ SATISFIED | `scheduler.py::build_scheduler`; exec-form CMD; 5 passing scheduler tests |
| INFRA-06 | Timestamps UTC; no `TZ=` on containers | ✓ SATISFIED | `TimeStamper(utc=True)`; `datetime.now(UTC)`; no `TZ=` in compose/Dockerfile; ruff `DTZ` enabled; `test_utc_invariants.py` green |
| INFRA-07 | structlog JSON to stdout + volume; every line has `cycle_id` | ✓ SATISFIED | Dual handlers; `merge_contextvars` first processor; 4 logging tests green; smoke step 6 |
| INFRA-08 | Unhandled exception logged with stacktrace, scheduler never dies | ✓ SATISFIED | try/except + `EVENT_JOB_ERROR` listener; 3 passing tests; smoke step 11 |
| INFRA-09 | Kill-switch `PAUSED=1` OR `/data/paused`; exit 0, logs, zero I/O | ✓ SATISFIED | OR-logic with `paused_by` reason; `run_cycle` short-circuits before `cycle_start`; 6 passing tests; smoke steps 7-8 |
| INFRA-10 | `DRY_RUN=1` flag visible in cycle log | ✓ SATISFIED | `Settings.dry_run: bool`; bound into contextvars; `test_dry_run_logging.py` green |

**Coverage:** 10/10 SATISFIED.

## Decisions D-01..D-10

All ten decisions honored verbatim (same evidence as initial verification — unchanged by the fix). D-01 package name, D-02 src-layout, D-03 sources.yaml bind-mount, D-04 multi-stage uv Dockerfile, D-05 `python -m tech_news_synth` entrypoint, D-06 argparse subcommand stubs, D-07 first-tick-on-boot, D-08 kill-switch OR-logic with `paused_by`, D-09 ULID cycle_id, D-10 `DRY_RUN` contextvars binding.

## Automated Checks

| Check | Command | Result |
|-------|---------|--------|
| Unit tests (with real `.env` present in cwd) | `uv run pytest tests/ -q` | **64 passed, 0 failed, 0 skipped** in 0.21s |
| Ruff lint | `uv run ruff check .` | All checks passed |
| Ruff format | `uv run ruff format --check .` | 24 files already formatted |
| `.env.backup` leftover | `ls .env.backup` | Not present — cleaned up |
| Hermeticity proof | `.env` present in cwd AND `test_settings_missing_required` still green | Confirmed: instance-level `_env_file=None` override works |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `load_settings()` honors `_env_file` override per call | Inspect `config.py:102` — `Settings(_env_file=_env_file_for_settings())` | Present; `_env_file_for_settings()` returns `None` when `PYDANTIC_SETTINGS_DISABLE_ENV_FILE=1` | ✓ |
| `monkeypatch_env` fixture sets `PYDANTIC_SETTINGS_DISABLE_ENV_FILE=1` | `tests/conftest.py:30` | Present | ✓ |
| Full suite green with `.env` on disk | `ls .env && uv run pytest tests/ -q` | 64 passed | ✓ |

## Anti-Patterns & Scope Leak

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `src/tech_news_synth/scheduler.py::_run_cycle_body` | `return None` no-op body | ℹ Info | **Intentional** — Phase 2+ fill-in point |
| `src/tech_news_synth/cli/{replay,post_now,source_health}.py` | `raise NotImplementedError("... Phase 8 ...")` | ℹ Info | **Intentional** — Phase 8 OPS stubs |
| `config/sources.yaml.example` | empty schema placeholder | ℹ Info | **Intentional** — Phase 4 populates |
| (none) | Alembic / models / ingestion / clustering / synthesis / publish | — | ✓ No scope leak |

No TODO/FIXME/PLACEHOLDER in production src/. No stub returns outside intentional Phase-N deferrals.

## SUMMARY ↔ Reality Cross-Check

| SUMMARY Claim | Reality | Match |
|---------------|---------|-------|
| 01-01: 24 files, 6 commits | Files + commits present | ✓ |
| 01-02: 64 passed, 0 skipped | 64 passed in 0.21s with `.env` in cwd | ✓ |
| 01-02: status `complete` | Frontmatter flipped per objective | ✓ |
| Hermeticity fix commit `3d30900` | `load_settings` passes `_env_file=` at call time | ✓ |

## Phase 2+ Scope Leak Check

None detected. `Settings.database_url` property exists but is unused by Phase 1 code — it is a convenience awaiting Phase 2's Alembic wiring.

## Gaps Summary

None. The sole gap from the initial verification (test hermeticity) is closed. The fix is the textbook pydantic-settings `_env_file` override pattern applied at `load_settings()` call time — small, surgical, and matches the pattern recommended in the initial report.

## Sign-off

**Verdict: PASS** — Phase 1 foundations are complete, deterministic, and ready. Phase 2 may proceed.

---
*Re-verified: 2026-04-12 via goal-backward analysis*
*Verifier: Claude (gsd-verifier, Opus 4.6 1M)*
