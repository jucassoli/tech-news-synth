---
phase: 02-storage-layer
plan: 01
subsystem: storage
tags: [storage, sqlalchemy, postgres, schema, hashing, fixtures]
status: complete
requirements:
  - STORE-02
  - STORE-04
  - STORE-06
dependency-graph:
  requires:
    - tech_news_synth.config.Settings
    - tech_news_synth.config.Settings.database_url
    - tech_news_synth.logging.get_logger
  provides:
    - tech_news_synth.db.base.Base (DeclarativeBase — target_metadata for alembic)
    - tech_news_synth.db.hashing.canonicalize_url
    - tech_news_synth.db.hashing.article_hash
    - tech_news_synth.db.session.init_engine
    - tech_news_synth.db.session.SessionLocal
    - tech_news_synth.db.session.get_session
    - tech_news_synth.db.session._reset_engine_for_tests
    - tech_news_synth.db.models.Article
    - tech_news_synth.db.models.Cluster
    - tech_news_synth.db.models.Post
    - tech_news_synth.db.models.RunLog
    - tests/integration/conftest.py (engine, connection, db_session, clean_db)
    - scripts/create_test_db.sh
  affects:
    - plan-02-02 (alembic autogenerate will consume Base.metadata; run_migrations()
      will import from db.base + db.models; repos will import from db.session)
    - phase-04-ingestion (article_hash + canonicalize_url contract for upsert key)
    - phase-05-cluster (Post.theme_centroid BYTEA — numpy float32 roundtrip ready)
tech-stack:
  added:
    - numpy 2.4.4 (pinned >=2,<3)
  patterns:
    - SA 2.0 typed Mapped[...] + mapped_column with explicit Postgres types
    - DateTime(timezone=True) uniformly → Postgres TIMESTAMPTZ
    - sa.CheckConstraint (not pg ENUM) for posts.status
    - sqlalchemy.dialects.postgresql.{ARRAY, JSONB} for array/JSON columns
    - LargeBinary for BYTEA (theme_centroid, numpy float32 tobytes)
    - Module-level engine singleton + idempotent init_engine
    - Integration conftest auto-markers (@pytest.mark.integration) via
      pytest_collection_modifyitems
    - Transactional-rollback fixture with nested SAVEPOINT + after_transaction_end
      listener (RESEARCH §Pattern 8)
    - Test-DB safety guard (refuses any DB name not ending in _test)
key-files:
  created:
    - src/tech_news_synth/db/__init__.py
    - src/tech_news_synth/db/base.py
    - src/tech_news_synth/db/hashing.py
    - src/tech_news_synth/db/session.py
    - src/tech_news_synth/db/models.py
    - scripts/create_test_db.sh
    - tests/integration/__init__.py
    - tests/integration/conftest.py
    - tests/integration/test_fixture_isolation.py
    - tests/integration/test_articles_upsert.py (red stub)
    - tests/integration/test_clusters_repo.py (red stub)
    - tests/integration/test_posts_repo.py (red stub)
    - tests/integration/test_run_log.py (red stub)
    - tests/integration/test_migration_roundtrip.py (red stub)
    - tests/unit/test_db_hashing.py
    - tests/unit/test_db_session.py
    - tests/unit/test_schema_invariants.py
    - tests/unit/test_centroid_roundtrip.py
    - tests/unit/test_migrations.py (red stub)
    - tests/unit/test_alembic_config.py (red stub)
  modified:
    - pyproject.toml (numpy dep, integration marker)
    - uv.lock (regenerated)
    - .env.example (TEST_DATABASE_URL note appended)
decisions:
  - Kept default ports (:80/:443) as-is in canonicalize_url rather than stripping.
    urlsplit preserves whatever the input contains; documented in a test so future
    Phase 4 is aware. Rationale: under-specified rule in D-06 — preserving is the
    safer choice (less surprise for feeds that always include :443).
  - canonicalize_url preserves trailing slash and path case exactly — "different
    paths are different resources" (per RESEARCH §Pattern 7 note).
  - Test-DB connection for local dev currently requires reaching the compose
    postgres container directly (IP or published port). Our compose has no
    ports mapping on postgres (T-02-09). Operators run integration tests via
    either (a) container IP (docker inspect), (b) a local compose override
    publishing 5432, or (c) docker compose exec from inside the bridge net.
    Documented in the conftest docstring. Not a fixture bug — a deliberate
    security posture.
