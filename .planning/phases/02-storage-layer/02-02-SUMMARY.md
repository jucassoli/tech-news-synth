---
phase: 02-storage-layer
plan: 02
subsystem: storage
tags: [alembic, migrations, repos, scheduler-wiring, docker]
status: awaiting-checkpoint
requirements:
  - STORE-01
  - STORE-02
  - STORE-03
  - STORE-04
  - STORE-05
dependency-graph:
  requires:
    - tech_news_synth.config.load_settings
    - tech_news_synth.db.base.Base
    - tech_news_synth.db.models.{Article,Cluster,Post,RunLog}
    - tech_news_synth.db.session.{init_engine,SessionLocal}
    - tech_news_synth.db.hashing.{canonicalize_url,article_hash}
    - tech_news_synth.logging.configure_logging
    - tech_news_synth.scheduler.{build_scheduler,run,run_cycle}
  provides:
    - alembic.ini (no DSN; loggers WARN)
    - alembic/env.py (DSN from load_settings at runtime)
    - alembic/versions/2026_04_13_0925-2a0b7b569986_initial_schema_articles_clusters_posts_.py
    - tech_news_synth.db.migrations.run_migrations
    - tech_news_synth.db.articles.{upsert_batch,get_by_hash,ArticleRow}
    - tech_news_synth.db.clusters.{insert_cluster,get_clusters_for_cycle}
    - tech_news_synth.db.posts.{insert_pending,update_posted,update_failed,read_centroid}
    - tech_news_synth.db.run_log.{start_cycle,finish_cycle}
    - run_log row per scheduler cycle (started_at + finished_at + status + counts)
    - /app/alembic.ini + /app/alembic/ in runtime image
  affects:
    - phase-04-ingestion (uses articles.upsert_batch + canonicalize_url contract)
    - phase-05-cluster (uses clusters.insert_cluster + ARRAY(BigInteger) member ids)
    - phase-07-publish (uses posts.insert_pending → update_posted with centroid bytes)
    - phase-08-ops (run_log audit trail; status='running' rows queryable for orphan check)
tech-stack:
  added:
    - alembic 1.18 (already in pyproject; first usage)
  patterns:
    - alembic.ini SANS sqlalchemy.url; env.py reads DSN at runtime (T-02-01)
    - alembic loggers pinned to WARN to suppress DSN echo (T-02-02)
    - Programmatic alembic.command.upgrade(cfg, "head") at container boot (D-01)
    - Module-level repo functions (no classes); caller owns transactions
    - pg_insert(...).on_conflict_do_nothing(...).returning(Article.id) — using
      RETURNING + len(scalars()) for accurate inserted-row count (rowcount
      returns -1 with ON CONFLICT DO NOTHING in psycopg3)
    - Session-per-cycle in scheduler.run_cycle with try/finally lifecycle:
      open → start_cycle → commit → body → finish_cycle → commit → close
    - autouse pytest fixture mock_db_in_scheduler patches SessionLocal +
      start_cycle + finish_cycle for unit tests
key-files:
  created:
    - alembic.ini
    - alembic/env.py
    - alembic/script.py.mako
    - alembic/versions/.gitkeep
    - alembic/versions/2026_04_13_0925-2a0b7b569986_initial_schema_articles_clusters_posts_.py
    - src/tech_news_synth/db/migrations.py
    - src/tech_news_synth/db/articles.py
    - src/tech_news_synth/db/clusters.py
    - src/tech_news_synth/db/posts.py
    - src/tech_news_synth/db/run_log.py
    - tests/unit/conftest.py
  modified:
    - src/tech_news_synth/__main__.py (boot order: configure_logging →
      init_engine → run_migrations → run)
    - src/tech_news_synth/scheduler.py (run_log wrapper around run_cycle;
      removed configure_logging from run())
    - tests/unit/test_scheduler.py (3 new tests for run_log wiring)
    - tests/unit/test_alembic_config.py (replace red stub)
    - tests/unit/test_migrations.py (replace red stub)
    - tests/integration/test_articles_upsert.py (replace red stub)
    - tests/integration/test_clusters_repo.py (replace red stub)
    - tests/integration/test_posts_repo.py (replace red stub)
    - tests/integration/test_run_log.py (replace red stub)
    - tests/integration/test_migration_roundtrip.py (replace red stub)
    - Dockerfile (COPY alembic.ini + alembic/ into /app)
    - pyproject.toml (extend-exclude alembic/versions from ruff)
