---
phase: 01
slug: foundations
status: needs-work
verified: 2026-04-12
verdict: REVISE
score: "9/10 must-haves verified (1 test hermeticity defect)"
overrides_applied: 0
gaps:
  - truth: "Boot fails fast with a clear error if any required .env key is missing or malformed (SC-2 / INFRA-03)"
    status: partial
    reason: >-
      The production behavior works (pydantic-settings raises ValidationError on missing required
      keys, and __main__ exits 2 with a stderr error). However, the automated regression test
      protecting this behavior (tests/unit/test_config.py::test_settings_missing_required) is
      non-hermetic and fails when a real `.env` exists in the working directory. The test relies
      on monkeypatching PYDANTIC_SETTINGS_DISABLE_ENV_FILE=1 via the conftest fixture, but
      Settings.model_config.env_file is evaluated ONCE at class-body execution time via
      _env_file_for_settings(), BEFORE the fixture can set the env var. As a result, when
      pytest is invoked after the operator's Phase 1 smoke test (which leaves `.env` and
      `.env.backup` in the repo), the class-level env_file=".env" has already been baked in,
      pydantic-settings reads .env, and the deleted ANTHROPIC_API_KEY is refilled from the file.
      The test reports `DID NOT RAISE ValidationError`.
    artifacts:
      - path: "src/tech_news_synth/config.py"
        issue: >-
          `env_file=_env_file_for_settings()` is evaluated at class-definition time.
          PYDANTIC_SETTINGS_DISABLE_ENV_FILE is only honored for the FIRST import of the module;
          subsequent conftest fixtures cannot influence it. The escape hatch documented in
          Plan 01-01's deviation #2 is brittle.
      - path: "tests/conftest.py"
        issue: >-
          monkeypatch_env sets PYDANTIC_SETTINGS_DISABLE_ENV_FILE after tech_news_synth.config
          has already been imported (via test collection / earlier tests). The fixture cannot
          retroactively change the class's env_file attribute.
    missing:
      - >-
        Make Settings() read env_file dynamically. Two concrete options: (a) override
        model_config.env_file at instance construction time (e.g. Settings.model_config["env_file"]
        = _env_file_for_settings() inside load_settings before instantiation), or (b) use
        model_config as a @classmethod / computed_field pattern that re-reads the environment,
        or (c) pass _env_file=None to Settings() when PYDANTIC_SETTINGS_DISABLE_ENV_FILE is set
        (pydantic-settings supports the _env_file kwarg override at call time).
      - >-
        Add CI guard: run `uv run pytest tests/ -q` in a working tree that contains a pre-existing
        .env file (mimicking post-deployment reality). The current pass-only-with-no-.env posture
        means any developer cloning the repo and running `cp .env.example .env` before tests
        breaks the suite.
      - >-
        Delete the leftover `.env.backup` produced by operator smoke-test step 9; it is
        gitignored but creates noise. Consider updating the smoke-test script to clean up.
human_verification: []
---

# Phase 1: Foundations Verification Report

**Phase Goal:** A running, observable, scheduled container with validated secrets and UTC invariants — the chassis every later phase writes through.

**Verified:** 2026-04-12
**Status:** needs-work (REVISE)
**Re-verification:** No — initial verification

## Verdict

**REVISE.** All five success criteria are structurally satisfied by the code on disk, the Docker image builds, ruff is clean, 63 of 64 unit tests pass, and the operator has manually approved the 11-step `docker compose up` smoke (covering INFRA-01, INFRA-03 runtime fail-fast, INFRA-05 interval/UTC behavior, INFRA-07 dual-sink volume write, INFRA-08 exception isolation, INFRA-09 kill-switch env+marker, INFRA-10 DRY_RUN binding). However, one unit test (`tests/unit/test_config.py::test_settings_missing_required`) is non-deterministic: it passes only when no `.env` exists in the working directory. Running `uv run pytest tests/` today in the post-smoke-test repo state produces `1 failed, 63 passed`. The SUMMARY's claim of "64 passed, 0 skipped" does not match current reality. The *behavior* under test (fail-fast on missing key) is real and operator-verified in step 9 of the smoke; only the unit test's hermeticity is broken. Fix is small but must be applied before Phase 2 inherits a flaky test baseline.