metrics:
  started_at: "2026-04-12T20:45:29Z"
  completed_at: "2026-04-13T12:30:00Z"
  duration_seconds: 1300
  tasks_completed: 5
  commits: 6
  files_created: 20
  files_modified: 3
  tests_total: 103
  tests_passing: 96
  tests_skipped: 7
  tests_integration_passing: 2
---

# Phase 02 Plan 01: Storage Foundation Summary

Established every surface Plan 02-02 and Phase 4+ will write through — the
`tech_news_synth.db` package (models + session + URL hashing), the
transactional-rollback integration fixture, the test-DB bootstrap script, and
the full red-stub tree for Plan 02-02 to fill.

## Overview

**One-liner:** SA 2.0 typed models for articles/clusters/posts/run_log, a pure
canonicalize_url + SHA256 article_hash helper, an idempotent engine singleton
that never logs the DSN, and a nested-SAVEPOINT `db_session` fixture proven
by a two-step meta-test against a live postgres.

Plan 02-01 delivers models + helpers + fixtures only. It **does not** create
alembic files, migration helpers, or repositories — those are Plan 02-02.
Phase 1 tests remained green throughout (64 pre-existing + 30 new unit tests
= 94 unit tests, plus 2 integration tests passing).

## Tasks Completed

| # | Task | Commit | Notes |
|---|------|--------|-------|
| 1 | Scaffold numpy dep + test-db helper + package skeleton | `6df99ff` | numpy>=2,<3, pytest `integration` marker, scripts/create_test_db.sh, empty db/ + tests/integration/ __init__.py |
| 2 (RED) | Failing tests for URL canonicalization + article_hash | `68a97c7` | 16 parametrized + edge-case tests for D-06 |
| 2 (GREEN) | canonicalize_url + article_hash implementation | `358e82a` | Pure stdlib (urlsplit/parse_qsl/urlencode) + hashlib.sha256 |
| 3 | SA 2.0 Base + idempotent init_engine/SessionLocal | `8af3bb1` | DSN never logged (T-02-01-A); 4 behavior tests |
| 4 | ORM models (Article, Cluster, Post, RunLog) + schema invariants | `8044061` | 6 introspection tests + 3 float32 roundtrip tests |
| 5 | Integration conftest + transactional-rollback fixture + red stubs | `635ee9f` | Nested SAVEPOINT isolation proven by 2-step meta-test against live postgres |

## Architecture Decisions

1. **Single `Base` in `db/base.py`** — simpler than splitting metadata per module;
   Alembic's `target_metadata = Base.metadata` gets one authoritative source.
2. **Module-level engine singleton with idempotent `init_engine`** — callers
   (Plan 02-02's `run_migrations()` + scheduler + integration tests) can call it
   multiple times without worry. The first call wins.
3. **`pool_pre_ping=True`, `pool_size=5`, `future=True`** — pre-ping makes us
   resilient to postgres restarts (D-03 leaves recovery to cycle-level retries);
   size 5 is plenty for a single-worker agent.
4. **DSN NEVER logged** — `init_engine` emits `db_engine_initialized` with only
   `pool_size`. Unit test captures structlog output and asserts the password +
   `postgresql+psycopg://` substring are both absent (T-02-01-A).
5. **`ON CONFLICT DO NOTHING` lives in Plan 02-02 upsert helpers**, not in the
   schema. Plan 02-01 just defines `article_hash UNIQUE`; the conflict target
   is the unique index.
6. **`sa.CheckConstraint` (not pg ENUM) for `posts.status`** — easier to evolve
   via migration (CONTEXT discretion). The constraint text names all four
   statuses literally.
7. **`server_default="{}"` for JSONB and ARRAY columns** — works in SA 2.0
   DDL emission at model level. Plan 02-02 may need to re-express as
   `sa.text("'{}'::jsonb")` in the autogenerated migration (see
   RESEARCH §Pitfall 3); model-level defaults remain as-is.
8. **Integration conftest auto-applies `@pytest.mark.integration`** via
   `pytest_collection_modifyitems` hook — authors of new integration tests
   don't have to remember the decorator.
9. **Test-DB safety guard** — `_assert_safe_test_db` refuses to call
   `create_all`/`drop_all` unless the DB name ends in `_test`. Mitigates
   T-02-03-A (accidentally hitting production) and T-02-08 (DoS via wrong
   target).
10. **Nested SAVEPOINT + `after_transaction_end` listener** — the canonical
    SA 2.0 pattern for "join an external transaction". SUT-level
    `session.commit()` becomes a SAVEPOINT release (no outer effect); the
    outer connection rollback wipes the slate when the test ends. Proven by
    two-step meta-test (step 1 writes + commits, step 2 asserts row gone).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] Ruff autofix pass after Task 5**
