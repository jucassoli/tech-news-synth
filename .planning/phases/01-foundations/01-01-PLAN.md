---
phase: 01-foundations
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - pyproject.toml
  - uv.lock
  - .gitignore
  - .dockerignore
  - .env.example
  - .pre-commit-config.yaml
  - src/tech_news_synth/__init__.py
  - src/tech_news_synth/config.py
  - src/tech_news_synth/logging.py
  - src/tech_news_synth/ids.py
  - src/tech_news_synth/killswitch.py
  - tests/__init__.py
  - tests/conftest.py
  - tests/unit/__init__.py
  - tests/unit/test_config.py
  - tests/unit/test_secrets_hygiene.py
  - tests/unit/test_logging.py
  - tests/unit/test_cycle_id.py
  - tests/unit/test_killswitch.py
  - tests/unit/test_dry_run_logging.py
  - tests/unit/test_utc_invariants.py
autonomous: true
requirements:
  - INFRA-02
  - INFRA-03
  - INFRA-04
  - INFRA-06
  - INFRA-07
  - INFRA-09
  - INFRA-10

must_haves:
  truths:
    - "Running `uv sync` on a fresh checkout installs all pinned deps into `.venv` from `uv.lock`."
    - "Importing `tech_news_synth.config.Settings()` with a complete .env returns a frozen, validated settings object; importing with a missing key raises pydantic ValidationError with the offending field name."
    - "`configure_logging(settings)` produces JSON lines on stdout AND on `/data/logs/app.jsonl` (or configured path), each line containing any cycle_id/dry_run bound via structlog contextvars."
    - "`new_cycle_id()` returns a 26-char Crockford base32 ULID string; two IDs generated 1ms apart sort lexicographically in generation order."
    - "`is_paused()` returns (True, 'env') when PAUSED=1, (True, 'marker') when `/data/paused` exists, (True, 'both') when both, (False, None) otherwise."
    - "`.env` is gitignored and dockerignored; `.env.example` is tracked; gitleaks pre-commit hook is installed and runs on staged changes."
    - "Ruff passes on src/ and tests/; pytest runs the unit suite green with `pythonpath=['src']` honored."
  artifacts:
    - path: "pyproject.toml"
      provides: "Python 3.12 project metadata, pinned deps (anthropic, tweepy, sklearn, feedparser, httpx, sqlalchemy, psycopg, alembic, apscheduler, structlog, pydantic, pydantic-settings, python-ulid, orjson, tenacity, beautifulsoup4, lxml, python-slugify, unidecode), dev-group (pytest, pytest-mock, respx, time-machine, pytest-cov, ruff), [tool.ruff], [tool.pytest.ini_options] with pythonpath=['src']"
    - path: "uv.lock"
      provides: "Resolved lockfile from `uv lock`"
    - path: "src/tech_news_synth/config.py"
      provides: "Settings(BaseSettings, frozen=True) with SecretStr secrets, INTERVAL_HOURS validator (24 % N == 0), PAUSED and DRY_RUN bool flags, DB DSN builder"
      contains: "class Settings"
    - path: "src/tech_news_synth/logging.py"
      provides: "configure_logging(settings) dual-output (stdout + file handler on settings.log_dir) via structlog → stdlib bridge with contextvars merge, orjson JSONRenderer, UTC TimeStamper"
      contains: "def configure_logging"
    - path: "src/tech_news_synth/ids.py"
      provides: "new_cycle_id() -> str wrapping python-ulid"
      contains: "def new_cycle_id"
    - path: "src/tech_news_synth/killswitch.py"
      provides: "is_paused(settings) -> tuple[bool, str | None] implementing PAUSED env OR /data/paused marker OR logic"
      contains: "def is_paused"
    - path: ".env.example"
      provides: "Every Settings field listed with dummy value (anthropic_api_key, x_consumer_key, x_consumer_secret, x_access_token, x_access_token_secret, postgres_password, postgres_host, postgres_db, postgres_user, interval_hours, paused, dry_run, log_dir)"
    - path: ".pre-commit-config.yaml"
      provides: "gitleaks v8.21.2 + pre-commit-hooks v5.0.0 + ruff-pre-commit v0.8.4 hooks"
  key_links:
    - from: "src/tech_news_synth/logging.py"
      to: "structlog.contextvars"
      via: "merge_contextvars processor"
      pattern: "merge_contextvars"
    - from: "src/tech_news_synth/killswitch.py"
      to: "os.environ['PAUSED'] AND pathlib.Path(settings.paused_marker_path)"
      via: "OR evaluation returning reason string"
      pattern: "paused_by"
    - from: "src/tech_news_synth/config.py"
      to: "pydantic.SecretStr"
      via: "typed fields for all API keys"
      pattern: "SecretStr"
---

