---
phase: 01
slug: foundations
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-12
---

# Phase 01 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (+ pytest-mock, time-machine, respx when needed downstream) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (Wave 0 installs) |
| **Quick run command** | `uv run pytest tests/ -q -x --ff` |
| **Full suite command** | `uv run pytest tests/ -v --cov=tech_news_synth --cov-report=term-missing` |
| **Estimated runtime** | ~5 seconds (unit only); compose smoke adds ~60s and runs manually |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/ -q -x --ff`
- **After every plan wave:** Run full suite with coverage
- **Before `/gsd-verify-work`:** Full unit suite green + one manual `docker compose up` smoke check
- **Max feedback latency:** ~5 seconds (unit), ~60 seconds (compose smoke)

---

## Per-Task Verification Map

*Per-task IDs are owned by the planner. This strategy records the requirement → test-type mapping the planner must honor.*

| Requirement | Test Type | Automated Command | Wave 0 Dep |
|-------------|-----------|-------------------|------------|
| INFRA-01 (compose up → healthy app + postgres, volumes) | manual compose smoke | `docker compose up -d && docker compose ps` (operator verifies `healthy`) | pytest + compose files |
| INFRA-02 (base image slim-bookworm, uv-installed deps, lockfile) | static check + build | `docker build --target runtime -t tns:test . && docker run --rm tns:test python -c "import sys; assert sys.version_info[:2]==(3,12)"` | Dockerfile, pyproject, uv.lock |
| INFRA-03 (pydantic-settings fail-fast on missing/invalid keys) | unit | `uv run pytest tests/unit/test_config.py -q` | `tests/unit/test_config.py` |
| INFRA-04 (`.env.example` present, `.env` ignored, pre-commit leak hook) | unit + tree check | `uv run pytest tests/unit/test_secrets_hygiene.py -q && gitleaks detect --no-banner` | `.gitignore`, `.env.example`, `.pre-commit-config.yaml` |
| INFRA-05 (APScheduler BlockingScheduler PID 1, CronTrigger UTC, INTERVAL_HOURS validator) | unit | `uv run pytest tests/unit/test_scheduler.py -q` | `tests/unit/test_scheduler.py` |
| INFRA-06 (UTC everywhere — no TZ env, datetime.now(timezone.utc)) | unit + static grep | `uv run pytest tests/unit/test_utc_invariants.py -q` (plus ruff rule banning naive `datetime.now()`) | `tests/unit/test_utc_invariants.py` |
| INFRA-07 (structlog JSON to stdout AND volume, cycle_id on every line) | unit | `uv run pytest tests/unit/test_logging.py -q` (captures stdout + tmp file, asserts both contain `cycle_id`) | `tests/unit/test_logging.py` |
| INFRA-08 (exception in run_cycle → logged with stacktrace, scheduler keeps ticking) | unit | `uv run pytest tests/unit/test_cycle_error_isolation.py -q` (injects raising job, asserts next tick still fires) | `tests/unit/test_cycle_error_isolation.py` |
| INFRA-09 (PAUSED env OR /data/paused → cycle exits 0, zero I/O, log `paused_by`) | unit | `uv run pytest tests/unit/test_killswitch.py -q` (parametrized over env/marker/both) | `tests/unit/test_killswitch.py` |
| INFRA-10 (DRY_RUN=1 accepted by config, bound on every cycle log line) | unit | `uv run pytest tests/unit/test_dry_run_logging.py -q` | `tests/unit/test_dry_run_logging.py` |

**Cross-cutting observability:** `cycle_id` ULID generator has its own unit test (`tests/unit/test_cycle_id.py`) asserting sortability and format.

**Cross-cutting signal handling:** SIGTERM test (`tests/unit/test_signal_shutdown.py`) asserts the scheduler's `shutdown(wait=True)` is called exactly once per SIGTERM/SIGINT. The behavior of *docker stop* propagating SIGTERM is covered manually.

---

## Wave 0 Requirements

Greenfield repo — Wave 0 installs everything:

- [ ] `pyproject.toml` with `[project]`, `[build-system]`, `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, `pythonpath = ["src"]`), `[tool.ruff]`
- [ ] `uv.lock` committed
- [ ] `tests/` directory with `tests/__init__.py`, `tests/conftest.py` (shared `monkeypatch_env` + `tmp_data_dir` fixtures)
- [ ] `tests/unit/` with one empty test file per requirement listed above (red stubs that import target modules — fail until code lands)
- [ ] `.pre-commit-config.yaml` with gitleaks + ruff hooks
- [ ] `.gitignore` covering `.env`, `.venv`, `__pycache__`, `*.egg-info`, `.pytest_cache`, `.ruff_cache`
- [ ] `.dockerignore` covering `.env`, `.venv`, `.git`, `__pycache__`, `.planning`, `tests`
- [ ] `.env.example` with every required key stubbed

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `docker compose up` on clean host yields two healthy containers with volumes | INFRA-01 | Requires Docker daemon + network + persistent volumes — outside pytest scope | 1) `cp .env.example .env` and fill stub secrets. 2) `docker compose up -d`. 3) Wait 30s. 4) `docker compose ps` — both services show `Up ... (healthy)`. 5) `docker volume ls` — `*_pgdata` and `*_logs` exist. 6) `docker compose logs app` — JSON line with `event=scheduler_started`, `cycle_id=<ULID>`. 7) `docker compose down` — graceful shutdown in < 10s (SIGTERM path). |
| Graceful SIGTERM shutdown under 10s | INFRA-05 / INFRA-08 | Requires container runtime to deliver SIGTERM | `docker compose up -d && sleep 5 && time docker compose down` — `down` completes in < `stop_grace_period` (default 10s). |
| Logs volume contains JSON lines after a cycle | INFRA-07 | Requires real volume mount | After `docker compose up -d` + one cycle: `docker compose exec app tail -n 5 /data/logs/app.jsonl` — each line parseable JSON with `cycle_id`. |
| Live toggle via `/data/paused` marker without restart | INFRA-09 | Requires running container | `docker compose exec app touch /data/paused` before next tick; observe next cycle logs `status=paused paused_by=marker` and performs zero I/O. Remove marker; next cycle runs normally. |
| Secret-leak pre-commit hook blocks `.env` commit | INFRA-04 | Requires git hook execution | `echo "X_API_KEY=sk-live-abc" >> .env_sample_test && git add .env_sample_test && git commit -m test` — commit rejected by gitleaks. Cleanup: `git reset HEAD && rm .env_sample_test`. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (Greenfield → everything Wave 0)
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
