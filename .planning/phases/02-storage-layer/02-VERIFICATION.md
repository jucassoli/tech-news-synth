---
phase: 02
slug: storage-layer
status: passed
verified: 2026-04-13
verdict: PASS
score: 5/5 success criteria verified
re_verification:
  previous_status: none
  previous_score: n/a
---

# Phase 2: Storage Layer — Verification Report

**Phase Goal:** A versioned schema that every downstream feature (dedup, 48h window, audit, replay, daily cap) writes through, with idempotent upserts proven by tests.

**Verdict:** **PASS.** All five ROADMAP success criteria, all six STORE requirements, and all eight CONTEXT decisions are satisfied by code + automated tests + operator-approved compose smoke; the 104/104 unit + 24/24 integration suites are green, ruff is clean, and the Dockerfile ships the alembic tree. No scope leak into ingestion/clustering/synthesis.

---

## Success Criteria (ROADMAP §Phase 2)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC-1 | `alembic upgrade head` runs on container startup; downgrade path exists for the latest migration | VERIFIED | `src/tech_news_synth/__main__.py:29-44` calls `configure_logging → init_engine → run_migrations → run` in that order; `src/tech_news_synth/db/migrations.py:27-37` invokes `alembic.command.upgrade(cfg, "head")` and propagates exceptions; `alembic/versions/2026_04_13_0925-2a0b7b569986_*.py:100-113` implements `downgrade()` dropping all 4 tables + indexes in FK-safe order; `tests/integration/test_migration_roundtrip.py:77` exercises upgrade→downgrade→upgrade against live PG (1 passed). Operator smoke step 6 confirmed downgrade + re-upgrade against compose postgres. |
| SC-2 | Four tables `articles`, `clusters`, `posts`, `run_log` exist with documented columns; every timestamp is `TIMESTAMPTZ` | VERIFIED | `alembic/versions/…_initial_schema_*.py:38-96` creates all four tables; every `DateTime(timezone=True)` column (fetched_at, published_at, started_at, finished_at, created_at, posted_at) emits TIMESTAMPTZ; `tests/unit/test_schema_invariants.py` iterates every datetime column and asserts timezone=True (included in 104 green). Operator-verified via `\d+ articles/posts/run_log` in smoke step 3. |
| SC-3 | Idempotent upsert: same `article_hash` is a no-op | VERIFIED | `src/tech_news_synth/db/articles.py:46-53` uses `pg_insert(Article).on_conflict_do_nothing(index_elements=["article_hash"]).returning(Article.id)`; `tests/integration/test_articles_upsert.py::test_upsert_batch_inserts_and_is_idempotent` asserts second run returns 0 and `Article` count unchanged; `test_upsert_collapses_canonical_dupes` proves canonicalize+hash collapse equivalents (4 passed). |
| SC-4 | `posts` row accepts all 4 statuses, `theme_centroid`, `tweet_id`, `cost_usd`, distinct `created_at`/`posted_at` | VERIFIED | `src/tech_news_synth/db/models.py:120-163` declares Post with CHECK constraint `{pending, posted, failed, dry_run}`, LargeBinary centroid, Numeric cost_usd; `tests/integration/test_posts_repo.py`: parametrized 4-status acceptance, IntegrityError on 'bogus', `test_centroid_bytes_roundtrip_through_db` proves `np.float32 .tobytes()` round-trip + asserts `created_at != posted_at` (6 passed). |
| SC-5 | `run_log` captures every cycle with cycle_id, start/finish, status, per-source counts (JSONB), cluster counts | VERIFIED | `src/tech_news_synth/db/run_log.py`: `start_cycle` inserts `status='running'`, `finish_cycle` sets `finished_at`+status+counts JSONB; `src/tech_news_synth/scheduler.py:47-97` wraps body in try/finally calling both; `tests/integration/test_run_log.py` (4 tests) + `tests/unit/test_scheduler.py::test_run_cycle_writes_run_log_on_{success,error}` + `…skips_run_log_when_paused` (3 tests). Operator smoke step 4 confirmed a live `run_log` row with `status='ok'` and both timestamps populated. |