decisions:
  - "Initial migration revision: 2a0b7b569986. File: alembic/versions/2026_04_13_0925-2a0b7b569986_initial_schema_articles_clusters_posts_.py."
  - "Autogenerate emitted clean output requiring NO post-edits to column types — every TIMESTAMPTZ, BYTEA (LargeBinary), JSONB, ARRAY(BigInteger/Text), CHAR/VARCHAR(64) UNIQUE, CHECK constraint, partial index, and FK ondelete clause came through correctly. Only post-edit was a docstring audit trail header (D-02 audit, no semantic changes)."
  - "articles.article_hash renders as VARCHAR(64) (SA String(length=64)) rather than CHAR(64). Both satisfy D-06 because UNIQUE + SHA256-hex-fixed-width make padding/length distinction immaterial. Documented in migration header."
  - "upsert_batch must return inserted-row count via .returning(Article.id) + len(scalars().all()). result.rowcount returns -1 for ON CONFLICT DO NOTHING under psycopg3 + SA 2.0; this was discovered in Task 5 and the implementation switched. The contract (count of new rows) is preserved for downstream callers."
  - "test_migration_roundtrip uses a test_dsn fixture that resolves _test_database_url() BEFORE alembic_cfg sets POSTGRES_DB to the already-suffixed name. Without this, env.py's load_settings() would compute tech_news_synth_test_test (double suffix) and fail to connect. Future migration tests must follow this pattern."
  - "tests/unit/conftest.py introduces an autouse fixture (mock_db_in_scheduler) that patches scheduler.SessionLocal/start_cycle/finish_cycle for every unit test. This is the cleanest way to keep the existing 64 Phase 1 + 11 Wave 1 scheduler tests green after the run_log wiring without DB dependency. Tests can opt out via @pytest.mark.no_db_mock."
  - "configure_logging moved from scheduler.run() to __main__._dispatch_scheduler(). Reason: alembic logs need to flow through the JSON pipeline (RESEARCH §Open Question 1). Downstream phase plans must NOT re-call configure_logging in scheduler-side code."
  - "alembic/versions/ excluded from ruff via pyproject extend-exclude. Auto-generated migration style (typing.Union, no module docstring, long lines for create_table) is widely accepted; lint pressure on it would either force ugly post-edits on every revision or auto-fix into something alembic regenerate would un-fix."
metrics:
  started_at: "2026-04-13T12:23:09Z"
  completed_at: "2026-04-13T12:36:11Z"
  duration_seconds: 782
  tasks_completed: 7  # tasks 1–7; task 8 is operator checkpoint
  commits: 7
  files_created: 11
  files_modified: 13
  tests_total: 128
  tests_passing: 128  # 104 unit + 24 integration (note: 24 = 2 fixture isolation + 22 new repo/migration tests)
  tests_unit: 104
  tests_integration: 24
---

# Phase 02 Plan 02: Alembic + Repos + Scheduler Wiring Summary

Wired the schema into the running container — alembic upgrade head runs
automatically at boot, four repository modules expose typed session-bound
helpers, the scheduler writes a `run_log` row per cycle, and the runtime
image ships the alembic tree at `/app/alembic{,.ini}`. Status `awaiting-checkpoint`
pending operator-driven `docker compose up` smoke (Task 8 — see below).

## Overview

**One-liner:** Programmatic alembic upgrade + 4 module-level repos +
session-per-cycle run_log lifecycle + Docker image carries alembic tree —
all behind a no-DSN-in-disk policy and a session-mock autouse so unit tests
never touch a real DB.