## Goal Achievement — Success Criteria

| # | Success Criterion | Status | Evidence |
|---|-------------------|--------|----------|
| 1 | `docker compose up` brings up healthy `app` + `postgres` with named volumes for DB + logs | ✓ VERIFIED | `compose.yaml` defines both services, healthchecks on each, named volumes `pgdata` + `logs`, `depends_on: postgres.condition: service_healthy`; operator manually approved 11-step smoke (steps 2-4); `docker build --target runtime -t tns:verify .` succeeds locally at time of verification |
| 2 | Boot fails fast on missing/malformed `.env`; `.env.example` present; `.env` gitignored | ⚠ PARTIAL | Production path verified: `config.py::load_settings` raises on missing required `SecretStr` fields; `__main__._dispatch_scheduler` catches `ValidationError` and returns exit code 2 with stderr message; `.env.example` present and tracked; `.gitignore` line 2 excludes `.env`; `.dockerignore` excludes `.env`; operator smoke step 9 confirmed runtime fail-fast. **But**: unit test `test_settings_missing_required` is non-hermetic — fails when a real `.env` exists in cwd (see Gaps). |
| 3 | APScheduler (PID 1, UTC) fires no-op `run_cycle()` every 2h configurable; JSON log on stdout AND volume with unique `cycle_id` | ✓ VERIFIED | `scheduler.py::build_scheduler` uses `BlockingScheduler(timezone=UTC)` + `CronTrigger(hour=f"*/{interval_hours}", timezone=UTC)` + `next_run_time=datetime.now(UTC)` for D-07 first-tick; `Dockerfile` CMD is exec-form (`["python","-m","tech_news_synth"]`) so scheduler runs as PID 1; `logging.py::configure_logging` attaches both `StreamHandler(sys.stdout)` and `FileHandler(log_dir/app.jsonl)`; `run_cycle` binds `cycle_id` via `structlog.contextvars.bind_contextvars`; tests `test_build_scheduler_utc_and_single_job`, `test_first_tick_on_boot`, `test_interval_respected`, `test_contextvars_bound_and_cleared` (4 passing); operator smoke step 5-6 confirmed dual-sink runtime write. |
| 4 | Exception in `run_cycle()` logged with stacktrace; scheduler keeps ticking — no crash loop | ✓ VERIFIED | `scheduler.py::run_cycle` wraps `_run_cycle_body` in `try/except Exception: log.exception("cycle_error")`; belt-and-suspenders `_job_error_listener` on `EVENT_JOB_ERROR`; tests `test_cycle_body_exception_isolated`, `test_scheduler_keeps_ticking_after_error`, `test_job_error_listener_logs` (3 passing); operator smoke step 11 confirmed live behavior. |
| 5 | `PAUSED=1` or `/data/paused` pauses next cycle (exit 0, log line, zero I/O); `DRY_RUN=1` accepted and visible in cycle log | ✓ VERIFIED | `killswitch.py::is_paused` returns `(bool, reason)` with OR logic across env + marker file (D-08); `run_cycle` calls it first, emits `cycle_skipped` and returns before `cycle_start` when paused; `Settings.dry_run` is a typed bool and bound into contextvars at cycle start; tests `test_cycle_skipped_when_paused` + 5 parametrized `test_killswitch.py` cases + `test_dry_run_logging.py` all green; operator smoke steps 7-8 confirmed runtime toggles for both `PAUSED=1` env and marker file. |

**Score:** 4 fully verified + 1 partial (production works, regression test flaky) = **9/10 must-haves**.

## Requirements Coverage (INFRA-01..INFRA-10)

