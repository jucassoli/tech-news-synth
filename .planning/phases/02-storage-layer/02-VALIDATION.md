---
phase: 02
slug: storage-layer
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-13
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (inherits from Phase 1; adds `markers = ["integration: requires live postgres"]`) |
| **Quick run command** | `uv run pytest tests/unit -q -x --ff` |
| **Integration run command** | `uv run pytest tests/integration -q -x` (requires `docker compose up -d postgres`) |
| **Full suite command** | `uv run pytest tests/ -v --cov=tech_news_synth --cov-report=term-missing` |
| **Estimated runtime** | ~2s unit, ~15s integration (compose postgres startup excluded) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit -q -x --ff` (unit only — fast)
- **After Wave 2 (migrations wired):** First integration run against live postgres required
- **After every wave:** Full suite with coverage
- **Before `/gsd-verify-work`:** Full suite green + `alembic upgrade head` from clean DB succeeds + `alembic downgrade -1 && alembic upgrade head` round-trip succeeds
- **Max feedback latency:** ~2s unit, ~15s integration

---

## Per-Requirement Verification Map

| Requirement | Test Type | Automated Command | Wave 0 Dep |
|-------------|-----------|-------------------|------------|
| STORE-01 (alembic upgrade head on container startup; downgrade path exists) | unit + integration | `pytest tests/unit/test_migrations.py -q` (mocks `alembic.command.upgrade`) + `pytest tests/integration/test_migration_roundtrip.py -q` (real DB upgrade → downgrade → upgrade) | `tests/unit/test_migrations.py`, `tests/integration/test_migration_roundtrip.py` |
| STORE-02 (articles UNIQUE + ON CONFLICT DO NOTHING; rerun same batch = no row count change) | integration | `pytest tests/integration/test_articles_upsert.py -q` | `tests/integration/test_articles_upsert.py` |
| STORE-03 (clusters metadata persisted per cycle) | integration | `pytest tests/integration/test_clusters_repo.py -q` | `tests/integration/test_clusters_repo.py` |
| STORE-04 (posts: status ∈ {pending,posted,failed,dry_run}; theme_centroid BYTEA roundtrip; tweet_id, cost_usd, created_at ≠ posted_at) | integration + unit | `pytest tests/integration/test_posts_repo.py tests/unit/test_centroid_roundtrip.py -q` | `tests/integration/test_posts_repo.py`, `tests/unit/test_centroid_roundtrip.py` |
| STORE-05 (run_log writes at cycle start + finish; cycle_id PK; counts JSONB) | integration | `pytest tests/integration/test_run_log.py -q` (plus a scheduler-integration test asserting the `run_cycle` wrapper writes run_log rows) | `tests/integration/test_run_log.py`, update `tests/unit/test_scheduler.py` |
| STORE-06 (all timestamps TIMESTAMPTZ; retention = passive floor) | unit (schema introspection) | `pytest tests/unit/test_schema_invariants.py -q` (inspects `Base.metadata` for TIMESTAMPTZ on every datetime column) | `tests/unit/test_schema_invariants.py` |

**Cross-cutting — URL canonicalization (D-06):** dedicated unit tests `tests/unit/test_url_canonicalize.py` covering: lowercase scheme+host, drop fragment, strip `utm_*`/`gclid`/`fbclid`, sort remaining query params alphabetically, trailing slash preservation, default-port handling, punycode/IDN passthrough. SHA256 hash stability test asserts the hex digest is deterministic across Python versions.

**Cross-cutting — secrets hygiene:** `tests/unit/test_alembic_config.py` asserts `alembic.ini` does NOT contain a `sqlalchemy.url =` line with a real DSN (must be `sqlalchemy.url =` empty or absent; DSN comes from `env.py` via Settings).

**Cross-cutting — session isolation:** `conftest.py` `db_session` fixture uses nested SAVEPOINT + `after_transaction_end` listener so SUT `session.commit()` calls stay rolled back on teardown. Proven by a meta-test `tests/integration/test_fixture_isolation.py` that writes a row, commits, and asserts the row is gone in the next test.

---

## Wave 0 Requirements

- [ ] `numpy>=2,<3` added to `pyproject.toml` deps + `uv sync` + `uv.lock` regenerated
- [ ] `tests/integration/__init__.py` created; `tests/integration/conftest.py` with `engine`, `connection`, `db_session`, `clean_db` fixtures
- [ ] `scripts/create_test_db.sh` (one-shot: `psql -U app -d postgres -c "CREATE DATABASE tech_news_synth_test;"`) — documented in DEPLOY/developer setup
- [ ] `.env.example` gains `TEST_DATABASE_URL` (optional override; defaults to `<DATABASE_URL>_test`)
- [ ] `pyproject.toml` adds `[tool.pytest.ini_options] markers = ["integration: requires live postgres"]` so `pytest -m "not integration"` filters cleanly in CI-lite scenarios
- [ ] Empty red-stub test files for each test module listed in the map above (fail until code lands)
- [ ] `alembic.ini` + `alembic/env.py` + `alembic/versions/` directory tree
- [ ] `src/tech_news_synth/db/__init__.py` package marker

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `alembic upgrade head` on fresh postgres creates the four tables with correct columns/constraints | STORE-01, 02, 03, 04, 05, 06 | Requires clean postgres volume | `docker compose down -v && docker compose up -d` — wait healthy — `docker compose exec postgres psql -U app -d tech_news_synth -c "\dt"` lists `articles`, `clusters`, `posts`, `run_log`, `alembic_version`. `\d+ articles` shows `article_hash CHAR(64) UNIQUE` and `TIMESTAMPTZ` columns. |
| `alembic downgrade -1` cleanly reverses the initial migration | STORE-01 | Requires live DB | `docker compose exec app alembic downgrade -1 && docker compose exec app alembic current` — shows empty history; re-upgrade with `alembic upgrade head` succeeds. |
| Connection-string password does not appear in container logs | Threat: T-02-cfg-leak | Requires real logs inspection | `docker compose logs app 2>&1 \| grep -i "$POSTGRES_PASSWORD"` must return nothing; `grep 'sqlalchemy.url'` must return nothing. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s (unit), < 30s (integration per test file)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
