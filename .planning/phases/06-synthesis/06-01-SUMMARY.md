---
phase: 06-synthesis
plan: 01
subsystem: synth
tags: [synth, haiku-4-5, twitter-text-parser, pure-core, tdd]
requires:
  - phase-05-cluster-rank (SelectionResult)
  - phase-02-storage-layer (posts + articles repositories)
  - phase-01-foundation (Settings + structlog)
provides:
  - src/tech_news_synth/synth/charcount.py::weighted_len
  - src/tech_news_synth/synth/truncate.py::word_boundary_truncate
  - src/tech_news_synth/synth/article_picker.py::pick_articles_for_synthesis
  - src/tech_news_synth/synth/url_picker.py::pick_source_url
  - src/tech_news_synth/synth/hashtags.py::{HashtagAllowlist, load_hashtag_allowlist, select_hashtags}
  - src/tech_news_synth/synth/prompt.py::{build_system_prompt, build_user_prompt, build_retry_prompt, format_final_post}
  - src/tech_news_synth/synth/client.py::call_haiku
  - src/tech_news_synth/synth/pricing.py::{MODEL_ID, HAIKU_INPUT_USD_PER_MTOK, HAIKU_OUTPUT_USD_PER_MTOK, compute_cost_usd}
  - src/tech_news_synth/synth/models.py::SynthesisResult
  - src/tech_news_synth/db/articles.py::get_articles_by_ids
  - src/tech_news_synth/db/posts.py::insert_post
  - src/tech_news_synth/cluster/models.py::SelectionResult.winner_centroid
affects:
  - pyproject.toml (twitter-text-parser + setuptools<81)
  - config/hashtags.yaml (starter allowlist)
  - .env.example (synthesis settings documented)
  - src/tech_news_synth/cluster/orchestrator.py (centroid plumbing to SelectionResult)
tech-stack:
  added:
    - twitter-text-parser 3.0.0 (weighted char count)
    - setuptools <81 (pkg_resources shim for twitter-text-parser)
  patterns:
    - Pure-function modules per responsibility (charcount, truncate, pickers, hashtags, prompt, client, pricing)
    - TDD RED→GREEN for Tasks 2-5 (one commit per color)
    - pydantic frozen models at schema boundaries (HashtagAllowlist, SynthesisResult)
    - Settings extended with validators + `.env.example` documented
    - Mock-based SDK tests via pytest-mock (no live Anthropic calls in unit suite)
key-files:
  created:
    - src/tech_news_synth/synth/__init__.py
    - src/tech_news_synth/synth/charcount.py
    - src/tech_news_synth/synth/truncate.py
    - src/tech_news_synth/synth/article_picker.py
    - src/tech_news_synth/synth/url_picker.py
    - src/tech_news_synth/synth/hashtags.py
    - src/tech_news_synth/synth/prompt.py
    - src/tech_news_synth/synth/client.py
    - src/tech_news_synth/synth/pricing.py
    - src/tech_news_synth/synth/models.py
    - src/tech_news_synth/synth/orchestrator.py (stub; 06-02 fills)
    - config/hashtags.yaml
    - tests/fixtures/synth/hashtags.yaml
    - tests/fixtures/synth/post_01.json .. post_10.json
    - tests/unit/test_selection_result.py
    - tests/unit/test_charcount.py
    - tests/unit/test_truncate.py
    - tests/unit/test_article_picker.py
    - tests/unit/test_url_picker.py
    - tests/unit/test_hashtags.py
    - tests/unit/test_synth_prompt.py
    - tests/unit/test_synth_format.py
    - tests/unit/test_synth_client.py
  modified:
    - pyproject.toml (twitter-text-parser + setuptools<81)
    - uv.lock (regenerated)
    - .env.example (+5 synth knobs)
    - src/tech_news_synth/config.py (+5 Settings fields, D-13)
    - src/tech_news_synth/cluster/models.py (SelectionResult.winner_centroid)
    - src/tech_news_synth/cluster/orchestrator.py (serialize winner centroid on winner branch)
    - src/tech_news_synth/db/articles.py (get_articles_by_ids helper)
    - src/tech_news_synth/db/posts.py (insert_post helper; insert_pending preserved)
    - tests/unit/test_config.py (+3 synthesis-settings tests)