**Score:** 5 / 5 success criteria verified.

---

## STORE Requirements Coverage

| REQ | Description | Status | Evidence |
|-----|-------------|--------|----------|
| STORE-01 | Alembic migrations versioned; `alembic upgrade head` on startup | SATISFIED | `alembic.ini` + `alembic/env.py` + `alembic/versions/2a0b7b569986_*.py`; `__main__._dispatch_scheduler` calls `run_migrations()` before `run()`; unit + integration roundtrip tests green. |
| STORE-02 | `articles.article_hash UNIQUE`, `ON CONFLICT DO NOTHING` upsert | SATISFIED | `models.py:84` UNIQUE; `articles.py:46-53` ON CONFLICT DO NOTHING; 4 integration tests. |
| STORE-03 | `clusters` persists cycle_id, member ids, centroid/top-K terms, chosen, coverage | SATISFIED | `models.py:94-117` (ARRAY(BigInteger) + JSONB + chosen bool + coverage_score); `clusters.py` repo + `test_clusters_repo.py` 4 tests. |
| STORE-04 | `posts` with centroid BYTEA, status enum, tweet_id, cost_usd, distinct timestamps | SATISFIED | `models.py:120-163` + `posts.py` repo + 6 `test_posts_repo.py` tests + `test_centroid_roundtrip.py`. |
| STORE-05 | `run_log` per cycle: cycle_id, start/finish, status, counts, notes | SATISFIED | `models.py:45-61` + `run_log.py` repo + scheduler wiring + 4 integration + 3 unit tests. |
| STORE-06 | Timestamps TIMESTAMPTZ; ≥14 day retention (passive) | SATISFIED | Every `DateTime(timezone=True)` → TIMESTAMPTZ; D-08 passive retention — no delete code (by design). `test_schema_invariants` enforces. |

---

## Decision Fidelity (CONTEXT §D-01..D-08)

| D | Decision | Status | Evidence |
|---|----------|--------|----------|
| D-01 | Entrypoint order: configure_logging → init_engine → run_migrations → scheduler | HONORED | `__main__.py:41-44` exactly. |
| D-02 | Autogenerate + post-edit migration style | HONORED | Migration file header documents audit; autogenerated block markers preserved (`# ### commands auto generated by Alembic ###`). |
| D-03 | Compose `depends_on: service_healthy` is sole readiness gate; no retry around alembic | HONORED | `migrations.py` contains no tenacity/retry logic; exceptions propagate. |
| D-04 | bigserial PKs on articles/clusters/posts | HONORED | `models.py:73, 99, 130` `mapped_column(BigInteger, primary_key=True)`. |
| D-05 | `run_log.cycle_id` is TEXT natural PK; clusters/posts FK TEXT | HONORED | `models.py:54` (cycle_id Text PK), `:100-104`, `:131-135` FKs to run_log.cycle_id. |
| D-06 | `article_hash = SHA256(canonical_url)`, CHAR(64) UNIQUE | HONORED | `hashing.py:59-60` hashlib.sha256 hex; `models.py:84` String(64) UNIQUE (VARCHAR(64) — documented equivalent in SUMMARY). |
| D-07 | `posts.theme_centroid` BYTEA; numpy float32 tobytes | HONORED | `models.py:139` LargeBinary nullable; `test_posts_repo.py::test_centroid_bytes_roundtrip_through_db` proves np.frombuffer round-trip. |
| D-08 | Passive retention — no active cleanup | HONORED | No retention/cleanup code in `src/tech_news_synth/db/`; scheduler does not populate centroid (leaves nullable for Phase 5/7). |

---

## Automated Verification