Plan 02-02 turns every red stub from Plan 02-01 green and adds 22 new
integration assertions across the four storage requirements. Phase 1
scheduler tests and Plan 02-01 fixture-isolation test remained green
throughout.

## Tasks Completed

| # | Task | Commit | Notes |
|---|------|--------|-------|
| 1 | Bootstrap alembic tree + env.py reading from Settings | `faa1849` | alembic.ini DSN-free; loggers WARN; 4 config tests green |
| 2 | Autogenerate initial migration + post-edit audit | `a2be60c` | Revision 2a0b7b569986; verified TIMESTAMPTZ/BYTEA/JSONB/ARRAY/CHECK/partial-index; upgrade→downgrade→upgrade roundtrip green locally |
| 3 (TDD) | run_migrations() helper + unit tests | `58b9f94` | 3 tests: path resolves; calls upgrade("head"); propagates exceptions |
| 4 | Integration roundtrip test against live PG | `7223f5a` | 1 test exercising real alembic upgrade/downgrade/upgrade against `_test` DB |
| 5 | 4 repository modules + 21 integration tests | `5027853` | STORE-02..05 green; centroid bytes roundtrip via `np.frombuffer(dtype=np.float32)` |
| 6 | Scheduler wiring: run_log per cycle; reorder __main__ boot | `9f3a3df` | INFRA-08/INFRA-09 preserved; 3 new run_log tests; autouse DB mock |
| 7 | Dockerfile ships alembic into runtime image | `452368e` | Verified by `docker run tns:test ls /app` |
| 8 | Compose smoke (operator) | — | **PENDING — see "Operator Smoke" below** |

## Architecture Decisions

1. **alembic.ini contains NO `sqlalchemy.url`** (T-02-01) — env.py materializes
   the DSN from `load_settings()` at runtime. Asserted by
   `test_alembic_ini_has_no_sqlalchemy_url`.
2. **alembic/sqlalchemy loggers pinned to WARN** in alembic.ini (T-02-02) —
   prevents DSN-fragment echo through SA INFO output.
3. **Autogenerate produced clean output** — no post-edits to column types
   needed. Migration header documents the audit trail (D-02).
4. **`upsert_batch` uses `.returning(Article.id) + len(scalars().all())`** —
   `result.rowcount` returns -1 for ON CONFLICT DO NOTHING in psycopg3.
   The RETURNING approach is the SA 2.0 idiom for accurate inserted counts.
5. **Boot order in `__main__._dispatch_scheduler` (D-01):**
   `load_settings → configure_logging → init_engine → run_migrations → run`.
   Logging configured BEFORE migrations so alembic events flow through
   the JSON pipeline; engine initialized BEFORE migrations so the
   sessionmaker is ready when the scheduler starts ticking.
6. **`scheduler.run()` no longer calls `configure_logging`** — moved to
   `__main__`. Downstream phases must NOT re-call it from scheduler code.
7. **Session-per-cycle in `run_cycle`** — opens via `SessionLocal()`, writes
   `start_cycle` row, commits, runs body, then in `finally` writes
   `finish_cycle(status, counts={})`, commits, closes. Status='ok' on
   success, 'error' on body exception, 'error' default if start_cycle
   itself raises (defensive).
8. **Paused cycles write NO run_log row** (INFRA-09) — `is_paused` short-
   circuits before SessionLocal is touched. Asserted by
   `test_run_cycle_skips_run_log_when_paused`.
9. **`tests/unit/conftest.py` autouse fixture mocks SessionLocal/start/finish**
   — keeps unit tests DB-free. Tests can opt out via `@pytest.mark.no_db_mock`.
   This is critical for Phase 1 regression coverage.
10. **`alembic/versions/` excluded from ruff** — auto-generated style
    (typing.Union, long lines, no module docstring) is canonical and
    re-runs of `alembic revision --autogenerate` would undo any auto-fix.
