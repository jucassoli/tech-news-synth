---
phase: 01-foundations
plan: 01
subsystem: foundations
tags: [scaffold, config, logging, killswitch, ulid, secrets]
status: complete
requirements:
  - INFRA-02
  - INFRA-03
  - INFRA-04
  - INFRA-06
  - INFRA-07
  - INFRA-09
  - INFRA-10
dependency-graph:
  requires: []
  provides:
    - tech_news_synth.config.Settings
    - tech_news_synth.config.load_settings
    - tech_news_synth.logging.configure_logging
    - tech_news_synth.logging.get_logger
    - tech_news_synth.ids.new_cycle_id
    - tech_news_synth.killswitch.is_paused
  affects:
    - plan-01-02 (scheduler + container) — consumes all four modules
tech-stack:
  added:
    - python 3.12
    - uv 0.11.6
    - hatchling (build backend)
    - anthropic 0.79.x
    - tweepy 4.16.x
    - scikit-learn 1.8.x
    - feedparser 6.0.11
    - httpx[http2] 0.28.x
    - sqlalchemy 2.0.49
    - psycopg[binary,pool] 3.2.x
    - alembic 1.18.x
    - apscheduler 3.10.x
    - structlog 25.5.0
    - orjson 3.10.x
    - pydantic 2.9.x / pydantic-settings 2.6.x
    - python-ulid 3.x
    - tenacity 9.1.x
    - beautifulsoup4 4.12.x / lxml 5.x
    - python-slugify 8.x / unidecode 1.4.x
    - pytest 8.x / pytest-cov / pytest-mock / respx / time-machine / ruff
  patterns:
    - src-layout package under src/tech_news_synth (D-01 / D-02)
    - pydantic-settings with SecretStr + frozen + field_validator
    - structlog → stdlib bridge with ProcessorFormatter + JSONRenderer(orjson)
    - contextvars-based binding for cycle_id and dry_run
    - OR-logic kill-switch (env flag OR marker file), single source of truth
key-files:
  created:
    - pyproject.toml
    - uv.lock
    - .gitignore (rewritten)
    - .dockerignore
    - .env.example
    - .pre-commit-config.yaml
    - src/tech_news_synth/__init__.py
    - src/tech_news_synth/config.py
    - src/tech_news_synth/ids.py
    - src/tech_news_synth/killswitch.py
    - src/tech_news_synth/logging.py
    - tests/__init__.py
    - tests/conftest.py
    - tests/unit/__init__.py
    - tests/unit/test_config.py
    - tests/unit/test_cycle_id.py
    - tests/unit/test_killswitch.py
    - tests/unit/test_logging.py
    - tests/unit/test_dry_run_logging.py
    - tests/unit/test_utc_invariants.py
    - tests/unit/test_secrets_hygiene.py
    - tests/unit/test_scheduler.py (RED STUB — Plan 02)
    - tests/unit/test_cycle_error_isolation.py (RED STUB — Plan 02)
    - tests/unit/test_signal_shutdown.py (RED STUB — Plan 02)
  modified: []
decisions:
  - Ruff DTZ rules disabled for tests/ via [tool.ruff.lint.per-file-ignores]
    (tests legitimately monkeypatch/freeze time; production src/ still enforces)
  - load_settings() re-raises ValidationError after printing to stderr; callers
    (Plan 02 __main__) own sys.exit(2) on failure
  - configure_logging removes previous handlers on re-entry to make the function
    idempotent while preserving exactly two sinks (stdout + file)
  - Env-file loading disabled in tests via PYDANTIC_SETTINGS_DISABLE_ENV_FILE;
    wired through a module-level _env_file_for_settings() helper in config.py
metrics:
  started_at: "2026-04-12T20:27:58Z"
  completed_at: "2026-04-12T20:33:00Z"
  duration_seconds: 302
  tasks_completed: 5
  commits: 6
  files_created: 24
  tests_total: 56
  tests_passing: 53
  tests_skipped: 3
  coverage_percent: 99
---

# Phase 1 Plan 1: Scaffold + Core Modules Summary

Stood up the uv-managed Python project, secret hygiene, and the four pure-core modules (`config`, `logging`, `ids`, `killswitch`) that every later phase imports. 53 unit tests pass, 3 are deliberate red stubs reserved for Plan 02, and coverage on the new modules is 99%.

## Overview