- **Found during:** Task 5 verify (final lint gate).
- **Issue:** Ruff flagged one unused `# noqa: ARG001` (ARG tests don't actually
  use the fixture, but the fixture is named for clarity) and 5 files needed
  line-length reflows.
- **Fix:** `uv run ruff check --fix .` + `uv run ruff format .` — 7 auto-fixes
  across 5 files. No semantic changes; all tests still green.
- **Commit:** folded into Task 5 commit `635ee9f`.

### Authentication Gates

None.

### Default-port handling (documented under "decisions")

CONTEXT D-06 was silent on whether `:443`/`:80` should be stripped. Chose to
**preserve** whatever `urlsplit` produces — simpler, less surprising, and the
test `test_canonicalize_url_preserves_default_port_as_is` documents the
behavior so Phase 4 isn't caught off-guard.

## Verification

### Automated (green)

```bash
# Unit suite — no DB required
uv run pytest tests/ -q -m "not integration"
# → 94 passed, 7 skipped (Plan 02-02 red stubs), 2 deselected

# Integration — required docker compose up -d postgres + ./scripts/create_test_db.sh
POSTGRES_HOST=<container-ip> uv run pytest tests/integration/test_fixture_isolation.py -q -x -m integration
# → 2 passed (both isolation steps green — SAVEPOINT rollback proven)

# Lint
uv run ruff check . && uv run ruff format --check .
# → clean
```

### Red stubs (collected + skipped)

```bash
uv run pytest tests/integration -q --co
# 2 collected (isolation) — rest are module-level skipped
```

Skipped for Plan 02-02:
- `tests/integration/test_articles_upsert.py`
- `tests/integration/test_clusters_repo.py`
- `tests/integration/test_posts_repo.py`
- `tests/integration/test_run_log.py`
- `tests/integration/test_migration_roundtrip.py`
- `tests/unit/test_migrations.py`
- `tests/unit/test_alembic_config.py`

## Requirements Coverage

| Requirement | Where Verified | Status |
|-------------|----------------|--------|
| STORE-02 (partial — schema only; upsert helper + integration test in Plan 02-02) | `test_schema_invariants.py::test_article_hash_is_char64_unique` + `test_db_hashing.py` (full canonicalization + SHA256 suite) | models + hashing ✓; upsert pending Plan 02-02 |
| STORE-04 (partial — schema + centroid roundtrip; repo helpers in Plan 02-02) | `test_schema_invariants.py::test_posts_status_check_covers_all_four_statuses`, `test_posts_theme_centroid_is_largebinary_nullable`, `test_centroid_roundtrip.py` | schema + centroid ✓; repo pending |
| STORE-06 (all datetimes TIMESTAMPTZ — passive retention per D-08) | `test_schema_invariants.py::test_every_datetime_is_timestamptz` iterates every column of every table | ✓ |
| STORE-01, STORE-03, STORE-05 | N/A this plan — alembic + repos belong to Plan 02-02 | deferred |

## Known Stubs

| File | Reason |
|------|--------|
| tests/integration/test_articles_upsert.py | Plan 02-02 implements STORE-02 upsert tests |
| tests/integration/test_clusters_repo.py | Plan 02-02 implements STORE-03 repo tests |
| tests/integration/test_posts_repo.py | Plan 02-02 implements STORE-04 repo tests |
| tests/integration/test_run_log.py | Plan 02-02 implements STORE-05 run_log lifecycle |
| tests/integration/test_migration_roundtrip.py | Plan 02-02 implements STORE-01 alembic roundtrip |
| tests/unit/test_migrations.py | Plan 02-02 implements run_migrations() + mock test |
| tests/unit/test_alembic_config.py | Plan 02-02 creates alembic.ini + asserts no sqlalchemy.url leak |