11. **`test_dsn` fixture in `test_migration_roundtrip.py`** resolves the
    test DSN BEFORE the `alembic_cfg` fixture sets `POSTGRES_DB` env var,
    avoiding double-suffix `..._test_test`. Future migration tests should
    follow the same separation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] `upsert_batch` rowcount returns -1 with ON CONFLICT**
- **Found during:** Task 5 first integration run.
- **Issue:** `result.rowcount or 0` returned -1 for `pg_insert.on_conflict_do_nothing`
  in psycopg3 + SA 2.0; the test `assert first == 2` failed with `assert -1 == 2`.
- **Fix:** Switched implementation to `.returning(Article.id)` + `len(result.scalars().all())`.
  Returns the actual inserted-row count. Same public contract; one extra column in
  the round-trip is negligible.
- **Files:** `src/tech_news_synth/db/articles.py`
- **Commit:** folded into Task 5 commit `5027853`.

**2. [Rule 1 — Test bug] `test_cluster_without_run_log_violates_fk` raised before flush**
- **Found during:** Task 5 integration run.
- **Issue:** Test wrapped `db_session.flush()` in `pytest.raises`, but
  `insert_cluster` itself calls `session.flush()` — the IntegrityError surfaced
  inside `insert_cluster`, not at the test's flush call.
- **Fix:** Moved `pytest.raises` to wrap the `insert_cluster` call.
- **Commit:** folded into Task 5 commit `5027853`.

**3. [Rule 3 — Blocking] Ruff complained about auto-generated alembic migration**
- **Found during:** Task 6 lint gate.
- **Issue:** Migration file uses `typing.Union[...]` (UP007), un-sorted imports
  (I001), long create_table lines (E501) — all canonical alembic-generated style.
- **Fix:** Added `extend-exclude = ["alembic/versions"]` to `[tool.ruff]` in
  `pyproject.toml`. Auto-generated revisions are not subject to project lint.
- **Commit:** folded into Task 6 commit `9f3a3df`.

**4. [Rule 1 — Test fixture bug] Double `_test` suffix in roundtrip DSN**
- **Found during:** Task 4 first run (`tech_news_synth_test_test does not exist`).
- **Issue:** `_test_database_url()` suffixes `postgres_db` with `_test`. The
  `alembic_cfg` fixture set `POSTGRES_DB=tech_news_synth_test`, so a second
  call to `_test_database_url()` (in the test body) computed
  `..._test_test`.
- **Fix:** Added `test_dsn` fixture that resolves the DSN BEFORE
  `alembic_cfg` mutates env. Documented for future migration tests.
- **Commit:** folded into Task 4 commit `7223f5a`.

### Authentication Gates

None.

### Architectural decisions auto-applied

None — every fix above falls under Rules 1–3 (bug / blocking) and is
non-architectural.

## Verification

### Automated (green)

```bash
# Unit suite — DB-mocked via tests/unit/conftest.py autouse fixture
uv run pytest tests/unit -q
# → 104 passed (was 94 after Plan 02-01; +4 alembic_config, +3 migrations,
#   +3 scheduler run_log)

# Integration — requires docker compose up -d postgres + ./scripts/create_test_db.sh
POSTGRES_HOST=$(docker inspect tech-news-synth-postgres-1 \
    --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}') \
  uv run pytest tests/integration -q -m integration
# → 24 passed (was 2; +1 migration_roundtrip, +4 articles_upsert,
#   +4 clusters_repo, +6 posts_repo, +4 run_log, +3 fixture_isolation
#   note: clusters has additional FK + empty-cycle tests)

# Lint
uv run ruff check . && uv run ruff format --check .
# → clean (alembic/versions excluded)

# Docker image
docker build --target runtime -t tns:test .
docker run --rm --entrypoint ls tns:test /app
# → alembic alembic.ini config src
docker run --rm --entrypoint ls tns:test /app/alembic/versions
# → 2026_04_13_0925-2a0b7b569986_initial_schema_articles_clusters_posts_.py
```