| REQ-ID | Description | Status | Evidence |
|--------|-------------|--------|----------|
| INFRA-01 | `docker compose up` with `app` + `postgres` services and persistent volumes for DB + logs | ✓ SATISFIED | `compose.yaml`; operator smoke signed off |
| INFRA-02 | Base `python:3.12-slim-bookworm`; deps via `uv` + lockfile | ✓ SATISFIED | `Dockerfile` L4+L27 use `python:3.12-slim-bookworm` (no Alpine); `pyproject.toml` L6 pins `requires-python = ">=3.12,<3.13"`; `uv.lock` present; builder stage uses `uv sync --frozen --no-dev` from ghcr.io/astral-sh/uv:0.11.6 (pinned) |
| INFRA-03 | Secrets loaded via pydantic-settings from `.env` (Compose `env_file:`); missing/invalid fail boot | ⚠ PARTIAL | Production behavior verified (smoke step 9 + code review); regression test non-hermetic — see Gaps |
| INFRA-04 | `.env.example` committed; `.env` in `.gitignore` + `.dockerignore`; pre-commit hook for secret scanning | ✓ SATISFIED | `.env.example` tracked; `.gitignore` L2 `^\.env$`; `.dockerignore` L1 `^\.env$`; `.pre-commit-config.yaml` includes `gitleaks` v8.21.2; 6 passing tests in `test_secrets_hygiene.py` |
| INFRA-05 | APScheduler `BlockingScheduler` as PID 1 with `CronTrigger(hour="*/{INTERVAL_HOURS}")` + `timezone=UTC` | ✓ SATISFIED | `scheduler.py::build_scheduler`; exec-form Dockerfile CMD; 5 passing scheduler tests; operator smoke step 5 |
| INFRA-06 | Timestamps UTC: `TIMESTAMPTZ` (Phase 2), Python `datetime.now(timezone.utc)`, no `TZ=` on containers | ✓ SATISFIED | `logging.py` uses `TimeStamper(fmt="iso", utc=True)`; `scheduler.py` uses `datetime.now(UTC)`; no `TZ=` anywhere in `compose.yaml` or `Dockerfile`; ruff `DTZ` lint selected in `pyproject.toml` L59 to prevent naive datetime regressions; `test_utc_invariants.py` passing |
| INFRA-07 | structlog JSON to stdout + Docker volume; every line has `cycle_id` | ✓ SATISFIED | `logging.py::configure_logging` adds both `StreamHandler(sys.stdout)` and `FileHandler(log_dir/app.jsonl)`; `merge_contextvars` first processor; `run_cycle` binds `cycle_id` (ULID) before any log line; `test_logging.py` 4 tests green; smoke step 6 verified volume write |
| INFRA-08 | Unhandled exception inside `run_cycle()` logged with stacktrace, never crashes scheduler | ✓ SATISFIED | try/except in `run_cycle`; `EVENT_JOB_ERROR` listener safety net; 3 passing tests; smoke step 11 verified runtime |
| INFRA-09 | Kill-switch at cycle start via `PAUSED=1` OR `/data/paused`; cycle exits 0, logs, zero I/O | ✓ SATISFIED | `killswitch.py::is_paused` OR-logic returns `(bool, reason)` with reasons `env|marker|both`; `run_cycle` short-circuits before `cycle_start` log; 5+1 passing tests; smoke steps 7-8 |
| INFRA-10 | `DRY_RUN=1` flag short-circuits publishing (Phase 7 binding), visible in cycle log now | ✓ SATISFIED | `Settings.dry_run: bool`; bound into contextvars at cycle start (`test_contextvars_bound_and_cleared` asserts `dry_run=True` on cycle lines); `test_dry_run_logging.py` passing |

**Coverage:** 9/10 SATISFIED, 1/10 PARTIAL (INFRA-03 production works, regression test flaky).

## Decisions D-01..D-10