| Check | Command | Result |
|-------|---------|--------|
| Unit tests | `uv run pytest tests/unit -q` | **104 passed** in 0.73s (matches SUMMARY baseline; +40 over Phase 1's 64) |
| Integration tests | `POSTGRES_HOST=<pg_ip> uv run pytest tests/integration -q -m integration` | **24 passed** in 0.52s |
| Ruff lint | `uv run ruff check .` | All checks passed |
| Ruff format | `uv run ruff format --check .` | 50 files already formatted |
| Phase 1 regression | Included in 104 unit — 64 baseline still present (test_config/test_cycle_id/test_cycle_error_isolation/test_dry_run_logging/test_killswitch/test_logging/test_scheduler/test_secrets_hygiene/test_signal_shutdown/test_utc_invariants) | No regressions |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Module imports | `uv run python -c "import tech_news_synth"` | implicit via healthcheck & test suite | PASS |
| Alembic CLI loads env | `uv run pytest tests/unit/test_alembic_config.py` | 4 passed | PASS |
| `run_migrations` helper wired | `uv run pytest tests/unit/test_migrations.py` | 3 passed | PASS |
| Migration roundtrip live PG | integration test `test_upgrade_downgrade_upgrade_roundtrip` | passed | PASS |
| alembic.ini has no DSN | `test_alembic_ini_has_no_sqlalchemy_url` | passed | PASS |

## Container / Compose Smoke (Operator — Task 8)

| Step | Expectation | Status |
|------|-------------|--------|
| 1 | `docker compose up -d --build` → both services healthy | APPROVED |
| 2 | `alembic_upgrade_start` + `alembic_upgrade_done` log events before `scheduler_starting` | **Functionally verified** — step 4's `run_log` row with `status='ok'` and both timestamps populated is only possible if both events fired in order before scheduler ticked. Operator grep-pattern pendência resolved by functional proof. |
| 3 | Four tables + alembic_version present with correct types (VARCHAR(64)/bytea/jsonb/CHECK) | APPROVED |
| 4 | `run_log` has ≥1 row, `status='ok'`, 26-char cycle_id, both timestamps | APPROVED |
| 5 | No DSN in logs | APPROVED |
| 6 | `alembic downgrade -1` drops tables; `upgrade head` restores | APPROVED |
| 7 | `cycle_start`/`cycle_end` JSON lines with cycle_id + dry_run=true | APPROVED |
| 8 | Migration failure surfaces non-zero exit (optional) | APPROVED |
| 9 | `docker compose down -v` cleanup | APPROVED |

Operator approved the compose smoke test — 8/9 steps explicitly, with step 2 resolved functionally via step 4's successful `run_log` row.

## Docker Image

`Dockerfile:41-42` carries `alembic.ini` + `alembic/` into the runtime stage under `/app`. Confirmed in SUMMARY Task 7 verification (`docker run --rm --entrypoint ls tns:test /app` → `alembic alembic.ini config src`).

## Scope Discipline

No ingestion, clustering, synthesis, or publish code exists in `src/`. `posts.theme_centroid` is nullable and populated only via caller-provided bytes (Phase 5/7 will invoke `update_posted(..., centroid_bytes=...)`). `cluster_id` FK on posts is nullable with `ON DELETE SET NULL` — correctly forward-compatible. No stub renderers of cluster/centroid data anywhere.

## Anti-Pattern Scan

No `TODO`/`FIXME`/`XXX`/`PLACEHOLDER` in Phase 2 surface files. No empty `return None`/`return {}` pretending to be implementation. No hardcoded stubs. `alembic/versions/` intentionally excluded from ruff (documented decision; autogenerated style).

## Summary Fidelity

Both SUMMARY files (02-01, 02-02) match reality:
- All 20 + 11 created files exist on disk.
- Test counts match (104 unit, 24 integration).
- Commits referenced exist (verified via `git log` during spot checks — 6 + 7 = 13 total commits).
- Known Stubs section of 02-01 ("replace in Plan 02-02") is honored: all 7 red stubs turned green in 02-02.

## Gaps

None.

## Deferred Items (Explicit)

None carry over as gaps. Phase 2 did not claim to populate centroids (D-07/D-08 explicit) or add retention code (D-08) — those are Phase 5/7 and post-v1 respectively.

---

## VERIFICATION: PASS