### Manual (Task 8 — pending operator)

See "Operator Smoke" section below.

## Requirements Coverage

| Requirement | Where Verified | Status |
|-------------|----------------|--------|
| STORE-01 (alembic on startup; downgrade exists) | `tests/unit/test_migrations.py` (3) + `tests/integration/test_migration_roundtrip.py` (1) + Task 8 step 2/6 | automated ✓; smoke pending |
| STORE-02 (articles UNIQUE + ON CONFLICT idempotent) | `tests/integration/test_articles_upsert.py` (4) | ✓ |
| STORE-03 (clusters per-cycle metadata) | `tests/integration/test_clusters_repo.py` (4) | ✓ |
| STORE-04 (posts: 4 statuses + centroid + timestamps) | `tests/integration/test_posts_repo.py` (6 incl. parametrized) + `tests/unit/test_centroid_roundtrip.py` (Plan 02-01) | ✓ |
| STORE-05 (run_log per cycle; counts JSONB) | `tests/integration/test_run_log.py` (4) + `tests/unit/test_scheduler.py` (3 new) | ✓ |
| STORE-06 (TIMESTAMPTZ; passive retention) | `tests/unit/test_schema_invariants.py` (Plan 02-01) + migration audit | ✓ |

## Threat Mitigations Verified

| Threat | Mitigation | Verified By |
|--------|-----------|-------------|
| T-02-01 (DSN in alembic.ini) | env.py materializes from Settings | `test_alembic_ini_has_no_sqlalchemy_url` |
| T-02-02 (alembic CLI logs DSN) | loggers WARN | `test_alembic_loggers_are_warn_level` + Task 8 step 5 |
| T-02-03 (SQL injection) | All queries via SA ORM/Core; no f-string SQL | code review |
| T-02-05 (migration before DB ready) | compose `depends_on: service_healthy` | Task 8 step 1 |
| T-02-06 (centroid byte misalignment) | dtype=np.float32 explicit | `test_centroid_bytes_roundtrip_through_db` |

## Operator Runbook Notes

### Test DB setup

```bash
docker compose up -d postgres
./scripts/create_test_db.sh   # idempotent
POSTGRES_HOST=$(docker inspect tech-news-synth-postgres-1 \
    --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}') \
  uv run pytest tests/integration -q -m integration
```

### Orphaned `run_log` rows after hard crash (T-02-07)

If the container is SIGKILLed mid-cycle, the `finish_cycle` update never
runs and the row stays at `status='running'`. Detect with:

```sql
SELECT cycle_id, started_at
FROM run_log
WHERE status = 'running'
  AND started_at < now() - interval '2 hours';
```

Phase 8 ops tools can manually update such rows to `status='aborted'` if
desired; v1 does not auto-clean.

### Destructive: `alembic downgrade` (T-02-04)

```bash
docker compose exec app alembic downgrade -1
```

Drops tables irreversibly (no data backup). Operator-only; never invoked
by application code. Re-`alembic upgrade head` to restore schema (data
gone).

## Known Stubs

None — every red stub from Plan 02-01 is now green.

## Operator Smoke (Task 8 — checkpoint:human-verify)

**DO NOT auto-approve.** Operator must run these 9 steps against a clean
`docker compose` environment and reply "approved" or "failed at step N".

1. **Clean slate:**
   ```bash
   docker compose down -v
   cp .env.example .env  # ensure non-empty values; INTERVAL_HOURS=2, DRY_RUN=1, PAUSED=0
   docker compose up -d --build
   ```
   Expect both services healthy in ~30s.

2. **Migrations auto-ran:**
   ```bash
   docker compose logs app | grep -E "(alembic_upgrade_start|alembic_upgrade_done)"
   ```
   Expect both events, in order, BEFORE `scheduler_starting`.