| # | Decision | Status | Evidence |
|---|----------|--------|----------|
| D-01 | Package name `tech_news_synth` | ✓ | `pyproject.toml` L2, `src/tech_news_synth/` exists; all imports use this root |
| D-02 | src-layout under `src/tech_news_synth/` | ✓ | `pyproject.toml` L45-46 `[tool.hatch.build.targets.wheel] packages=["src/tech_news_synth"]`; `pythonpath=["src"]` for pytest |
| D-03 | `./config/sources.yaml` bind-mounted `:ro` | ✓ | `compose.yaml` L39 `./config:/app/config:ro`; `config/sources.yaml.example` exists (populated in Phase 4) |
| D-04 | Multi-stage uv Dockerfile (builder → runtime) | ✓ | `Dockerfile` has `AS builder` (L4) and `AS runtime` (L27); builder uses uv 0.11.6 pinned image; runtime is slim-bookworm; 665MB runtime (per SUMMARY, consistent with rebuild) |
| D-05 | Entrypoint `python -m tech_news_synth` | ✓ | `Dockerfile` L55 `CMD ["python", "-m", "tech_news_synth"]`; `__main__.py` present |
| D-06 | Subcommands `replay`/`post-now`/`source-health` as argparse dispatcher skeletons | ✓ | `__main__.py::main` uses argparse with 3 subparsers; `cli/replay.py`, `cli/post_now.py`, `cli/source_health.py` all raise `NotImplementedError("... Phase 8 ...")` — correct stubs per plan |
| D-07 | First-tick-on-boot via `next_run_time=datetime.now(UTC)` | ✓ | `scheduler.py` L104; `test_first_tick_on_boot` passing; smoke step 5 confirms |
| D-08 | Kill-switch OR logic with `paused_by` in log | ✓ | `killswitch.py::is_paused` returns `env|marker|both|None`; `run_cycle` logs `paused_by=reason` |
| D-09 | ULID cycle_id via `python-ulid` | ✓ | `ids.py` uses `ulid.ULID`; `test_cycle_id.py` asserts 26-char Crockford-base32; `test_contextvars_bound_and_cleared` asserts `len(ln["cycle_id"]) == 26` |
| D-10 | `DRY_RUN` bound into contextvars per cycle | ✓ | `scheduler.py::run_cycle` L57 `bind_contextvars(cycle_id=..., dry_run=bool(settings.dry_run))`; test assertions confirm |

All 10 decisions honored verbatim. One minor, pre-documented micro-deviation: ruff auto-fix swapped `from datetime import timezone; timezone.utc` to `from datetime import UTC` (Python 3.11+ alias) — semantically identical, noted in SUMMARY 01-02.

## Automated Checks

| Check | Command | Result |
|-------|---------|--------|
| Unit tests (as-is, with leftover `.env`) | `uv run pytest tests/ -q` | **1 failed, 63 passed** (test_settings_missing_required) |
| Unit tests (hermetic) | `PYDANTIC_SETTINGS_DISABLE_ENV_FILE=1 uv run pytest tests/ -q` | 64 passed, 0 skipped |
| Ruff lint | `uv run ruff check .` | All checks passed |
| Ruff format | `uv run ruff format --check .` | 24 files already formatted |
| Docker build | `docker build --target runtime -t tns:verify .` | Succeeds (image manifest exported, DONE) |
| Commits present | `git log --oneline` | All 6 plan-01-01 commits + 3 plan-01-02 commits + 2 docs commits present |
| Operator smoke (11 steps) | manual | Approved |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Module imports cleanly in runtime image | `docker run --rm tns:verify python -c "import tech_news_synth"` | Healthcheck CMD runs this on 30s interval; build succeeded implying layer OK | ✓ (indirect; operator smoke exercised) |
| `--help` lists all subcommands | `docker run --rm tns:verify python -m tech_news_synth --help` | Per SUMMARY 01-02 this returned replay/post-now/source-health | ✓ (per prior verification, not re-run here to respect 10s/no-state rule) |
| `docker compose config --quiet` parses clean | already-run gate | ✓ per SUMMARY + operator smoke | ✓ |

## Anti-Patterns & Scope Leak

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `src/tech_news_synth/scheduler.py::_run_cycle_body` | `return None` no-op body | ℹ Info | **Intentional** — documented Phase 2+ fill-in point (plan T-02-02); not a stub leak |
| `src/tech_news_synth/cli/{replay,post_now,source_health}.py` | `raise NotImplementedError("... Phase 8 ...")` | ℹ Info | **Intentional** — Phase 8 OPS-02/03/04 stubs with explicit phase reference |
| `config/sources.yaml.example` | empty schema placeholder | ℹ Info | **Intentional** — Phase 4 INGEST-01 populates |
| (none) | Alembic migrations | — | ✓ No scope leak — Phase 2 owns |
| (none) | ingestion / clustering / synthesis / publish code | — | ✓ No scope leak — Phases 4-7 own |
| (none) | DB queries from app | — | ✓ No scope leak — Phase 2 owns (only `Settings.database_url` property exists, unused by app code) |
| `.env.backup` in repo root (gitignored) | leftover from smoke step 9 | ⚠ Warning | Noise only; not committed. Operator should `rm .env.backup` and the smoke-test script should clean up. |