All stubs use `pytest.skip("implemented in Plan 02-02", allow_module_level=True)`
so they are collected (surfacing in `pytest --co`) but do not fail.

## Test DB Setup Runbook

Operator / CI steps to enable integration tests:

```bash
# 1. Start compose postgres (no host port — internal bridge only)
docker compose up -d postgres

# 2. Create <db>_test once (idempotent; safe to re-run)
./scripts/create_test_db.sh

# 3. Run integration tests. The compose postgres is NOT published to localhost
#    (T-02-09). Three options to reach it from the host:
#
#    a) container IP (ad-hoc dev):
#         export PG_IP=$(docker inspect tech-news-synth-postgres-1 \
#             --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
#         POSTGRES_HOST=$PG_IP uv run pytest tests/integration -q -m integration
#
#    b) local compose override (dev only — commit .override to .gitignore):
#         # compose.override.yaml
#         services:
#           postgres:
#             ports: ["5432:5432"]
#         uv run pytest tests/integration -q -m integration
#
#    c) run pytest from inside a dev container attached to the bridge net
#       (CI pattern — out of scope for v1).
#
# 4. Alternative: set TEST_DATABASE_URL directly to any <db>_test DSN:
#       export TEST_DATABASE_URL=postgresql+psycopg://app:pw@host:5432/any_test
```

The conftest refuses to touch any DB whose name does not end in `_test`
(T-02-03-A mitigation).

## Handoff to Plan 02-02

Integration points waiting for Plan 02-02:

1. **Alembic tree creation** — Plan 02-02 creates `alembic.ini`, `alembic/env.py`,
   and `alembic/versions/<rev>_initial_schema.py`. `env.py` imports
   `tech_news_synth.db.base.Base` + `tech_news_synth.db.models` (noqa:F401) and
   sets `target_metadata = Base.metadata`. `alembic revision --autogenerate` will
   find all four tables.
2. **`src/tech_news_synth/db/migrations.py::run_migrations()`** — programmatic
   `alembic.command.upgrade(cfg, "head")`. Called from
   `tech_news_synth.__main__._dispatch_scheduler()` after `configure_logging()`
   and before `build_scheduler()` (D-01).
3. **Engine init order** — Plan 02-02 should call `init_engine(settings)` after
   `run_migrations()` succeeds. The engine singleton is ready; just wire the call.
4. **Repository modules** — Plan 02-02 creates `db/articles.py`,
   `db/clusters.py`, `db/posts.py`, `db/run_log.py` as pure-function modules.
   `articles.upsert_batch(session, rows)` uses
   `from sqlalchemy.dialects.postgresql import insert as pg_insert` +
   `.on_conflict_do_nothing(index_elements=["article_hash"])`.
5. **Integration conftest swap** — Plan 02-02 may change the `engine` fixture
   from `Base.metadata.create_all(eng)` to `alembic upgrade head` so the
   migration roundtrip test exercises the real path. The red-stub
   `test_migration_roundtrip.py` is the target.
6. **scheduler `run_cycle` wiring** — Plan 02-02 inserts a RunLog row at cycle
   start and updates it at finish (see RESEARCH §Pattern 6).
7. **Dockerfile** — Plan 02-02 must ensure `alembic/` and `alembic.ini` are
   `COPY`-ed into `/app` in the runtime stage. Current Dockerfile copies
   `src/` but those new paths are additive.
8. **alembic.ini must NOT contain `sqlalchemy.url`** — DSN comes from
   `env.py` via `load_settings()`. `test_alembic_config.py` (red stub here)
   enforces this.

## Self-Check: PASSED

- All 20 created files exist on disk (verified via git commit diffs).
- All 3 modified files present with expected changes.
- 6 commits verified: `6df99ff`, `68a97c7`, `358e82a`, `8af3bb1`, `8044061`, `635ee9f`.
- `uv run pytest tests/ -q -m "not integration"` → 94 passed, 7 skipped, 2 deselected.
- `POSTGRES_HOST=<ip> uv run pytest tests/integration/test_fixture_isolation.py -q -x -m integration` → 2 passed.
- `uv run ruff check .` and `uv run ruff format --check .` clean.
- No Phase 1 regressions: original 64 tests still green.
- No DSN or password appears in any log output (structlog capture test).