decisions:
  - D-01 applied (diverse-sources-first article picker)
  - D-02 applied (URL picker sort key -weight, -ts, id)
  - D-04 applied (twitter-text-parser for weighted counting)
  - D-05 applied (constants HASHTAG_BUDGET_CHARS=30 expressed via Settings.hashtag_budget_chars)
  - D-06 framework in place (retry prompt built by prompt.build_retry_prompt; orchestrator consumes in 06-02)
  - D-07 applied (system + user + retry prompts; ByteRelevant brand + injection clause)
  - D-08/09/10 applied (db.posts.insert_post signature + centroid + error_detail)
  - D-11 applied (config/hashtags.yaml + HashtagAllowlist + select_hashtags; LLM never picks)
  - D-13 applied (5 new Settings fields with validators)
  - T-06-01 mitigated (system prompt injection clause + 500-char summary truncation)
  - T-06-03 mitigated (MODEL_ID literal, unit-test equality assertion)
  - T-06-05 mitigated (select_hashtags algorithmically restricted to allowlist ∪ default)
  - T-06-07 mitigated (explicit ellipsis-weight gate in test_charcount; reservation in truncator)
  - T-06-08 mitigated (HashtagAllowlist.default non-empty validator + safe_load)
metrics:
  duration_minutes: ~45
  tasks: 5
  test_files_added: 9
  tests_added: 80
  unit_tests_total: 306
  baseline_preserved: true
  commits: 9 (1 scaffold + 4 RED + 4 GREEN)
  completed: 2026-04-14
---

# Phase 06 Plan 01: Pure-Core Synth Toolkit Summary

One-liner: Built the pure-function synthesis toolkit — weighted char
counting (twitter-text-parser), word-boundary truncation, diverse-source
article picker, weight-biased URL picker, YAML hashtag allowlist with
slug-match selector, PT-BR prompts with injection mitigation, and the
Anthropic Haiku 4.5 SDK wrapper — ready for Plan 06-02 to compose into a
full orchestrator.

## What Shipped

### `src/tech_news_synth/synth/`

| Module              | Public API                                                                                              | Notes                                                                       |
| ------------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `charcount.py`      | `weighted_len(text) -> int`, `ELLIPSIS = "\u2026"`                                                      | Thin wrapper; test_charcount gates ellipsis weight (observed value: 2)      |
| `truncate.py`       | `word_boundary_truncate(text, max_weighted) -> str`                                                     | Reserves ellipsis weight; prefers whitespace boundary; char-level fallback  |
| `article_picker.py` | `pick_articles_for_synthesis(cluster_articles, max_articles=5) -> list[Article]`                        | D-01 round-1 per source → round-2 global recency fill                       |
| `url_picker.py`     | `pick_source_url(selected_articles, source_weights) -> str`                                             | D-02 sort key `(-weight, -ts, id)`                                          |
| `hashtags.py`       | `HashtagAllowlist`, `load_hashtag_allowlist(path)`, `select_hashtags(centroid_terms, allowlist, ...)`   | slug substring-match against topic keys; LLM never picks (T-06-05)          |
| `prompt.py`         | `build_system_prompt`, `build_user_prompt`, `build_retry_prompt`, `format_final_post`, `SUMMARY_TRUNCATE_CHARS` | All anchors + T-06-01 injection clause + brand reference; summary caps 500  |
| `client.py`         | `call_haiku(client, system, user_prompt, max_tokens) -> (text, in_tok, out_tok)`                        | No tenacity wrap; exceptions propagate to cycle-level isolation             |
| `pricing.py`        | `MODEL_ID="claude-haiku-4-5"`, `HAIKU_INPUT_USD_PER_MTOK=1.00`, `HAIKU_OUTPUT_USD_PER_MTOK=5.00`, `compute_cost_usd` | T-06-03 literal model id                                                   |
| `models.py`         | `SynthesisResult` (frozen pydantic)                                                                     | Contract for 06-02 orchestrator → scheduler                                 |
| `orchestrator.py`   | (stub — Plan 06-02 fills)                                                                               | Placeholder raises `NotImplementedError`                                    |

### `SelectionResult` extension (Task 1)

```diff
class SelectionResult(BaseModel):
    ...
    counts_patch: dict[str, object]
+   # Phase 6 Plan 06-01: numpy float32 centroid bytes (D-09 plumbing).
+   # Default None preserves backward compat for the fallback branch.
+   winner_centroid: bytes | None = None
```

`cluster/orchestrator.py` now passes `winner_centroid=np.asarray(winner.centroid, dtype=np.float32).tobytes()` on the winner branch; fallback branch leaves it None. Pre-existing cluster orchestrator tests still green.

### DB helpers (Task 1)

Added to `db/articles.py`:
```python
def get_articles_by_ids(session, ids: list[int]) -> list[Article]
    # Preserves input order via {id: article} dict lookup; filters missing ids.
```

Added to `db/posts.py` (legacy `insert_pending` untouched):
```python
def insert_post(
    session, *, cycle_id, cluster_id, status, theme_centroid,
    synthesized_text, hashtags, cost_usd, error_detail=None,
) -> Post
    # JSON-serializes dict error_detail per D-10.
```

### Settings additions (D-13)

```python
synthesis_max_tokens: int = Field(default=150, ge=50, le=500)
synthesis_char_budget: int = Field(default=225, ge=100, le=280)
synthesis_max_retries: int = Field(default=2, ge=0, le=5)
hashtag_budget_chars: int = Field(default=30, ge=0, le=50)
hashtags_config_path: str = "/app/config/hashtags.yaml"
```

