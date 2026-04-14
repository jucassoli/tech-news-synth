# Phase 8 Deferred Items

Out-of-scope issues discovered during plan execution, recorded per GSD
scope-boundary rule (do not fix unrelated pre-existing issues).

## Pre-existing test-isolation issue: `test_migration_roundtrip.py`

**Discovered in:** 08-02 Task 1 (post-commit full suite run).

**Symptom:** `tests/integration/test_migration_roundtrip.py::test_upgrade_downgrade_upgrade_roundtrip`
fails when the full integration suite runs with `-x` because the
session-scoped `engine` fixture in `tests/integration/conftest.py` calls
`Base.metadata.create_all(eng)` on the test DB before alembic
`upgrade head` runs. The alembic revision table collides with the
SA-created schema.

**Isolation confirmed:** test passes in isolation
(`uv run pytest tests/integration/test_migration_roundtrip.py`).
Totals with it skipped: **119 integration passed** (113 Phase 1-7 baseline + 6 new
soak_monitor tests from Plan 08-02).

**Root cause:** pre-dates Phase 8 — the `Base.metadata.create_all` vs
`alembic upgrade head` strategy was noted for future unification in
`tests/integration/conftest.py` docstring ("Plan 02-02 will swap this
to `alembic upgrade head` once the alembic tree exists").

**Not fixed because:** out of Phase 8 scope. Fix belongs in a Phase 2
follow-up or a dedicated test-infra plan.

**Workaround:** run integration suite minus migration_roundtrip with:

```
uv run pytest tests/integration -m integration --ignore=tests/integration/test_migration_roundtrip.py
```

or run migration_roundtrip alone:

```
uv run pytest tests/integration/test_migration_roundtrip.py -m integration
```