**One-liner:** Establishes the import root, frozen pydantic-settings contract, structlog JSON dual-sink pipeline, ULID cycle-id generator, and OR-logic kill-switch — all with fail-fast validation and SecretStr-based secret handling.

This plan delivers the chassis that the scheduler (Plan 01-02) plugs into. No Docker, no scheduler, no CLI dispatch yet — just the contracts.

## Tasks Completed

| # | Task | Commit | Notes |
|---|------|--------|-------|
| 1 | Project scaffold (pyproject, uv.lock, ignore files, pre-commit, tests skeleton) | `9768157` | 70-package uv resolve; hatchling src-layout |
| 2 | Settings with SecretStr + INTERVAL_HOURS validator | `aa393dc` | 31 parametrized tests (happy path, SecretStr hygiene, frozen, missing required, 24%N==0, bool coercion, database_url, DRY_RUN) |
| 3 | `ids.new_cycle_id` (ULID) + `killswitch.is_paused` | `574b858` | 8 tests — 3 for ULIDs, 5 for killswitch including marker-path configurability |
| 4 | `logging.configure_logging` dual-sink + UTC + contextvars | `e3b305b` | 8 tests across logging/dry_run/utc_invariants; ruff DTZ subprocess test included |
| 5 | Secrets hygiene tests + Plan 02 red stubs | `dad9ffa` | 6 real tests + 3 module-level pytest.skip stubs |
| — | Ruff format cleanup | `37d51c2` | Whitespace-only |

## Architecture Decisions

1. **src-layout** (D-02) with `pyproject.toml` + `[tool.hatch.build.targets.wheel] packages = ["src/tech_news_synth"]`. Tests import via `[tool.pytest.ini_options] pythonpath=["src"]` — no editable install required during pytest runs.
2. **SecretStr everywhere** for API keys and DB password (T-01-03). `repr(settings)` and `model_dump_json()` both mask as `"**********"`.
3. **`@field_validator("interval_hours")`** enforces `24 % N == 0` at construction time — catches PITFALLS #3 before APScheduler ever sees the value.
4. **`frozen=True`** on `SettingsConfigDict` prevents runtime mutation (T-01-07); attempted reassignment raises `ValidationError`.
5. **structlog → stdlib bridge** via `ProcessorFormatter`. One formatter, two handlers (stdout + file). `merge_contextvars` as the first processor so `cycle_id` / `dry_run` bound by the scheduler (Plan 02) appear on every line, including exception logs.
6. **Idempotent `configure_logging`**: removes existing handlers on re-entry. Tests assert `len(root.handlers) == 2` after two calls.
7. **ULID via python-ulid 3.x** — `str(ULID())` is monotonic-within-ms and Crockford-base32. No custom monotonic wrapper needed for v1.
8. **Kill-switch single source of truth** (`is_paused`) — the four branches (env, marker, both, none) are exercised by parametrized tests. Plan 02 scheduler must call `is_paused(settings)`, never re-implement the OR.
9. **`PYDANTIC_SETTINGS_DISABLE_ENV_FILE=1`** wired through `_env_file_for_settings()` keeps tests hermetic. Without this, tests on a developer machine with a populated `.env` would have produced flaky/irreproducible failures.
10. **Ruff config**: selected `E, F, I, UP, B, DTZ, RUF`. `DTZ` statically bans naive `datetime.now()` / `utcnow()` in `src/` (INFRA-06 safety net). Tests get a per-file DTZ ignore so `time-machine` and fixtures aren't fighting the lint.

## Deviations from Plan

### Rule 2 / Rule 3 — auto-added small corrections