## Interfaces Exposed to Plan 06-02

Plan 06-02 will compose `synth/orchestrator.py::run_synthesis(session, cycle_id, selection, settings, anthropic_client) -> SynthesisResult` from the pure modules above. It will also:

1. Call `get_articles_by_ids(session, selection.winner_article_ids or [selection.fallback_article_id])` to materialize articles.
2. Call `pick_articles_for_synthesis` → `pick_source_url` → `build_user_prompt` → `call_haiku` in the retry loop → `word_boundary_truncate` last resort.
3. Use `centroid_terms` from the winning cluster (re-fetch or pass via SelectionResult extension — 06-02's decision) for `select_hashtags`.
4. Call `format_final_post` to compose the final string.
5. Call `insert_post(... status='pending'|'dry_run', theme_centroid=selection.winner_centroid, cost_usd=compute_cost_usd(...), error_detail=attempt_log_dict if truncated)`.
6. Wire into `scheduler.py::run_cycle` between `run_clustering` and `finish_cycle`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] twitter-text-parser 3.0.0 depends on removed `pkg_resources`**
- **Found during:** Task 1 (initial `uv sync` and smoke import)
- **Issue:** `twitter_text/regexp/emoji.py` imports `pkg_resources`, which setuptools 81+ removes. First `uv sync` installed setuptools 82 → `ModuleNotFoundError: No module named 'pkg_resources'`.
- **Fix:** Added `setuptools>=75,<81` to project dependencies so the pkg_resources shim stays available. Library itself works correctly at `parse_tweet(...).weightedLength` once pkg_resources is importable.
- **Files modified:** `pyproject.toml`, `uv.lock`
- **Commit:** e0496d6

**2. [Rule 1 — Bug] Ellipsis weight assumption in plan (weight 1) contradicts real library (weight 2)**
- **Found during:** Task 1 smoke check of twitter-text-parser 3.0.0
- **Issue:** Plan and execution rules assert `weighted_len(ELLIPSIS) == 1`. Measured value is 2 in twitter-text-parser 3.0.0. Shipping the `== 1` assertion would have produced silently over-budget posts (the threat T-06-07 explicitly warns about).
- **Fix:** test_charcount asserts the real observed weight (`== 2`) and truncator reserves `weighted_len(ELLIPSIS)` dynamically rather than hard-coding `1`. The T-06-07 mitigation (fail loudly if upstream changes) is preserved — this is exactly the "loud failure" the threat register wanted, just now at the correct value.
- **Files modified:** `tests/unit/test_charcount.py`, `src/tech_news_synth/synth/truncate.py`
- **Commit:** e2b7ed8

### Authentication gates

None — all synth unit tests use mocked Anthropic client. No live API calls during Plan 06-01.

## Open Items Deferred to 06-02

- `synth/orchestrator.py::run_synthesis` composition (retry loop + DRY_RUN branching + posts-row write).
- `scheduler.py::run_cycle` wiring (call order: run_ingest → run_clustering → run_synthesis → finish_cycle).
- `__main__.py` instantiation of `anthropic.Anthropic(api_key=...)` per cycle.
- Integration tests: `test_synth_orchestrator.py`, `test_synth_fixtures.py` (the 10-post spot-check), `test_synth_persist.py`, `test_synth_dry_run.py`, `test_synth_skipped.py`, `test_synth_error.py`.
- Compose smoke cycle with live Anthropic call (real $0.000038 per call, DRY_RUN=1 recommended).
- `run_log.counts` schema extension for synth telemetry (input/output tokens, cost, attempts, truncated flag, post_id).

## Tests

```text
tests/unit/test_charcount.py          6 tests
tests/unit/test_truncate.py          11 tests
tests/unit/test_article_picker.py     7 tests
tests/unit/test_url_picker.py         5 tests
tests/unit/test_hashtags.py          11 tests
tests/unit/test_synth_prompt.py      11 tests
tests/unit/test_synth_format.py       4 tests
tests/unit/test_synth_client.py      13 tests
tests/unit/test_selection_result.py   3 tests
tests/unit/test_config.py            +3 tests (synthesis settings)
```

Unit suite: **306 passed** (baseline 226 + 80 new) — Phase 1–5 baseline preserved.

## Self-Check: PASSED

- All listed files exist on disk (verified via git status after final commit).
- All per-task commit hashes verifiable in `git log`:
  - e0496d6 (Task 1 scaffold)
  - f542add (Task 2 RED) + e2b7ed8 (Task 2 GREEN)
  - 0700ba2 (Task 3 RED) + cbd3916 (Task 3 GREEN)
  - 06fd6d3 (Task 4 RED) + d7ba1e2 (Task 4 GREEN)
  - 7d06497 (Task 5 RED) + 35539ea (Task 5 GREEN)