<objective>
Lay down the repository scaffolding and the four pure-core modules (`config`, `logging`, `ids`, `killswitch`) that every later module in this phase — and every downstream phase — depends on. No Docker, no scheduler, no CLI dispatch yet. This plan delivers: (a) the uv-managed Python project with pinned deps and lockfile, (b) secret hygiene (gitignore, dockerignore, .env.example, pre-commit gitleaks), (c) the `Settings` class with fail-fast validation including the critical `24 % INTERVAL_HOURS == 0` rule (PITFALLS #3), (d) the structlog dual-output pipeline that binds `cycle_id` and `dry_run` via contextvars, (e) the ULID cycle-id generator, and (f) the OR-logic kill-switch. Full unit test suite covers every requirement slice.

Purpose: Establish the import root, config contract, and log contract that every later phase writes through. Breaking these at phase boundaries is the biggest risk; nailing them once here pays back through 8 phases.

Output: A green `uv run pytest tests/ -q` with tests validating every INFRA-XX requirement mapped to this plan.
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
@CLAUDE.md

<interfaces>
<!-- These are NEW interfaces this plan creates. Downstream tasks in Plan 02 and every later phase consume them. -->

From src/tech_news_synth/config.py (to be created):
```python
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )
    # runtime knobs
    interval_hours: int = 2          # must satisfy 24 % N == 0
    paused: bool = False
    dry_run: bool = False
    log_dir: str = "/data/logs"
    paused_marker_path: str = "/data/paused"

    # secrets (SecretStr — never raw)
    anthropic_api_key: SecretStr
    x_consumer_key: SecretStr
    x_consumer_secret: SecretStr
    x_access_token: SecretStr
    x_access_token_secret: SecretStr

    # postgres
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "tech_news_synth"
    postgres_user: str = "app"
    postgres_password: SecretStr

    @property
    def database_url(self) -> str: ...

def load_settings() -> Settings: ...
```

From src/tech_news_synth/logging.py (to be created):
```python
import structlog
def configure_logging(settings: "Settings") -> None: ...
def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger: ...
```

From src/tech_news_synth/ids.py (to be created):
```python
def new_cycle_id() -> str:
    """Return a 26-char Crockford base32 ULID string."""
```

From src/tech_news_synth/killswitch.py (to be created):
```python
def is_paused(settings: "Settings") -> tuple[bool, str | None]:
    """
    Returns (True, 'env') | (True, 'marker') | (True, 'both') | (False, None).
    Checks settings.paused AND pathlib.Path(settings.paused_marker_path).exists().
    """
```
</interfaces>
</context>

<tasks>

<task type="auto" id="01.01.01">
  <name>Task 1: Project scaffold — pyproject, uv.lock, gitignore/dockerignore, .env.example, pre-commit, test dir</name>
  <files>
    pyproject.toml
    uv.lock
    .gitignore
    .dockerignore
    .env.example
    .pre-commit-config.yaml
    src/tech_news_synth/__init__.py
    tests/__init__.py
    tests/conftest.py
    tests/unit/__init__.py
  </files>
  <action>
Create the project scaffold. Covers INFRA-02 (uv + pinned lockfile + Python 3.12) and INFRA-04 (secret hygiene + pre-commit). No runtime code yet — just the skeleton every other task writes into.

**pyproject.toml** — use hatchling backend, src-layout per D-02:
- `[project]`: name="tech-news-synth", version="0.1.0", requires-python=">=3.12,<3.13"
- `[project] dependencies` — pin from RESEARCH.md §Standard Stack (Core + Supporting):
  `anthropic>=0.79,<0.80`, `tweepy>=4.14,<5`, `scikit-learn>=1.8,<2`, `feedparser>=6.0.11,<7`,
  `httpx[http2]>=0.28,<0.29`, `sqlalchemy>=2.0.40,<2.1`, `psycopg[binary,pool]>=3.2,<4`,
  `alembic>=1.18,<2`, `apscheduler>=3.10,<4`, `structlog>=25,<26`, `orjson>=3.10,<4`,
  `pydantic>=2.9,<3`, `pydantic-settings>=2.6,<3`, `python-ulid>=3,<4`, `tenacity>=9,<10`,
  `beautifulsoup4>=4.12,<5`, `lxml>=5,<6`, `python-slugify>=8,<9`, `unidecode>=1.3,<2`
- `[dependency-groups] dev`: `pytest>=8,<9`, `pytest-mock`, `pytest-cov`, `respx`, `time-machine`, `ruff>=0.8,<1`
- `[build-system]`: requires=["hatchling"], build-backend="hatchling.build"
- `[tool.hatch.build.targets.wheel]`: `packages = ["src/tech_news_synth"]`
- `[tool.pytest.ini_options]`: `testpaths=["tests"]`, `pythonpath=["src"]`, `addopts="-ra"`
- `[tool.ruff]`: `target-version="py312"`, `line-length=100`, `src=["src","tests"]`
- `[tool.ruff.lint]`: `select=["E","F","I","UP","B","DTZ","RUF"]` — DTZ bans naive `datetime.now()` (enforces INFRA-06 statically)

Then generate lockfile: `uv lock` → commits `uv.lock`. If `uv` not installed locally, print the install one-liner (`curl -LsSf https://astral.sh/uv/install.sh | sh`) and stop — operator runs it, then re-runs the task.

**.gitignore** — at minimum: `.env`, `.env.*` (but `!.env.example`), `.venv/`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`, `.ruff_cache/`, `dist/`, `build/`, `.coverage`, `htmlcov/`.

**.dockerignore** — per RESEARCH.md Pattern 1: `.env`, `.env.*` (but `!.env.example`), `.venv/`, `.git/`, `.gitignore`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.planning/`, `tests/`, `docs/`, `README.md`, `.pre-commit-config.yaml`, `.github/`.

**.env.example** — every Settings field with a placeholder (NOT a real secret). Order: runtime knobs first, then secrets, then postgres. Example lines:
```
# Runtime
INTERVAL_HOURS=2
PAUSED=0
DRY_RUN=0
LOG_DIR=/data/logs
PAUSED_MARKER_PATH=/data/paused

# Anthropic
ANTHROPIC_API_KEY=sk-ant-replace-me

# X OAuth 1.0a User Context (4 secrets)
X_CONSUMER_KEY=replace-me
X_CONSUMER_SECRET=replace-me
X_ACCESS_TOKEN=replace-me
X_ACCESS_TOKEN_SECRET=replace-me

# Postgres
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=tech_news_synth
POSTGRES_USER=app
POSTGRES_PASSWORD=replace-me
```

**.pre-commit-config.yaml** — verbatim per RESEARCH.md Pattern 8 (gitleaks v8.21.2, pre-commit-hooks v5.0.0 with check-added-large-files/end-of-file-fixer/trailing-whitespace/check-yaml/check-toml, ruff-pre-commit v0.8.4 with `id: ruff` args=[--fix] + `id: ruff-format`).

**src/tech_news_synth/__init__.py**: just `__version__ = "0.1.0"`.

**tests/__init__.py**, **tests/unit/__init__.py**: empty files (pytest discovery).

**tests/conftest.py** — two shared fixtures per VALIDATION.md Wave 0:
```python
import os, pathlib, pytest
from unittest.mock import patch

@pytest.fixture
def monkeypatch_env(monkeypatch):
    """Set a complete valid env for Settings()."""
    env = {
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "X_CONSUMER_KEY": "k", "X_CONSUMER_SECRET": "s",
        "X_ACCESS_TOKEN": "t", "X_ACCESS_TOKEN_SECRET": "ts",
        "POSTGRES_PASSWORD": "pw",
        "INTERVAL_HOURS": "2", "PAUSED": "0", "DRY_RUN": "0",
        "LOG_DIR": "/tmp/tns-logs", "PAUSED_MARKER_PATH": "/tmp/tns-paused",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Ensure real .env is NOT loaded during tests
    monkeypatch.setenv("PYDANTIC_SETTINGS_DISABLE_ENV_FILE", "1")
    return env

@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Provide an isolated /data-like tree for logs and marker."""
    d = tmp_path / "data"
    (d / "logs").mkdir(parents=True)
    monkeypatch.setenv("LOG_DIR", str(d / "logs"))
    monkeypatch.setenv("PAUSED_MARKER_PATH", str(d / "paused"))
    return d
```

Per D-02: ensure `pyproject.toml` `[tool.pytest.ini_options] pythonpath=["src"]` lets tests import `tech_news_synth.*` without installing the package.

**Security decisions embedded:**
- `SecretStr` will be used in config.py (Task 2) — this task sets up the hygiene walls around it.
- gitleaks runs pre-commit on staged changes — blocks accidental `.env` commits (threat T-secret-leak).
- `.dockerignore` keeps `.env` out of image layers (threat T-env-in-image).
  </action>
  <verify>
<automated>uv lock --check && uv run ruff check . && test -f .env.example && test -f .gitignore && test -f .dockerignore && test -f .pre-commit-config.yaml && grep -q "^\.env$" .gitignore && grep -q "^\.env$" .dockerignore && ! grep -qE "^(ANTHROPIC_API_KEY|X_[A-Z_]+|POSTGRES_PASSWORD)=(sk-ant-[a-zA-Z0-9]{10,}|[A-Z0-9]{16,})" .env.example</automated>
  </verify>
  <done>
    - `pyproject.toml` + `uv.lock` present, `uv lock --check` exits 0
    - `ruff check .` exits 0 on empty tree
    - `.gitignore` excludes `.env`, `.dockerignore` excludes `.env`
    - `.env.example` present with all required keys, no real secrets
    - `.pre-commit-config.yaml` references gitleaks v8.21.2
    - `tests/conftest.py` provides `monkeypatch_env` and `tmp_data_dir` fixtures
    - `src/tech_news_synth/__init__.py` exports `__version__`
  </done>
</task>

<task type="auto" id="01.01.02" tdd="true">
  <name>Task 2: Settings (config.py) — pydantic-settings fail-fast with SecretStr + INTERVAL_HOURS validator</name>
  <files>
    src/tech_news_synth/config.py
    tests/unit/test_config.py
  </files>
  <behavior>
    - Test 1 (happy): With full valid env, `load_settings()` returns a Settings where `interval_hours=2`, `paused=False`, `dry_run=False`, `anthropic_api_key.get_secret_value() == "sk-ant-test"`.
    - Test 2 (SecretStr hygiene): `repr(settings)` / `str(settings)` / JSON-dumped settings do NOT leak any raw secret value; they show `'**********'` or equivalent pydantic mask.
    - Test 3 (frozen): assigning `settings.interval_hours = 7` raises `pydantic.ValidationError` or `ValidationError`-equivalent (frozen model).
    - Test 4 (missing required): unset ANTHROPIC_API_KEY → `load_settings()` raises `pydantic.ValidationError`, error message names `anthropic_api_key`.
    - Test 5 (INTERVAL_HOURS cron validator — PITFALLS #3): values {1,2,3,4,6,8,12,24} pass; values {5,7,9,10,11,13} raise ValidationError mentioning "24 % interval_hours" or similar.
    - Test 6 (bool coercion — PITFALLS #9): `PAUSED=0`, `PAUSED=false`, `PAUSED=no`, `PAUSED=off` → `paused is False`; `PAUSED=1`, `PAUSED=true`, `PAUSED=yes`, `PAUSED=on` → `paused is True`.
    - Test 7 (database_url): composes `postgresql+psycopg://app:pw@postgres:5432/tech_news_synth`; the secret is materialized via `get_secret_value()` (NOT `str(SecretStr)`).
    - Test 8 (DRY_RUN accepted — INFRA-10): `DRY_RUN=1` → `settings.dry_run is True`.
  </behavior>
  <action>
Write `tests/unit/test_config.py` FIRST (red), then implement `src/tech_news_synth/config.py` to make them green.

**config.py** — follow RESEARCH.md Pattern 4 (D-03, Claude's discretion on exact shape):
- `class Settings(BaseSettings)` with `model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore", frozen=True)`.
- Fields exactly as declared in `<interfaces>` block above.
- Use `Field(ge=1, le=24)` on `interval_hours`.
- `@field_validator("interval_hours")` classmethod enforcing `24 % v == 0` — raise `ValueError("INTERVAL_HOURS must divide 24 evenly — allowed: 1,2,3,4,6,8,12,24")`. This implements PITFALLS #3 and INFRA-05's configurable interval.
- `database_url` property uses `self.postgres_password.get_secret_value()` — never `str(secret)`.
- Module-level `load_settings()` function that constructs `Settings()` and catches `ValidationError`, printing `f"Configuration error:\n{e}"` to stderr then re-raising. Keeps the pattern explicit — callers can `sys.exit(2)` on catch (Plan 02's __main__ does this).
- NO logging at module import time (PITFALLS #5). Do not call `structlog.get_logger()` at module scope.

Honors D-01..D-03 (package name, src-layout, config path), D-08 (paused marker path field), D-10 (DRY_RUN bound later via context).

**Security (threat T-secret-leak, T-config-leak):**
- Every API key / password uses `SecretStr`. Loose `str` for secrets is forbidden.
- `extra="ignore"` to not crash on unmodeled vars injected by Compose/OS.
- `frozen=True` prevents runtime mutation (integrity).

**Decision refs:** Implements INFRA-03 (fail-fast), INFRA-10 (DRY_RUN accepted), parts of INFRA-05 (INTERVAL_HOURS validator), and the field base for INFRA-09 (paused flag + marker path).
  </action>
  <verify>
<automated>uv run pytest tests/unit/test_config.py -q</automated>
  </verify>
  <done>
    - All 8 behavior tests pass.
    - `ruff check src/tech_news_synth/config.py` clean.
    - Attempting `str(settings)` or `repr(settings)` emits `**********` for every SecretStr field (verified in Test 2).
    - `load_settings()` with missing `ANTHROPIC_API_KEY` exits non-zero with a message naming the field (Test 4).
  </done>
</task>

<task type="auto" id="01.01.03" tdd="true">
  <name>Task 3: cycle_id (ids.py) + kill-switch (killswitch.py) — pure utilities</name>
  <files>
    src/tech_news_synth/ids.py
    src/tech_news_synth/killswitch.py
    tests/unit/test_cycle_id.py
    tests/unit/test_killswitch.py
  </files>
  <behavior>
    **test_cycle_id.py:**
    - Test 1: `new_cycle_id()` returns a 26-char string matching `^[0-9A-HJKMNP-TV-Z]{26}$` (Crockford base32).
    - Test 2: Two IDs generated consecutively (same ms is fine with python-ulid's monotonic) sort lexicographically in generation order. Use `time-machine` to advance 1ms between calls OR use python-ulid's monotonic guarantee — assert `sorted([id1, id2]) == [id1, id2]`.
    - Test 3: 1000 IDs are all distinct.

    **test_killswitch.py** (parametrized — INFRA-09):
    - Test A: PAUSED=0, no marker → `(False, None)`.
    - Test B: PAUSED=1, no marker → `(True, "env")`.
    - Test C: PAUSED=0, marker file exists → `(True, "marker")`.
    - Test D: PAUSED=1, marker file exists → `(True, "both")`.
    - Test E: marker path is configurable via Settings — pointing at `tmp_data_dir / "paused"` honors it.
  </behavior>
  <action>
Write tests first (red), then implement.

**ids.py** (per RESEARCH.md §Code Examples + D-09):
```python
from ulid import ULID

def new_cycle_id() -> str:
    """Return a 26-char Crockford base32 ULID string, monotonic within ms."""
    return str(ULID())
```
That's it. `python-ulid`'s `ULID()` is already monotonic within the same ms. If test 2 flakes due to same-ms collisions across generation, switch to `ulid.monotonic.ULID()` per library docs.

**killswitch.py** (per RESEARCH.md Pattern 6 + D-08):
```python
from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tech_news_synth.config import Settings


def is_paused(settings: "Settings") -> tuple[bool, str | None]:
    """
    INFRA-09: PAUSED env OR /data/paused marker → pause cycle.

    Returns (True, reason) where reason is 'env', 'marker', or 'both'.
    Returns (False, None) if neither is set.
    """
    env_paused = bool(settings.paused)
    marker_exists = Path(settings.paused_marker_path).exists()

    if env_paused and marker_exists:
        return (True, "both")
    if env_paused:
        return (True, "env")
    if marker_exists:
        return (True, "marker")
    return (False, None)
```

Pure function — no I/O beyond `Path.exists()`, no side effects. Scheduler (Plan 02) will call this at cycle start and short-circuit with a structured log line if paused.

**Threat T-killswitch-bypass:** The function is the single source of truth. Do NOT duplicate the OR-logic in the scheduler; the scheduler calls `is_paused()` and trusts its result. A later phase adding a "pause everything except health" mode extends THIS function, not bypasses it.

**Decision refs:** D-08 (OR logic, `paused_by` label), D-09 (ULID format), INFRA-09 and the cross-cutting cycle_id requirement.
  </action>
  <verify>
<automated>uv run pytest tests/unit/test_cycle_id.py tests/unit/test_killswitch.py -q</automated>
  </verify>
  <done>
    - All 8 behavior tests pass (3 for ids, 5 for killswitch).
    - `is_paused` produces distinct reasons for each OR branch; `both` case exercised.
    - ULID format and sortability verified.
    - ruff clean.
  </done>
</task>

<task type="auto" id="01.01.04" tdd="true">
  <name>Task 4: Logging (logging.py) — structlog dual-output + cycle_id/dry_run contextvars</name>
  <files>
    src/tech_news_synth/logging.py
    tests/unit/test_logging.py
    tests/unit/test_dry_run_logging.py
    tests/unit/test_utc_invariants.py
  </files>
  <behavior>
    **test_logging.py (INFRA-07):**
    - Test 1: After `configure_logging(settings)` pointing at `tmp_data_dir/logs`, `get_logger().info("hello", foo=1)` emits a JSON line to stdout (captured via capsys) AND appends a JSON line to `tmp_data_dir/logs/app.jsonl`. Both lines parse as JSON and contain `event="hello"`, `foo=1`, `timestamp` (ISO 8601 UTC ending in `+00:00` or `Z`), and `level="info"`.
    - Test 2: After `bind_contextvars(cycle_id="01ARZ3NDEKTSV4RRFFQ69G5FAV")` and then logging, every subsequent line on both sinks contains `cycle_id="01ARZ3NDEKTSV4RRFFQ69G5FAV"`. After `clear_contextvars()`, the next line does NOT contain `cycle_id`.
    - Test 3: `configure_logging` is idempotent — calling twice does NOT duplicate handlers (assert `len(logging.getLogger().handlers) <= 2` after two calls).
    - Test 4: Log dir is created if missing (PITFALLS #8).

    **test_dry_run_logging.py (INFRA-10):**
    - Test 1: After `bind_contextvars(dry_run=True)`, log lines contain `dry_run=true` on both sinks.
    - Test 2: After `bind_contextvars(dry_run=False)`, lines contain `dry_run=false`.

    **test_utc_invariants.py (INFRA-06):**
    - Test 1: Parse the `timestamp` field from one emitted log line; assert it ends in `+00:00` or `Z` (UTC).
    - Test 2: Grep the src/ tree for forbidden patterns — `datetime.now()` without `timezone.utc`, `datetime.utcnow()`. The test runs `subprocess.run(["ruff", "check", "--select=DTZ", "src/"])` and asserts returncode 0. (Ruff DTZ rules enforce timezone-aware datetimes statically.)
  </behavior>
  <action>
Write tests first, then implement per RESEARCH.md Pattern 5.

**logging.py** — dual-output via structlog → stdlib bridge:
```python
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import orjson
import structlog

if TYPE_CHECKING:
    from tech_news_synth.config import Settings

_CONFIGURED = False


def _orjson_dumps(obj, default=None) -> str:
    return orjson.dumps(obj, default=default).decode("utf-8")


def configure_logging(settings: "Settings") -> None:
    """
    INFRA-07: JSON logs to stdout AND /data/logs/app.jsonl.
    INFRA-06: UTC timestamps everywhere.
    INFRA-10: dry_run + cycle_id bound via contextvars appear on every line.
    Idempotent — safe to call twice.
    """
    global _CONFIGURED

    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)   # PITFALLS #8
    log_file = log_dir / "app.jsonl"

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),  # INFRA-06
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processor=structlog.processors.JSONRenderer(serializer=_orjson_dumps),
    )

    root = logging.getLogger()
    if _CONFIGURED:
        # idempotent: clear existing handlers we installed
        for h in list(root.handlers):
            root.removeHandler(h)

    stdout_h = logging.StreamHandler(sys.stdout)
    stdout_h.setFormatter(formatter)

    file_h = logging.FileHandler(log_file, encoding="utf-8")
    file_h.setFormatter(formatter)

    root.addHandler(stdout_h)
    root.addHandler(file_h)
    root.setLevel(logging.INFO)

    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
```

**Threat T-log-pii:** The processor chain does NOT auto-bind `settings` into context. Callers must use explicit `bind_contextvars()` for `cycle_id` and `dry_run` only. `SecretStr` in config.py ensures accidental inclusion renders as `**********`.

**test_utc_invariants.py note:** The ruff subprocess test is a belt-and-suspenders check; ruff's DTZ rules (configured in pyproject.toml from Task 1) also run in CI/pre-commit. The test asserts the rule is wired and the codebase currently passes.

**Decision refs:** INFRA-06 (UTC), INFRA-07 (dual output + cycle_id on every line), INFRA-10 (DRY_RUN visible in logs), D-10 (contextvars bind).
  </action>
  <verify>
<automated>uv run pytest tests/unit/test_logging.py tests/unit/test_dry_run_logging.py tests/unit/test_utc_invariants.py -q</automated>
  </verify>
  <done>
    - All behavior tests pass.
    - JSON lines on both stdout and `/data/logs/app.jsonl` contain UTC timestamps, cycle_id when bound, dry_run when bound.
    - `configure_logging` is idempotent.
    - Ruff DTZ rules pass on `src/` (no naive datetime usage).
  </done>
</task>

<task type="auto" id="01.01.05">
  <name>Task 5: Secrets hygiene test + red stubs for Plan 02 requirements</name>
  <files>
    tests/unit/test_secrets_hygiene.py
    tests/unit/test_scheduler.py
    tests/unit/test_cycle_error_isolation.py
    tests/unit/test_signal_shutdown.py
  </files>
  <action>
Create one real test file (INFRA-04 coverage) plus three red-stub test files that Plan 02 will make green. This preserves Nyquist continuity (every requirement has an automated verify command pre-declared) and avoids mid-execution surprises.

**tests/unit/test_secrets_hygiene.py (INFRA-04) — REAL TESTS, must pass now:**
- Test 1: Repo tree contains `.env.example` (tracked).
- Test 2: Repo tree does NOT contain a tracked `.env` (use `subprocess.run(["git", "ls-files", ".env"], capture_output=True)` → stdout empty).
- Test 3: `.gitignore` contains a line matching `^\.env$` (anchored, not just substring).
- Test 4: `.dockerignore` contains a line matching `^\.env$`.
- Test 5: `.pre-commit-config.yaml` exists AND references `gitleaks` (simple substring check is fine).
- Test 6: `.env.example` does NOT contain high-entropy strings resembling real secrets — regex scan for `sk-ant-[a-zA-Z0-9]{20,}` or 32+-char base64-ish tokens; assert no match. (Defense in depth: even if an operator accidentally copies `.env` → `.env.example`, this test catches it.)

**tests/unit/test_scheduler.py (INFRA-05) — RED STUB (imports will fail until Plan 02 lands):**
```python
"""RED STUB — Plan 02 implements tech_news_synth.scheduler.

Tests will be filled in by Plan 02 Task 1. This file exists now so Nyquist
continuity is preserved: every requirement has a pre-declared test path.
"""
import pytest

pytest.skip("Plan 02 implements scheduler; filled in there", allow_module_level=True)
```

**tests/unit/test_cycle_error_isolation.py (INFRA-08) — RED STUB:**
Same skip pattern, with docstring noting Plan 02 Task 1 fills it.

**tests/unit/test_signal_shutdown.py (SIGTERM/SIGINT cross-cutting) — RED STUB:**
Same skip pattern, with docstring noting Plan 02 Task 1 fills it.

**Why skip-stubs not xfail:** `xfail` counts as "passing" in CI green — confusing. `pytest.skip(..., allow_module_level=True)` is explicit: "not implemented yet, filled in Plan 02." When Plan 02 replaces these bodies, the skip is removed and tests go green.

**Decision refs:** INFRA-04 (secret hygiene, enforced now); Nyquist-compliance from VALIDATION.md (every requirement has an automated command pre-declared).
  </action>
  <verify>
<automated>uv run pytest tests/unit/test_secrets_hygiene.py -q && uv run pytest tests/ -q --co | grep -q "test_scheduler"</automated>
  </verify>
  <done>
    - `test_secrets_hygiene.py` has 6 passing tests.
    - The three red-stub files are collected by pytest (visible in `--co`) but skipped with the documented reason.
    - Running `uv run pytest tests/ -q` at end of this plan: all real tests pass, the three stubs show as SKIPPED with reason "Plan 02 implements ...".
  </done>
</task>

</tasks>

<validation_refs>
Per `.planning/phases/01-foundations/01-VALIDATION.md`:

| Task | Requirement | Automated Command (from VALIDATION.md) |
|------|-------------|----------------------------------------|
| 01.01.01 | INFRA-02, INFRA-04 | `docker build ...` (deferred to Plan 02) + `gitleaks detect --no-banner` (pre-commit) |
| 01.01.01 | INFRA-04 (env hygiene subset) | `uv run pytest tests/unit/test_secrets_hygiene.py -q` (Task 5) |
| 01.01.02 | INFRA-03, INFRA-10 | `uv run pytest tests/unit/test_config.py -q` |
| 01.01.03 | INFRA-09 + cycle_id cross-cutting | `uv run pytest tests/unit/test_cycle_id.py tests/unit/test_killswitch.py -q` |
| 01.01.04 | INFRA-06, INFRA-07, INFRA-10 | `uv run pytest tests/unit/test_logging.py tests/unit/test_dry_run_logging.py tests/unit/test_utc_invariants.py -q` |
| 01.01.05 | INFRA-04 (full) | `uv run pytest tests/unit/test_secrets_hygiene.py -q && gitleaks detect --no-banner` |

Full-suite command at plan end: `uv run pytest tests/ -v --cov=tech_news_synth --cov-report=term-missing`. Coverage target: ≥80% on `config.py`, `logging.py`, `killswitch.py`, `ids.py`.
</validation_refs>

<threat_model>
## Trust Boundaries (from RESEARCH.md §Security Domain)

| Boundary | Description |
|----------|-------------|
| Host filesystem → Python process | `.env` loaded via pydantic-settings (env_file or OS env); `./config/*.yaml` read via bind mount (Plan 02); `/data/logs/*.jsonl` written via file handler |
| Git working tree → Git history | `.env` must never cross; gitleaks pre-commit hook enforces |
| Source tree → Docker image layers | `.env` must never cross; `.dockerignore` enforces (Plan 02 builds the image) |
| Runtime process → Log sinks (stdout, file) | Log payloads may contain exception text and operator-supplied data; SecretStr prevents raw secret inclusion |
| Operator env → Settings object | pydantic-settings validates every field at boot; frozen=True prevents runtime mutation |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-01-env-committed | Information Disclosure | `.env` in git history | mitigate | `.gitignore` line `^\.env$` (Task 1); gitleaks pre-commit hook v8.21.2 (Task 1); `tests/unit/test_secrets_hygiene.py` asserts both (Task 5); `.env.example` is the only env file tracked. |
| T-01-02-env-in-image | Information Disclosure | Docker image layer carrying `.env` | mitigate | `.dockerignore` line `^\.env$` (Task 1). Image build is Plan 02; this plan only pre-installs the dockerignore. |
| T-01-03-secret-in-logs | Information Disclosure | structlog rendering `Settings` or a `SecretStr` field | mitigate | All API keys + DB password typed `SecretStr` in `config.py` (Task 2); test_config.py Test 2 asserts `repr(settings)` masks every secret (Task 2); logging pipeline never auto-binds `settings` into context — callers must name specific fields (Task 4). |
| T-01-04-config-loose-coercion | Tampering / Input Validation | `PAUSED=0` etc. parsed as truthy string | mitigate | `paused: bool` typed via pydantic; Test 6 of test_config.py exercises the full truth table (Task 2). |
| T-01-05-crontrigger-stride | Integrity (operator surprise, not security but integrity of cadence contract) | `CronTrigger(hour="*/N")` with 24 % N != 0 | mitigate | `@field_validator("interval_hours")` in config.py rejects non-divisors at boot (Task 2); Test 5 enforces. PITFALLS #3. |
| T-01-06-naive-datetime | Integrity (UTC invariant breakage cascades into INFRA-06 and all later TIMESTAMPTZ compares) | Any `datetime.now()` without tz | mitigate | Ruff `DTZ` lint rules enabled in pyproject.toml (Task 1); test_utc_invariants.py Test 2 runs ruff subprocess (Task 4). Plus `TimeStamper(utc=True)` in logging. |
| T-01-07-mutable-settings | Tampering | Runtime code mutating `settings` to bypass checks | mitigate | `frozen=True` on Settings model_config (Task 2); Test 3 verifies mutation raises. |
| T-01-08-logging-before-config | Integrity (log contract breakage) | Module-level `structlog.get_logger()` call → plain console output before `configure_logging` | mitigate | Pattern: never log at import time. Task 4's `logging.py` docstring makes this explicit; PITFALLS #5 cited. No test — detected by manual inspection of Plan 02's `__main__.py`. |
| T-01-09-killswitch-bypass | Bypass (Elevation adjacent) | Scheduler duplicates OR logic and diverges from `is_paused()` | accept+convention | Single-source-of-truth: `killswitch.is_paused()` (Task 3). Plan 02's scheduler calls this function, does NOT re-implement. Code review enforces. |
| T-01-10-log-volume-path-missing | Denial of Service (first boot fails) | `/data/logs/` doesn't exist on fresh volume → FileHandler crashes | mitigate | `log_dir.mkdir(parents=True, exist_ok=True)` at top of `configure_logging` (Task 4); Test 4 of test_logging.py verifies. PITFALLS #8. |

**ASVS coverage:** V5 (all inputs validated via pydantic) — T-01-04, T-01-05. V6 partial (SecretStr) — T-01-03. V7 (structured logs, no secret payloads) — T-01-03, T-01-08. V14 (secure config) — T-01-01, T-01-02, T-01-07.

**Accepted risks:** None in this plan requiring user sign-off. T-01-09 is a convention enforced by code review — the `is_paused()` function is small enough that duplication is unlikely; documented explicitly.
</threat_model>

<verification>
After all 5 tasks:

```bash
uv run pytest tests/ -v --cov=tech_news_synth --cov-report=term-missing
uv run ruff check . && uv run ruff format --check .
gitleaks detect --no-banner   # optional local check; pre-commit runs this on staged changes
```

Expected:
- All non-stub tests green (test_config, test_logging, test_dry_run_logging, test_utc_invariants, test_cycle_id, test_killswitch, test_secrets_hygiene).
- 3 SKIPPED tests with reason "Plan 02 implements ..." — this is Nyquist-compliant because the verify paths exist and fire automatically once Plan 02 fills them.
- Coverage ≥80% on `config.py`, `logging.py`, `killswitch.py`, `ids.py`.
- Ruff clean (lint + format).
- gitleaks reports no leaks.
</verification>

<success_criteria>
This plan is complete when:
1. `uv run pytest tests/ -q` exits 0 (skips allowed for Plan 02 stubs, failures not allowed).
2. Running `python -c "from tech_news_synth.config import load_settings; s = load_settings(); print(s.interval_hours)"` with a valid `.env` prints `2` and never leaks a secret.
3. Running the same with `ANTHROPIC_API_KEY` unset prints a pydantic ValidationError naming the field to stderr and exits non-zero.
4. `ruff check .` exits 0.
5. A hand-written script using `configure_logging()` + `bind_contextvars(cycle_id="...")` + `get_logger().info(...)` produces one JSON line on stdout AND one appended to `{log_dir}/app.jsonl`, both containing the bound `cycle_id`.
6. All 10 INFRA requirement IDs owned by this plan have at least one passing test (INFRA-02 via lockfile presence; INFRA-03 via test_config; INFRA-04 via test_secrets_hygiene; INFRA-06 via test_utc_invariants; INFRA-07 via test_logging; INFRA-09 via test_killswitch; INFRA-10 via test_dry_run_logging).
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundations/01-01-SUMMARY.md` documenting:
- Files created and their responsibilities (import root established)
- Any deviations from Pattern 4 / Pattern 5 / Pattern 6 of RESEARCH.md
- Coverage numbers
- Any pydantic-settings v2.13 gotchas encountered (the field_validator API is stable but the `SettingsConfigDict` shape occasionally changes minor keys)
- Handoff note to Plan 02: `Settings`, `configure_logging`, `get_logger`, `new_cycle_id`, `is_paused` are all importable from `tech_news_synth.*`
</output>
