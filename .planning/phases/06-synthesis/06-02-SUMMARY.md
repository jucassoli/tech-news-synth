---
phase: 06-synthesis
plan: 02
subsystem: synth
status: awaiting-checkpoint
tags: [synth, orchestrator, scheduler, haiku-4-5, anthropic, compose-smoke-pending]
requires:
  - phase-06-plan-01 (pure-core toolkit)
  - phase-05-cluster-rank (SelectionResult.winner_centroid)
  - phase-02-storage-layer (insert_post + get_articles_by_ids)
  - phase-01-foundation (Settings + structlog + scheduler frame)
provides:
  - src/tech_news_synth/synth/orchestrator.py::run_synthesis
  - src/tech_news_synth/scheduler.py::run_cycle (Phase 6 wiring)
  - src/tech_news_synth/__main__.py::_dispatch_scheduler (boot-time allowlist load)
affects:
  - tests/unit/test_scheduler.py (Phase 4/5 tests updated for synth-aware MagicMock)
tech-stack:
  added: []
  patterns:
    - TDD RED→GREEN per task (2 RED + 2 GREEN + 1 integration test commit)
    - Pure-core toolkit composition in orchestrator (imports only, no reimplementation)
    - Per-cycle Anthropic client lifecycle (not module-level; INFRA-08 compatible)
    - Boot-time fail-fast config load (sources.yaml + hashtags.yaml)
    - Empty-window short-circuit at scheduler (never reaches run_synthesis with empty selection)
key-files:
  created:
    - src/tech_news_synth/synth/orchestrator.py (run_synthesis composition)
    - tests/unit/test_synth_orchestrator.py (8 tests)
    - tests/unit/test_synth_skipped.py (1 test — empty selection guard)
    - tests/unit/test_synth_error.py (1 test — anthropic error propagation)
    - tests/integration/test_synth_persist.py (2 tests — posts row + error_detail)
    - tests/integration/test_synth_dry_run.py (1 test — D-12 status='dry_run')
    - tests/integration/test_synth_fixtures.py (10 tests — 10-post spot-check)
  modified:
    - src/tech_news_synth/scheduler.py (Phase 6 wiring + allowlist threading)
    - src/tech_news_synth/__main__.py (load_hashtag_allowlist at boot)
    - tests/unit/test_scheduler.py (added 4 Phase 6 tests + updated 3 earlier tests)
decisions:
  - D-06 applied (3-attempt retry loop; build_retry_prompt between attempts)
  - D-08/09/10 applied (insert_post with all fields; error_detail JSON-serialized on truncation)
  - D-12 applied (DRY_RUN still calls Anthropic; status='dry_run', cost_usd>0)
  - T-06-09 mitigated (hard assert `weighted_len(final_text) <= 280` pre-insert)
  - T-06-10 mitigated (attempts bounded by Settings validator; logged in run_log)
  - T-06-11 mitigated (synth_done event never includes body_text / user_prompt)
  - T-06-13 accepted (flush-but-no-commit; INFRA-08 rolls back posts row on crash)
  - T-06-14 mitigated (cost written to posts.cost_usd AND run_log.counts.synth_cost_usd)
  - T-06-15 mitigated (load_hashtag_allowlist at boot in __main__; fail-fast)
  - T-06-16 mitigated (status = "dry_run" if settings.dry_run else "pending" — pure expr)
metrics:
  duration_minutes: ~50
  tasks: 3 (2 auto + 1 checkpoint)
  test_files_added: 6
  tests_added: 23 (10 unit + 13 integration)
  unit_tests_total: 320 (baseline 306 + 10 synth_orchestrator/skipped/error + 4 scheduler)
  integration_tests_total: 74 (baseline 61 + 2 persist + 1 dry_run + 10 fixtures)
  total_tests_total: 394
  baseline_preserved: true
  commits: 5 (2 RED + 2 GREEN + 1 integration-test)
  completed: 2026-04-14
requirements:
  - SYNTH-01
  - SYNTH-02
  - SYNTH-03
  - SYNTH-04
  - SYNTH-05
  - SYNTH-06
  - SYNTH-07
---

# Phase 06 Plan 02: Orchestrator + Scheduler Integration Summary

One-liner: Composed the 06-01 pure-core toolkit into `run_synthesis`, wired
it into `scheduler.run_cycle` with per-cycle Anthropic client lifecycle and
boot-time hashtag-allowlist load, proven by 10-post fixture spot-check
(weighted_len ≤ 280 invariant) and Phase 1-5 scheduler baseline preserved.
Awaiting operator compose-smoke verification (Task 3 human-verify gate).