1. **`[tool.ruff.lint.per-file-ignores]` for tests/** — plan didn't explicitly list it, but without it downstream tests using `time.sleep` + datetime helpers (and future tests using `time-machine`) would trip DTZ. Added now to avoid churn. Not in plan; justified as Rule 2 (test ergonomics).
2. **`_env_file_for_settings()` helper** — plan's interface snippet hardcoded `env_file=".env"`. Tests needed a way to disable this to stay hermetic, so I added the env-switch helper. Minor but load-bearing for tests 4 and 5 of `test_config.py` to be deterministic.
3. **`test_env_example_has_no_real_secrets` regex**: tightened the suspicious-value regex to ignore hyphens so it doesn't false-flag `replace-me` placeholders. Rule 1 (test correctness) — without this the test fails on the legitimate placeholder values the plan specifies.

No architectural changes. No pydantic-settings v2.x breakage hit — `SettingsConfigDict` shape matches plan.

### Authentication Gates

None — greenfield Python scaffolding has no external auth.

## Verification

### Automated (green)

```bash
uv run pytest tests/ -v --cov=tech_news_synth --cov-report=term-missing
# 53 passed, 3 skipped
# coverage: config 98%, ids 100%, killswitch 100%, logging 100% (overall 99%)

uv run ruff check .    # All checks passed
uv run ruff format --check .   # All files formatted
uv lock --check        # lockfile consistent
```

### Manual / deferred

- `docker build` + `docker compose up` smoke checks are Plan 02's responsibility (Dockerfile + compose.yaml don't exist yet).
- `gitleaks detect --no-banner` wasn't run as a plan gate (per execution_rules); the pre-commit hook will trigger it locally on staged changes.

## Requirements Coverage

| Requirement | Where Verified |
|-------------|----------------|
| INFRA-02 | `uv.lock` present, `uv lock --check` green, `pyproject.toml` pins Python 3.12 |
| INFRA-03 | `tests/unit/test_config.py::test_settings_missing_required` + happy-path |
| INFRA-04 | `tests/unit/test_secrets_hygiene.py` (6 tests) |
| INFRA-06 | `tests/unit/test_utc_invariants.py` (timestamp + ruff DTZ subprocess) |
| INFRA-07 | `tests/unit/test_logging.py` (4 tests: dual-output, contextvars, idempotency, mkdir) |
| INFRA-09 | `tests/unit/test_killswitch.py` (5 parametrized cases) |
| INFRA-10 | `tests/unit/test_config.py::test_dry_run_accepted` + `test_dry_run_logging.py` |

INFRA-05 (scheduler) and INFRA-08 (cycle-error isolation) are Plan 02's scope — red-stub test files exist in `tests/unit/` with `pytest.skip("implemented in Plan 01-02", allow_module_level=True)` so test paths are already wired.

## Known Stubs

Three test modules deliberately skipped at module level until Plan 01-02 fills them:

| File | Line | Reason |
|------|------|--------|
| tests/unit/test_scheduler.py | 10 | Scheduler lives in Plan 01-02; stub preserves Nyquist continuity |
| tests/unit/test_cycle_error_isolation.py | 9 | Error-isolation wrapper lives in Plan 01-02 |
| tests/unit/test_signal_shutdown.py | 9 | SIGTERM/SIGINT handlers live in Plan 01-02 |

These are intentional per plan Task 5 and `execution_rules.Wave 0`. Plan 01-02's Task 1 replaces the skip bodies.

## Handoff to Plan 01-02

All symbols are importable from `tech_news_synth.*`:

```python
from tech_news_synth.config import Settings, load_settings
from tech_news_synth.logging import configure_logging, get_logger
from tech_news_synth.ids import new_cycle_id
from tech_news_synth.killswitch import is_paused
```

Plan 02 pattern (from RESEARCH.md / PLAN.md `<interfaces>`):

```python
settings = load_settings()
configure_logging(settings)
# In run_cycle:
cid = new_cycle_id()
structlog.contextvars.bind_contextvars(cycle_id=cid, dry_run=settings.dry_run)
paused, reason = is_paused(settings)
if paused:
    log.info("cycle_paused", paused_by=reason, status="paused")
    return
```

Plan 02 must:
- Build the `BlockingScheduler` + `CronTrigger(hour=f"*/{settings.interval_hours}", timezone=UTC)`.
- Replace the three red-stub test files with real behavior tests.
- Add the Dockerfile + compose.yaml wiring `/data` volume and `./config/sources.yaml` bind mount.
- Install SIGTERM/SIGINT handlers that call `scheduler.shutdown(wait=True)` exactly once.
- Add a first-tick-on-boot pattern per D-07.

## Self-Check: PASSED

- All 24 key files exist on disk.
- 6 commits verified present: `9768157`, `aa393dc`, `574b858`, `e3b305b`, `dad9ffa`, `37d51c2`.
- `uv run pytest tests/ -q` exits 0 with 53 passed, 3 skipped (designed).
- `uv run ruff check .` and `uv run ruff format --check .` both clean.
- No TODO/FIXME placeholders in production code (only in the documented red-stub tests).
