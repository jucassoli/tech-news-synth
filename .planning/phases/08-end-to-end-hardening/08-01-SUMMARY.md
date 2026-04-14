---
phase: 08
plan: 01
subsystem: observability + operator-clis
tags: [observability, cli, scheduler, synth, ops]
dependency_graph:
  requires: [07-02]
  provides: [08-02]
  affects: [scheduler, synth/orchestrator, cli/*, db/source_state]
tech_stack:
  added: []
  patterns:
    - keyword-only flags for dangerous-on-default behaviour (persist=False)
    - post-commit log emit (durability invariant)
    - in-process CLI invocation sharing the same run_cycle code path
    - stdlib f-string table rendering (no prettytable dep)
key_files:
  created:
    - src/tech_news_synth/cli/source_health.py
    - src/tech_news_synth/cli/replay.py
    - src/tech_news_synth/cli/post_now.py
    - tests/unit/test_cycle_summary.py
    - tests/unit/test_cli_source_health.py
    - tests/unit/test_cli_replay.py
    - tests/integration/test_cycle_summary_e2e.py
    - tests/integration/test_cli_source_health.py
    - tests/integration/test_cli_replay.py
    - tests/integration/test_cli_post_now.py
  modified:
    - src/tech_news_synth/scheduler.py
    - src/tech_news_synth/synth/orchestrator.py
    - src/tech_news_synth/synth/models.py
    - src/tech_news_synth/db/source_state.py
    - tests/unit/test_synth_orchestrator.py
    - tests/integration/test_orchestrator_slow_day.py
decisions:
  - "D-04/D-05/D-06: cycle_summary emitted from scheduler.run_cycle outer finally AFTER session.commit() — not inside db/run_log.finish_cycle (which uses flush, not commit). 10 fields (8 OPS-01 + status + dry_run)."
  - "D-12: run_synthesis gains keyword-only persist: bool = True; persist=False returns post_id=None, status='replay', counts_patch['post_id']=None. SynthesisResult.status Literal widened."
  - "D-03: source-health has 4 modes (status, --json, --enable NAME, --disable NAME). Stdlib f-string table; enable/disable mutually exclusive."
  - "D-01: replay uses persist=False; resolves winner cycles via posts row + Cluster.chosen, fallback cycles via run_log.counts['fallback_article_id']; session.rollback() after synth as defense in depth."
  - "D-02: post-now inline-invokes scheduler.run_cycle. Exit 0 on ok/capped/dry_run/paused, 1 on error."
  - "Phase 6 counts_patch amended to carry char_budget_used (weighted_len of final text) — reachable even when persist=False."
metrics:
  duration_sec: 873
  completed_at: 2026-04-14T17:37:08Z
requirements_completed: [OPS-01, OPS-02, OPS-03, OPS-04]
---

# Phase 8 Plan 01: Observability + CLIs Summary

Delivered a single-line-per-cycle operator dashboard (`cycle_summary` structlog event) and three operator CLIs (`replay`, `post-now`, `source-health`) that replace the Phase 1 D-06 stubs, using the existing `__main__.py` argparse dispatcher. Zero new Python dependencies, zero schema changes, zero compose changes.

## Deliverables

### 1. `cycle_summary` aggregated log event (OPS-01, D-04/D-05/D-06)

`scheduler._emit_cycle_summary(cycle_id, status, counts, settings, started_at)` is invoked from the outer `finally` block of `run_cycle`, **after** `session.commit()` for `finish_cycle` succeeds. Durability invariant (Pitfall 1): if the line appears in logs, the run_log row was durably committed. On commit failure the emit is skipped and a `run_log_finish_failed` event is logged instead.

`cycle_started_at = datetime.now(UTC)` is captured on the first line of `run_cycle` — before any I/O, including kill-switch check — so `duration_ms` is a meaningful wall-clock for every non-paused cycle.

10 fields emitted (D-06):

| Field                        | Type           | Source                                   |
| ---------------------------- | -------------- | ---------------------------------------- |
| `cycle_id`                   | str (ULID)     | `new_cycle_id()`                         |
| `duration_ms`                | int            | `now - cycle_started_at`                 |
| `articles_fetched_per_source`| dict[str,int]  | `counts["articles_fetched"]`             |
| `cluster_count`              | int \| None    | `counts["cluster_count"]`                |
| `chosen_cluster_id`          | int \| None    | `counts["chosen_cluster_id"]`            |
| `char_budget_used`           | int \| None    | `counts["char_budget_used"]` (new)       |
| `token_cost_usd`             | float \| None  | `counts["synth_cost_usd"]`               |
| `post_status`                | str            | `counts["publish_status"]` \|\| "empty"  |
| `status`                     | str            | `run_log.status` (ok/error/paused)       |
| `dry_run`                    | bool           | `settings.dry_run`                       |

### 2. `run_synthesis` persist kwarg extension (D-12)

```python
def run_synthesis(..., *, persist: bool = True) -> SynthesisResult
```

`persist=True` (default): writes a posts row via `insert_post` — Phase 6 behavior, byte-for-byte identical on all paths (happy / retry / truncated / fallback).

`persist=False`: skips the `insert_post` call entirely; returns `SynthesisResult` with `post_id=None`, `status='replay'`, `counts_patch['post_id']=None`. Keyword-only so positional calls raise `TypeError` (T-08-02 mitigation).

`SynthesisResult.status` Literal widened to `{"pending", "dry_run", "replay"}`; `post_id: int | None`.

`counts_patch` also gains `char_budget_used: weighted_len(final_text)` — property of the synthesized text, not of persistence — so cycle_summary carries it even on replay.

### 3. `source_state` repository helpers

Three new module-level helpers in `src/tech_news_synth/db/source_state.py`:

```python
get_all_source_states(session) -> list[SourceState]  # ORDER BY name
enable_source(session, name) -> bool   # clears disabled_at + consecutive_failures=0
disable_source(session, name) -> bool  # sets disabled_at if currently null
```

Both toggles return `False` on unknown name, `True` on update (idempotent). Caller owns the commit.

### 4. `python -m tech_news_synth source-health` (OPS-04 / D-03)

Four modes:

```
python -m tech_news_synth source-health                  # aligned text table
python -m tech_news_synth source-health --json           # JSON list
python -m tech_news_synth source-health --enable NAME    # clear disabled_at
python -m tech_news_synth source-health --disable NAME   # set disabled_at
```

- `--enable` / `--disable` mutually exclusive (argparse group).
- Unknown NAME → `stderr: "unknown source: NAME"` and exit 1.
- Every toggle logs `source_toggled` structured event before commit (T-08-05 audit).
- Table uses stdlib f-string padding (no prettytable dep).

### 5. `python -m tech_news_synth replay --cycle-id X` (OPS-02 / D-01)

Re-runs synthesis against a past cycle without writing any posts row. Two resolution branches:

- **Winner**: query `Post WHERE cycle_id == X`; if `post.cluster_id IS NOT NULL`, fetch `Cluster` row, build `SelectionResult(winner_cluster_id=..., winner_article_ids=cluster.member_article_ids, winner_centroid=post.theme_centroid, ...)`.
- **Fallback**: if `post.cluster_id IS NULL`, read `fallback_article_id` from `run_log.counts` for that cycle (Phase 5 contract locked by `test_single_article_window_fallback`).
- Unresolvable cycle → `stderr: "cycle-id X not found or has no resolvable input"` and exit 1.

Calls `run_synthesis(..., persist=False)`. Explicit `session.rollback()` after synthesis as belt-and-suspenders defense. Prints JSON payload to stdout:

```json
{"cycle_id", "text", "hashtags", "source_url",
 "cost_usd", "input_tokens", "output_tokens", "final_method"}
```

Real Anthropic client constructed (CLI never mocks — tests mock `call_haiku` at the orchestrator boundary).

### 6. `python -m tech_news_synth post-now` (OPS-03 / D-02)

No arguments. One-shot inline invocation of `scheduler.run_cycle` with full boot chain (Settings + configure_logging + init_engine + sources_config + hashtag_allowlist). Does NOT register with APScheduler; safe to run alongside the scheduler. All Phase 7 guardrails honored through the reused `run_cycle` body — kill-switch, DRY_RUN, daily/monthly caps, anti-repeat, stale-pending cleanup, idempotency.

Exit codes:
- `0` — run_log.status == "ok" (includes capped→ok, dry_run→ok)
- `0` — paused (no run_log row written; documented behavior)
- `1` — run_log.status == "error"

Captures `invoked_at = datetime.now(UTC).replace(microsecond=0)` to survive fast-path timestamp-precision edge cases when locating "this invocation's" run_log row after the cycle.

### 7. Phase 5 `fallback_article_id` contract lock

Verified `counts_patch["fallback_article_id"]` is present on all three Phase 5 return paths (empty window → None, single-article → int, slow-day fallback → int). Added explicit regression assertion in `tests/integration/test_orchestrator_slow_day.py::test_single_article_window_fallback` so any future refactor of `_empty_counts_patch` or `run_clustering` breaks the test, not replay.

## Test Inventory

### Unit (18 new tests)

| File | Tests |
| ---- | ----- |
| `tests/unit/test_synth_orchestrator.py` | `test_run_synthesis_persist_false_skips_insert`, `test_run_synthesis_persist_must_be_keyword_only`; existing tests extended with `char_budget_used` assertion |
| `tests/unit/test_cycle_summary.py` | `test_emits_one_line_with_10_fields`, `test_paused_cycle_emits_no_summary`, `test_no_emit_on_commit_failure`, `test_emits_on_failed_cycle`, `test_dry_run_flag_propagates` |
| `tests/unit/test_cli_source_health.py` | `test_enable_unknown_exits_1`, `test_enable_known_returns_0_and_commits`, `test_disable_unknown_exits_1`, `test_mutually_exclusive_enable_disable`, `test_format_table_matches_columns`, `test_json_mode_emits_list` |
| `tests/unit/test_cli_replay.py` | `test_replay_unknown_cycle_exits_1`, `test_replay_winner_branch_builds_selection`, `test_replay_fallback_branch_reads_run_log_counts`, `test_replay_missing_cycle_id_exits_argparse`, `test_replay_post_exists_but_cluster_dangling_exits_1` |

### Integration (14 new tests)

| File | Tests |
| ---- | ----- |
| `tests/integration/test_cycle_summary_e2e.py` | `test_real_cycle_emits_summary` |
| `tests/integration/test_cli_source_health.py` | `test_status_mode`, `test_json_mode`, `test_enable_persists`, `test_disable_persists`, `test_enable_unknown_exits_1`, `test_disable_unknown_exits_1` |
| `tests/integration/test_cli_replay.py` | `test_replay_winner_no_posts_row`, `test_replay_fallback_cycle`, `test_replay_unknown_exits_1` |
| `tests/integration/test_cli_post_now.py` | `test_writes_run_log`, `test_respects_dry_run`, `test_respects_cap`, `test_respects_paused`, `test_run_log_error_exit_1` |
| `tests/integration/test_orchestrator_slow_day.py` | extended `test_single_article_window_fallback` with `fallback_article_id` contract assertion |

## Verification

- Unit suite: **381 passed** (Phase 1-7 baseline 363 + 18 new).
- Phase 8 integration: **19 passed** (cycle_summary_e2e, cli_source_health, cli_replay, cli_post_now, + extended slow_day). Full integration suite total: 113 passed (baseline 99 + 14 new).
- Ruff: clean on all Phase 8-touched files (2 pre-existing errors in `synth/hashtags.py` and `synth/orchestrator.py` line 129 are outside Phase 8 scope).

## Deviations from Plan

**None — plan executed exactly as written.** Three minor technique adjustments, none changing behavior or contracts:

1. **Integration test log capture**: Used in-memory `StreamHandler` + JSON-line parsing instead of `structlog.testing.capture_logs()`. The project pipeline uses `wrap_for_formatter`, which bypasses `capture_logs`. This mirrors the pattern already in `tests/unit/test_scheduler.py::capture_logs`.

2. **Integration test session isolation**: Replay integration tests call `db_session.commit()` after seeding to release the SAVEPOINT, ensuring seeds survive the CLI's own `session.rollback()`. Plan 08-01 contemplated subprocess tests; in-process with SAVEPOINT-release is both faster and properly isolated.

3. **`post-now` invoked_at precision**: Truncated to microsecond=0 so `started_at >= invoked_at` comparisons survive the fast-path case where Python and Postgres `NOW()` resolve to within a microsecond of each other on fast machines. Cosmetic only — the exit-code contract is unchanged.

## Commits

| Hash | Message |
| ---- | ------- |
| f100afc | feat(08-01): scaffold persist kwarg, source_state helpers, wave-0 test stubs |
| da53322 | feat(08-01): emit aggregated cycle_summary after commit (OPS-01) |
| 8ea6e84 | feat(08-01): implement source-health CLI (OPS-04) |
| 41be8f5 | feat(08-01): implement replay CLI (OPS-02) |
| a3c6073 | feat(08-01): implement post-now CLI (OPS-03) |
| 85e7e3c | chore(08-01): ruff cleanup (unused unpack, line length, getattr simplification) |

## Known Stubs

None. Every CLI has a real implementation; every stub test file was replaced with real tests in the task that owns the feature. The `cutover_verify.py` / `soak_monitor.py` stubs referenced in Plan 08-01's Task 1 note are owned by Plan 08-02 (Wave 2), not this plan.

## Self-Check: PASSED

- `src/tech_news_synth/cli/source_health.py`: FOUND
- `src/tech_news_synth/cli/replay.py`: FOUND
- `src/tech_news_synth/cli/post_now.py`: FOUND
- `tests/unit/test_cycle_summary.py`: FOUND
- `tests/integration/test_cycle_summary_e2e.py`: FOUND
- Commit f100afc: FOUND
- Commit da53322: FOUND
- Commit 8ea6e84: FOUND
- Commit 41be8f5: FOUND
- Commit a3c6073: FOUND
- Commit 85e7e3c: FOUND