## What Shipped

### `src/tech_news_synth/synth/orchestrator.py::run_synthesis`

Final signature (matches plan interface block):

```python
def run_synthesis(
    session: Session,
    cycle_id: str,
    selection: SelectionResult,
    settings: Settings,
    sources_config: SourcesConfig,
    anthropic_client: anthropic.Anthropic,
    hashtag_allowlist: HashtagAllowlist,
) -> SynthesisResult
```

Winner-branch semantics:

1. `get_articles_by_ids(session, selection.winner_article_ids)` → materialize.
2. `pick_articles_for_synthesis(..., max_articles=5)` (D-01 diverse-sources).
3. `pick_source_url(selected, source_weights_from_sources_config)` (D-02).
4. `session.get(Cluster, winner_cluster_id).centroid_terms` → `select_hashtags`.
5. `theme_centroid = selection.winner_centroid` (bytes from 06-01).

Fallback-branch semantics:

1. `session.get(Article, selection.fallback_article_id)` → single article.
2. `selected = [article]`; `source_url = article.url`.
3. `cluster_id = None`; `theme_centroid = None`; `centroid_terms = {}`.
4. Hashtags collapse to `allowlist.default[:max_tags]` (select_hashtags handles
   empty centroid_terms).

Shared retry loop (D-06):

- `max_attempts = settings.synthesis_max_retries + 1` (default 3).
- Each attempt: `call_haiku → candidate = format_final_post(text, url, hashtags) →
  if weighted_len(candidate) <= 280: break`.
- Else build `build_retry_prompt(text, cand_len, body_budget - 10)` for next attempt.
- Tokens accumulated across attempts; cost computed with total at end.
- `for-else` loop: if exhausted, `word_boundary_truncate(last_text, 280 - overhead)`.
  `overhead = 1 + 23 + (1 + weighted_len(hashtag_block) if hashtags else 0)`.
- `final_method` = `"completed" | "truncated"`.

Persistence (D-08/09/10):

- `insert_post(cycle_id, cluster_id, status, theme_centroid, synthesized_text,
  hashtags, cost_usd, error_detail)`.
- `status = "dry_run" if settings.dry_run else "pending"` (D-12).
- `error_detail = json.dumps(attempt_log)` ONLY when truncated (D-10).
- `session.flush()` — caller commits.

Invariants (pre-insert):

- `assert weighted_len(final_text) <= 280` — T-06-09 hard gate.
- `assert body_text is not None`.

Logging:

- `log = _log.bind(phase="synth", cycle_id=cycle_id)` at entry.
- Per-attempt `synth_attempt` event: `attempt, length, input_tokens, output_tokens`.
- Terminal `synth_done` event: `attempts, final_method, input_tokens,
  output_tokens, cost_usd, post_id`. **No body_text / user_prompt** (T-06-11).
- On truncation: additional `synth_truncated` warning with `final_length_estimate`.

Return `SynthesisResult` with `counts_patch`:

```python
counts_patch = {
    "synth_attempts": int,
    "synth_truncated": bool,
    "synth_input_tokens": int,
    "synth_output_tokens": int,
    "synth_cost_usd": float,
    "post_id": int,
}
```

### `src/tech_news_synth/scheduler.py::run_cycle` diff (before → after)

Before (end of Phase 5):

```python
ingest_counts = run_ingest(...)
selection = run_clustering(...)
counts = {**ingest_counts, **selection.counts_patch}
```

After (Phase 6):

```python
ingest_counts = run_ingest(...)
selection = run_clustering(...)
synth_patch: dict[str, object] = {}
if (
    selection.winner_cluster_id is not None
    or selection.fallback_article_id is not None
):
    if hashtag_allowlist is None:
        hashtag_allowlist = load_hashtag_allowlist(
            Path(settings.hashtags_config_path)
        )
    anthropic_client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
    )
    synthesis = run_synthesis(
        session, cycle_id, selection, settings, sources_config,
        anthropic_client, hashtag_allowlist,
    )
    synth_patch = synthesis.counts_patch
counts = {**ingest_counts, **selection.counts_patch, **synth_patch}
```

Empty-window short-circuit: when Phase 5 returns both `winner_cluster_id=None`
and `fallback_article_id=None`, the scheduler skips `run_synthesis` entirely
(and therefore never constructs an Anthropic client, never touches
`hashtags.yaml`). `synth_patch={}` merges as identity and `finish_cycle`
receives only ingest + selection counts. Unit-test
`test_scheduler_skips_synthesis_when_empty_window` pins this behavior.