No TODO/FIXME/PLACEHOLDER comments found in production src/. No `return []` / `return {}` stubs outside intended Phase N references. No `console.log`-style placeholders (N/A — Python project, but equivalent `print` debugging absent).

## SUMMARY ↔ Reality Cross-Check

| SUMMARY Claim | Reality | Match |
|---------------|---------|-------|
| 01-01: 24 files created | `ls` confirms all files in `key-files.created` exist | ✓ |
| 01-01: 53 passed, 3 skipped | Those 3 are no longer skipped (Plan 01-02 filled them) — now counted in the 64 total | ✓ (expected evolution) |
| 01-01: 6 commits (`9768157`..`37d51c2`) | `git log --oneline` shows all six | ✓ |
| 01-02: 64 passed, 0 skipped | **Reality: 63 passed, 1 failed** when `.env` present in cwd; 64 passed when hermetic | ✗ STALE — SUMMARY claim assumes no `.env` in repo |
| 01-02: 3 commits (`7d6e7b2`, `d79b607`, `9b29542`) | Present | ✓ |
| 01-02: image 665 MB | Build succeeded; size not re-measured but layers cached | ✓ (consistent) |

The 01-02 SUMMARY status is `awaiting-checkpoint`, which matches: the operator has approved the 11-step smoke (per the verification request's preamble). Suggest flipping `status: complete` in the frontmatter and adding a brief "checkpoint signed off on 2026-04-12" note when the fix for the test-hermeticity gap lands.

## Phase 2+ Scope Leak Check

None detected. `Settings.database_url` property exists (returns DSN string) but is never called from any Phase 1 code path — it is a convenience for Phase 2's Alembic wiring, consistent with CONTEXT.md Integration Points. No `alembic/`, `migrations/`, `models/`, `repos/`, `sources.py`, `clusters.py`, `synth.py`, or `publish.py` modules present.

## Gaps Summary

**One gap, narrow and non-blocking at runtime but test-suite-blocking in CI:**

The `test_settings_missing_required` unit test is non-hermetic because `Settings.model_config.env_file` is resolved at class-body time, before the test fixture can set `PYDANTIC_SETTINGS_DISABLE_ENV_FILE=1`. Any developer who has a `.env` file in the repo root (which is the *expected* state after running the quickstart or the operator smoke test — both do `cp .env.example .env`) will see 1 failure out of 64.

The underlying production behavior — fail-fast on missing required secret — is correct and operator-verified in smoke step 9. Only the test is broken.

**Recommended fix (small):**

Pass `_env_file` at instance-construction time instead of relying on class config:

```python
def load_settings() -> Settings:
    env_file = _env_file_for_settings()
    try:
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    except Exception as e:
        print(f"Configuration error:\n{e}", file=sys.stderr)
        raise
```

Or delete the `.env.backup` artifact and document that test runs require `PYDANTIC_SETTINGS_DISABLE_ENV_FILE=1` in a Makefile / pytest invocation. The former is cleaner and matches pydantic-settings' documented override pattern.

Also recommend: operator cleanup of `.env.backup` in repo root (it's gitignored but clutters `ls`).

## Sign-off

**Verdict: REVISE** — production chassis is sound and operator-verified; one unit-test hermeticity bug must be closed before declaring Phase 1 complete so that CI and every subsequent developer inherits a reliably green baseline. Estimated fix effort: <15 minutes. No architectural changes, no scope additions.

---
*Verified: 2026-04-12 via goal-backward analysis*
*Verifier: Claude (gsd-verifier, Opus 4.6 1M)*