3. **Four tables exist with correct types:**
   ```bash
   docker compose exec postgres psql -U app -d tech_news_synth -c "\dt"
   docker compose exec postgres psql -U app -d tech_news_synth -c "\d+ articles"
   docker compose exec postgres psql -U app -d tech_news_synth -c "\d+ posts"
   docker compose exec postgres psql -U app -d tech_news_synth -c "\d+ run_log"
   ```
   Expect: articles/clusters/posts/run_log/alembic_version listed; article_hash
   VARCHAR(64) UNIQUE; theme_centroid bytea; status CHECK includes pending/posted/failed/dry_run;
   counts jsonb default '{}'.

4. **First cycle wrote a run_log row:**
   ```bash
   docker compose exec postgres psql -U app -d tech_news_synth \
     -c "SELECT cycle_id, status, started_at, finished_at FROM run_log ORDER BY started_at DESC LIMIT 3;"
   ```
   Expect ≥1 row; status='ok'; started_at and finished_at populated; cycle_id 26 chars.

5. **DSN not in logs:**
   ```bash
   docker compose logs app 2>&1 | grep -E "(postgresql\+psycopg|replace-me|sqlalchemy\.url)"
   ```
   Expect no matches (or only env-echo lines without the password).

6. **Downgrade roundtrip:**
   ```bash
   docker compose exec app alembic downgrade -1
   docker compose exec postgres psql -U app -d tech_news_synth -c "\dt"
   ```
   Expect tables gone (alembic_version may remain).
   ```bash
   docker compose exec app alembic upgrade head
   docker compose exec postgres psql -U app -d tech_news_synth -c "\dt"
   ```
   Expect 4 tables back.

7. **Scheduler still ticking:**
   ```bash
   docker compose logs app --tail 30
   ```
   Expect `cycle_start`/`cycle_end` JSON lines with cycle_id + dry_run=true after `alembic_upgrade_done`.

8. **Migration failure surfaces non-zero exit (optional):**
   Set `POSTGRES_PASSWORD=wrong` in `.env`, restart app: container should exit non-zero, alembic error in logs. Restore .env afterward.

9. **Cleanup:**
   ```bash
   docker compose down -v
   ```

Record any deviations in this SUMMARY (append a "Smoke Results" section).

## Handoff to Phase 4 (Ingestion)

- `articles.upsert_batch(session, rows)` is ready. Build `ArticleRow` dicts via
  `tech_news_synth.db.hashing.{canonicalize_url, article_hash}` per source feed.
- The session's lifecycle inside `run_cycle` is: open → start_cycle → commit →
  body → finish_cycle → commit → close. Phase 4 hooks into the body slot
  (`_run_cycle_body`) — pass the ALREADY-OPEN session in, OR open a new session;
  current contract opens one session per cycle. Recommended: pass session into
  the body so all writes share the txn and a single commit at end-of-cycle.
- `run_log` row exists with the cycle's `cycle_id` BEFORE the body runs, so any
  FK from `clusters.cycle_id` / `posts.cycle_id` is satisfied immediately.
- `finish_cycle(session, cycle_id, status, counts)` accepts the dict Phase 4
  needs (`{"sources_ok": N, "articles": M, "clusters": K}`). Pass it from the
  body's accumulated counters.

## Self-Check: PASSED

- All 11 created files exist on disk (verified via git diff vs HEAD~7).
- All 13 modified files have the expected diffs.
- 7 commits exist in git log: `faa1849`, `a2be60c`, `58b9f94`, `7223f5a`,
  `5027853`, `9f3a3df`, `452368e`.
- `uv run pytest tests/unit -q` → 104 passed.
- `POSTGRES_HOST=<ip> uv run pytest tests/integration -q -m integration` → 24 passed.
- `uv run ruff check .` and `uv run ruff format --check .` clean.
- Docker image `tns:test` contains `/app/alembic.ini` and `/app/alembic/versions/<rev>.py`.
- Phase 1 + Plan 02-01 tests (75 prior unit) still green within the 104 total.