### Anthropic client lifecycle

**Per-cycle, not module-level.** Mirrors the httpx pattern from Phase 4
(`build_http_client()` inside `_run_cycle_body`). Rationale:

- Consistent with existing `http_client` pattern (operator mental model
  — one cycle = one batch of external clients, all closed at cycle end).
- No shared state across cycles (SDK handles its own httpx pool; client goes
  out of scope when `_run_cycle_body` returns).
- Under `DRY_RUN=1` the client IS still built and called (D-12); we rely on
  the `Settings.anthropic_api_key` being present even in dry runs.

### Hashtag allowlist lifecycle

**Boot-time load, pass-through to cycle closures.** Pattern mirrors
`sources_config` from Phase 4:

1. `__main__._dispatch_scheduler` calls `load_hashtag_allowlist(Path(settings.hashtags_config_path))`
   AFTER `load_sources_config` — same fail-fast layer, same exit code 2 on error.
2. Loaded `HashtagAllowlist` instance is threaded through
   `run(settings, sources_config=..., hashtag_allowlist=...)` → `build_scheduler(..., hashtag_allowlist=...)`
   → `add_job(..., kwargs={"hashtag_allowlist": allowlist})`.
3. `run_cycle` accepts it as an optional parameter; if None (e.g., Phase 1 legacy
   test path that doesn't pass sources_config), it's loaded lazily on first use.

This satisfies T-06-15: malformed `hashtags.yaml` crashes the container at boot
(not at cycle time), no silent degradation.

## Deviations from Plan

None — plan executed as written.

### Auto-fixed Issues

**1. [Rule 3 — Blocking] Existing Phase 4 test had truthy MagicMock attrs**

- **Found during:** Task 2 GREEN (first scheduler pytest run after wiring synth).
- **Issue:** `test_run_cycle_calls_run_ingest_with_counts` used
  `mocker.MagicMock(counts_patch={})` as its run_clustering return value.
  With Phase 6 wiring, `MagicMock.winner_cluster_id` auto-returns a truthy
  MagicMock, so the new `if winner or fallback` branch fired and tried to
  load `/app/config/hashtags.yaml` (not present in unit-test environment) →
  cycle crashed with `FileNotFoundError` → `finish_cycle` status='error'
  instead of 'ok' → assertion failure.
- **Fix:** Explicitly set `winner_cluster_id=None, fallback_article_id=None`
  on the MagicMock so the empty-window short-circuit fires. This better
  reflects the test's intent ("focus on Phase 4 wiring").
- **Files modified:** `tests/unit/test_scheduler.py`.
- **Commit:** 6f94171 (same commit as scheduler wiring — integral fix).

### Authentication gates

None — unit + integration tests use mocked `call_haiku`. The compose-smoke
verification in Task 3 will exercise real Haiku 4.5 at ~$0.000038/call.

## Tests

```text
tests/unit/test_synth_orchestrator.py    8 tests (winner/fallback/retry/truncate/DRY_RUN/error)
tests/unit/test_synth_skipped.py         1 test  (empty-selection ValueError guard)
tests/unit/test_synth_error.py           1 test  (Anthropic error propagates, no insert)
tests/unit/test_scheduler.py            +4 tests (synth wiring, empty-window, fallback, INFRA-08)
tests/integration/test_synth_persist.py  2 tests (cost + error_detail)
tests/integration/test_synth_dry_run.py  1 test  (D-12 status='dry_run')
tests/integration/test_synth_fixtures.py 10 tests (post_01..10 — weighted_len ≤ 280 invariant)
```

**Baseline preserved:**
- Unit: 306 (Plan 06-01) → 320 (this plan). +10 new synth unit tests, +4 new
  scheduler tests. Existing scheduler tests still green (3 updated to patch
  `run_synthesis`).
- Integration: 61 → 74. +13 new tests; no existing integration test modified.
- **Total: 394 passed** (`uv run pytest tests/ -q` with
  `TEST_DATABASE_URL=postgresql+psycopg://app:replace-me@172.19.0.2:5432/tech_news_synth_test`).

## Interfaces Exposed to Phase 7

- `posts.status IN ('pending', 'dry_run')` rows present after every
  non-empty-window cycle. Phase 7 will query
  `SELECT id, synthesized_text, status FROM posts WHERE status='pending' ORDER BY created_at`
  and `UPDATE posts SET tweet_id=..., posted_at=..., status='posted'` (D-08).
- `run_log.counts` contains `synth_attempts, synth_truncated, synth_input_tokens,
  synth_output_tokens, synth_cost_usd, post_id` for every cycle that ran synthesis.
- Cost telemetry doubled: `posts.cost_usd` (per-post) AND
  `run_log.counts.synth_cost_usd` (per-cycle) — T-06-14 double-entry.

## Compose Smoke — Awaiting Operator (Task 3 Checkpoint)

Per plan, Task 3 is `checkpoint:human-verify` with 6 gated checks:

1. `docker compose down -v && docker compose up -d --build` succeeds.
2. Streamed logs show `{"event": "synth_done", ...}` within ~30-90s.
3. `psql -c "SELECT id, status, length(synthesized_text), cost_usd, hashtags
   FROM posts ORDER BY created_at DESC LIMIT 3;"` shows a row with
   `status IN ('pending','dry_run')`, PT-BR preview, `cost_usd > 0 AND < 0.001`,
   non-empty hashtags array.
4. `psql -c "SELECT counts->>'synth_attempts', counts->>'synth_cost_usd',
   counts->>'post_id' FROM run_log ORDER BY started_at DESC LIMIT 1;"` shows
   all synth_* fields populated.
5. `docker compose logs app | grep '"phase":"synth"'` returns at least one
   `synth_done` line.
6. Operator reads 3 most-recent `synthesized_text` values aloud, confirms:
   - fluent PT-BR jornalístico neutro (no emojis, no exclamations);
   - all named entities / numbers appear in source `articles.title`/`summary`
     (no hallucination);
   - URL matches an ingested `articles.url`;
   - hashtags come from `config/hashtags.yaml` (not LLM-freestyled).

**On approval:** Plan 06-02 closes; Phase 7 (posting) can begin.

**On failure:** operator shares the offending SQL output / log excerpt; executor
debugs and re-runs. Expected failure modes: posts row missing (check `anthropic`
import, `ANTHROPIC_API_KEY` env), cost_usd=0 (token accounting bug),
hallucinated facts (prompt regression — tweak `build_system_prompt`),
freestyled hashtag (select_hashtags bypass), over-280 post (truncate bug).

## Phase 6 Requirements Satisfied (Test Mapping)

| Req       | Coverage                                                                                              |
| --------- | ----------------------------------------------------------------------------------------------------- |
| SYNTH-01  | `call_haiku` invoked via orchestrator; unit + integration tests                                      |
| SYNTH-02  | `build_system_prompt` drives tone; existing 06-01 unit tests + integration spot-checks               |
| SYNTH-03  | `build_user_prompt` framing (Fonte/Título/Resumo); 06-01 unit tests                                  |
| SYNTH-04  | Retry + truncation invariant `weighted_len <= 280` across 10 fixtures (`test_synth_fixtures.py`)      |
| SYNTH-05  | `select_hashtags` deterministic allowlist; `test_fixture_spot_check_weighted_len` asserts ≥1 hashtag |
| SYNTH-06  | `format_final_post` end-to-end in fixtures                                                           |
| SYNTH-07  | `posts.cost_usd > 0` in `test_synth_persist` + `run_log.counts.synth_cost_usd` via `counts_patch`    |

## Self-Check: PASSED

Files verified on disk:
- FOUND: src/tech_news_synth/synth/orchestrator.py
- FOUND: src/tech_news_synth/scheduler.py
- FOUND: src/tech_news_synth/__main__.py
- FOUND: tests/unit/test_synth_orchestrator.py
- FOUND: tests/unit/test_synth_skipped.py
- FOUND: tests/unit/test_synth_error.py
- FOUND: tests/integration/test_synth_persist.py
- FOUND: tests/integration/test_synth_dry_run.py
- FOUND: tests/integration/test_synth_fixtures.py

Commits verified in `git log`:
- FOUND: 91c2ee7 (test: RED run_synthesis orchestrator)
- FOUND: 1a41dd3 (feat: GREEN run_synthesis orchestrator)
- FOUND: 43f0222 (test: integration synth persistence/dry_run/fixtures)
- FOUND: 3286d33 (test: RED scheduler synth wiring)
- FOUND: 6f94171 (feat: GREEN scheduler wiring + boot-time allowlist load)

Final test run: 394 passed (320 unit + 74 integration), 1 warning
(pkg_resources deprecation from twitter-text-parser — inherited, tracked in
06-01 deviations).
