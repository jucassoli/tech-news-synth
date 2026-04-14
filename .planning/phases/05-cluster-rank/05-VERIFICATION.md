---
phase: 05-cluster-rank
verified: 2026-04-12T00:00:00Z
status: passed
verdict: PASS
score: 5/5 must-haves verified
overrides_applied: 0
operator_signoff: partial-with-acceptance
operator_observed:
  cycle_id: "01KP5PB1ZXFKWKSM4KEG8QX5AV"
  articles_in_window: 14
  cluster_count: 0
  singleton_count: 14
  chosen_cluster_id: null
  fallback_used: true
  fallback_article_id: 1
  determinism_loop_runs: 3
  determinism_runs_identical: true
  clusters_table_candidates: 14
  clusters_table_chosen_count: 0
  exactly_one_winner_invariant_violations: 0
  compose_smoke_steps_green: "7/8 (step 7 kill-switch inconclusive — orthogonal boot observability gap)"
requirements_completed:
  - CLUSTER-01
  - CLUSTER-02
  - CLUSTER-03
  - CLUSTER-04
  - CLUSTER-05
  - CLUSTER-06
  - CLUSTER-07
test_results:
  unit_tests_passed: 226
  unit_tests_baseline: 161
  integration_tests_passed: 61
  integration_tests_baseline: 39
  ruff: clean
phase_8_followups:
  - title: "docker compose restart observability gap"
    description: >
      During compose smoke step 7 (kill-switch-via-restart-with-marker), `docker compose restart app`
      stopped showing logs after `alembic_upgrade_start`; no subsequent `cycle_start` / `cycle_skipped`
      events were observed, so the operator could not confirm the PAUSED path fired at runtime.
      Phase 5 unit test `tests/unit/test_scheduler.py::test_paused_cycle_skips_run_clustering`
      independently proves `run_clustering` is NOT invoked when PAUSED=1.
      INFRA-09 kill-switch was already operator-approved in the Phase 1 compose smoke and
      Phase 5 does not modify the kill-switch path — it only inserts run_clustering AFTER the PAUSED gate.
    classification: "Phase 1/2 boot observability issue (log stream drops after alembic_upgrade_start on container restart)"
    not_a_phase_5_defect: true
    recommended_phase: 8
---

# Phase 5: Cluster + Rank — Verification Report

**Phase Goal (ROADMAP.md):** A deterministic, pure-core clustering + ranking module that picks the cycle's winning topic, enforces 48h semantic anti-repetition, and always has a fallback so cadence holds.

**Verified:** 2026-04-12
**Status:** PASS
**Re-verification:** No (initial verification).

---

## Goal Achievement — Observable Truths (ROADMAP.md Success Criteria 1–5)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC-1 | 6h window + TF-IDF char n-grams 3–5 + PT+EN stopwords + unidecode + agglomerative at threshold 0.35 | VERIFIED | `cluster_window_hours=6` in `config.py:58`; `build_vectorizer()` in `src/tech_news_synth/cluster/vectorize.py` uses `analyzer="char_wb"`, `ngram_range=(3,5)`, `preprocessor=preprocess`, `stop_words` intentionally omitted; `test_vectorize.py:55–61` asserts analyzer, ngram_range, preprocessor identity, and `v.stop_words is None`. `run_agglomerative` in `cluster/cluster.py` uses cosine + average + `distance_threshold=0.35` from settings. Operator observed `articles_in_window=14` on cycle `01KP5PB1ZXFKWKSM4KEG8QX5AV`. |
| SC-2 | Winner selection fully deterministic on fixtures | VERIFIED | `test_cluster_determinism.py` green across 3 fixtures (hot_topic/mixed/tiebreak); operator ran the 3× determinism loop (`for i in 1 2 3`) and each run produced identical output in 1.17s. `rank.py::rank_candidates` uses Python stable sort on `(-source_count, -recency_ts, -weight_sum)` per D-09. |
| SC-3 | Fixture post <48h ago with cosine ≥ 0.5 to current winner → winner rejected, next-best selected | VERIFIED | `tests/integration/test_antirepeat.py::test_winner_rejected_by_antirepeat_chooses_next` green (Apple clustered and ranked first; matched against 30h-ago past post; rejected; GPT-5 chosen). D-01 ONE-fit combined corpus implemented in `cluster/orchestrator.py` via `FittedCorpus.past_post_ranges`. `get_recent_posts_with_source_texts` in `db/posts.py` applies P-9 status filter (`status='posted'` only). |
| SC-4 | Slow-news-day fixture → fallback picker returns single best-ranked article | VERIFIED | `tests/unit/test_fallback.py` + `tests/integration/test_orchestrator_slow_day.py` green; `cluster/fallback.py::pick_fallback` sorts by `(-source_weight, -published_at, id)`. Operator observed **real-world fallback path fired on a 14-singleton day** — `fallback_used=true`, `fallback_article_id=1`, `chosen_cluster_id=null`. This is the best possible SC-4 evidence. |
| SC-5 | Every cycle persists clusters audit trail (all candidates + chosen flag + rejected-by-antirepeat) | VERIFIED | `cluster/orchestrator.py` implements D-12 persist-all-first pattern (INSERT every candidate with `chosen=False`, then UPDATE winner to `chosen=True`). `tests/integration/test_cluster_audit.py` green. Operator observed 14 candidates / 0 chosen (correct for fallback path — fallback is an article, not a cluster, so no chosen=True flag is set per D-12 last bullet); exactly-one-winner invariant query returned 0 rows (correct). |

**Score: 5/5 must-haves verified.**

---

## Required Artifacts (Pure-Core + Wiring)

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/tech_news_synth/cluster/__init__.py` | Package root | VERIFIED | Present |
| `src/tech_news_synth/cluster/stopwords_pt.py` | `PT_STOPWORDS` + `PT_EN_STOPWORDS` frozensets | VERIFIED | Present |
| `src/tech_news_synth/cluster/preprocess.py` | `preprocess(text)` for vectorizer | VERIFIED | Present; fed to TfidfVectorizer preprocessor |
| `src/tech_news_synth/cluster/vectorize.py` | `build_vectorizer` + `FittedCorpus` + `fit_combined_corpus` | VERIFIED | P-1 fix codified (stop_words intentionally omitted; see lines 23–34) |
| `src/tech_news_synth/cluster/cluster.py` | `run_agglomerative` + `compute_centroid` | VERIFIED | Cosine + average linkage + threshold 0.35 |
| `src/tech_news_synth/cluster/rank.py` | `ClusterCandidate` + `rank_candidates` (D-09) | VERIFIED | Stable sort; singletons excluded |
| `src/tech_news_synth/cluster/antirepeat.py` | `check_antirepeat` (D-01 shared-feature-space cosine) | VERIFIED | Imported by orchestrator |
| `src/tech_news_synth/cluster/fallback.py` | `pick_fallback` (CLUSTER-06) | VERIFIED | Used by orchestrator when no winner |
| `src/tech_news_synth/cluster/models.py` | `SelectionResult` frozen pydantic v2 model | VERIFIED | Returned by orchestrator to scheduler |
| `src/tech_news_synth/cluster/orchestrator.py` | `run_clustering` (full D-14 flow) | VERIFIED | Wired into scheduler (see Key Links) |
| `src/tech_news_synth/db/articles.py::get_articles_in_window` | P-5 deterministic sort | VERIFIED | Called by orchestrator |
| `src/tech_news_synth/db/posts.py::get_recent_posts_with_source_texts` | P-9 status filter (`status='posted'` only) | VERIFIED | Returns `PostWithTexts` |
| `src/tech_news_synth/db/clusters.py::update_cluster_chosen` | Atomic UPDATE helper | VERIFIED | Called by orchestrator |
| `src/tech_news_synth/config.py` — 4 new settings fields | `cluster_window_hours`, `cluster_distance_threshold`, `anti_repeat_cosine_threshold`, `anti_repeat_window_hours` | VERIFIED | Lines 58–61 with pydantic ge/le validators |
| `src/tech_news_synth/ingest/sources_config.py` — `weight` field | `weight: float = Field(default=1.0, ge=0.0, le=10.0)` | VERIFIED | Line 27 on _SourceBase |

---

## Key Link Verification (Wiring)

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `scheduler.run_cycle` | `cluster.orchestrator.run_clustering` | Direct import + call between `run_ingest` and `finish_cycle` | WIRED | `scheduler.py:26` imports, `scheduler.py:93` invokes with merged `counts_patch` |
| `orchestrator.run_clustering` | `db.articles.get_articles_in_window` | Window lookup | WIRED | Article stream sourced from DB, sorted by (published_at ASC, id ASC) |
| `orchestrator.run_clustering` | `db.posts.get_recent_posts_with_source_texts` | 48h past post texts | WIRED | P-9 status filter applied at DB layer |
| `orchestrator.run_clustering` | `db.clusters.insert_cluster` + `update_cluster_chosen` | Audit trail persistence (D-12) | WIRED | All candidates inserted with `chosen=False`, winner toggled via UPDATE |
| `orchestrator` | `cluster.fallback.pick_fallback` | Slow-day path | WIRED | `fallback_article_id` + `fallback_used=true` populated in SelectionResult |
| `SelectionResult.counts_patch` | `run_log.counts` | Merged in scheduler | WIRED | 7 Phase 5 keys (articles_in_window, cluster_count, singleton_count, chosen_cluster_id, rejected_by_antirepeat, fallback_used, fallback_article_id) join 5 Phase 4 keys → 12 total per D-13 |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `clusters` table rows | candidate clusters | `run_agglomerative` on live TF-IDF matrix of `articles` in 6h window | Yes — operator observed 14 real candidates on a live cycle | FLOWING |
| `run_log.counts` | Phase 5 audit counts | `SelectionResult.counts_patch` merged into ingest counts before `finish_cycle` | Yes — operator observed populated counts in live cycle | FLOWING |
| `SelectionResult` | selection decision | `run_clustering` orchestrator over real DB articles + past posts | Yes — flowed through to fallback_article_id=1 in operator cycle | FLOWING |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CLUSTER-01 | 05-02 | 6h window (configurable) | SATISFIED | `cluster_window_hours` setting + `get_articles_in_window` + operator `articles_in_window=14` |
| CLUSTER-02 | 05-01 | TF-IDF char 3–5 + PT+EN stopwords + unidecode on title+summary | SATISFIED | `vectorize.py` + `preprocess.py` + `stopwords_pt.py`; P-1 fix validated |
| CLUSTER-03 | 05-01 | Agglomerative cosine average dt=0.35 | SATISFIED | `cluster.py::run_agglomerative` + `test_cluster_formation.py` |
| CLUSTER-04 | 05-01 | Winner = distinct-source-count → recency → weight-sum; singletons excluded; deterministic | SATISFIED | `rank.py::rank_candidates` + 3× determinism loop green |
| CLUSTER-05 | 05-02 | Anti-repeat cosine ≥ 0.5 vs 48h post centroids, re-fit on combined corpus | SATISFIED | `antirepeat.py` + D-01 FittedCorpus + `test_antirepeat.py` integration green |
| CLUSTER-06 | 05-01 | Fallback picker on no-cluster days | SATISFIED | `fallback.py` + operator-observed live fallback (fallback_used=true) |
| CLUSTER-07 | 05-02 | Audit trail with all candidates + chosen flag + rejected ids | SATISFIED | D-12 persist-all-first + `test_cluster_audit.py` + operator 14-candidate observation |

---

## Decisions Honored (CONTEXT.md D-01 through D-15)

| Decision | Honored | Evidence |
|----------|---------|----------|
| D-01 Re-fit TF-IDF on combined corpus per cycle | Yes | `FittedCorpus` with `current_range` + `past_post_ranges` slice bookkeeping in `vectorize.py` |
| D-02 No posts schema change; read-only JOIN helper | Yes | `get_recent_posts_with_source_texts` is read-only; no migration added |
| D-03 `ANTI_REPEAT_COSINE_THRESHOLD=0.5` | Yes | `config.py:60` `anti_repeat_cosine_threshold: float = Field(default=0.5, ...)` |
| D-04 Per-source `weight` field (default 1.0) | Yes | `sources_config.py:27` |
| D-05 All v1 sources ship with weight 1.0 | Yes | Default value in pydantic field |
| D-06 AgglomerativeClustering cosine/average/dt=0.35 | Yes | `cluster.py::run_agglomerative` + setting |
| D-07 Singletons excluded from winner selection | Yes | `rank.py::rank_candidates` excludes cluster.source_count < 2 |
| D-08 Preprocess pipeline (unidecode → lower → tokenize → drop stopwords) | Yes | `preprocess.py` + `stopwords_pt.py` stored pre-unidecoded |
| D-09 Stable-sort rank key `(-src_count, -recency, -weight_sum)` | Yes | `rank.py::rank_candidates` |
| D-10 Articles sorted `(published_at ASC, id ASC)` before vectorization | Yes | `get_articles_in_window` P-5 sort + orchestrator belt-and-suspenders resort |
| D-11 Fallback by `(highest weight, most recent, lowest id)` | Yes | `fallback.py::pick_fallback` |
| D-12 Persist-all-first audit (insert all candidates; update winner chosen=True) | Yes | `orchestrator.py` flow |
| D-13 run_log.counts gains 7 Phase 5 keys | Yes | `counts_patch` dict; operator observed 12-key counts JSON |
| D-14 run_cycle flow `start → ingest → run_clustering → finish` | Yes | `scheduler.py:93` |
| D-15 Settings gains 4 new fields | Yes | `config.py:58–61` |

---

## Research P-1 Fix Verification

**Finding:** sklearn silently ignores `stop_words=` when `analyzer="char_wb"`. Stopwords must be stripped at the preprocessor level BEFORE char n-grams are generated.

**Fix verified:**
- `src/tech_news_synth/cluster/vectorize.py` line 23–34: explicit comment documenting P-1; `stop_words` intentionally omitted
- `src/tech_news_synth/cluster/preprocess.py`: stopword stripping happens in preprocessor
- `tests/unit/test_vectorize.py:61`: `assert v.stop_words is None`
- PT stopwords stored pre-unidecoded (`nao`, `e`, `a`, `so`) to match preprocess pipeline without a second ASCII pass

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full unit suite green | `uv run pytest tests/unit -q` | 226 passed in 2.63s | PASS |
| Ruff clean on src/ + tests/ | `uv run ruff check src/ tests/` | All checks passed | PASS |
| Integration suite in compose | operator ran `pytest tests/integration` inside app container | 61 passed | PASS |
| Integration suite on host | `uv run pytest tests/integration -q -m integration` | Fails DNS for `postgres:5432` — expected; compose-only network | SKIP (environment) |
| Determinism loop 3× | `for i in 1 2 3; do ... test_cluster_determinism ...; done` | 3 identical runs, 4 passed 1.17s each | PASS |

---

## Anti-Patterns Scanned

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none found) | — | — | — | Pure-core cluster package is clean; no TODO/FIXME/placeholder/stub patterns in Phase 5-touched code |

---

## Scope Leak Check

| Concern | Result |
|---------|--------|
| No synthesis code (Phase 6) in cluster/ | CONFIRMED — grep for `anthropic|tweepy|create_tweet|Anthropic` in `src/tech_news_synth/cluster/` returned 0 files |
| `posts.theme_centroid` NOT written by Phase 5 | CONFIRMED — `theme_centroid` only appears in `db/models.py` (Phase 2 column def) and `db/posts.py` (Phase 2 helper never called from `cluster/` or `scheduler.py`). Phase 7 will write it. |
| `pending|posted|failed|dry_run` status set by Phase 5 | CONFIRMED not set — no writes to `posts.status` from Phase 5 code; Phase 5 only READS past posts via `get_recent_posts_with_source_texts` |

---

## Phase 1–4 Baseline Preservation

| Metric | Baseline (Phase 4) | After Phase 5 | Delta |
|--------|--------------------|--------------|-------|
| Unit tests | 161 | 226 | +65 (Plan 05-01: 60; Plan 05-02: 5) |
| Integration tests (operator-verified in compose) | 39 | 61 | +22 (Plan 05-02) |
| Ruff | clean | clean | no regression |

The Phase 4 scheduler test `test_run_cycle_calls_run_ingest_with_counts` was updated (not duplicated) to mock `run_clustering` with an empty `counts_patch` — preserving its Phase 4 focus and avoiding double-testing Phase 5 semantics.

---

## Operator Sign-Off — Compose Smoke

**Status:** partial-with-acceptance (7/8 green; step 7 inconclusive for an orthogonal reason).

Operator-observed Phase 5 specifics (all green):
- Cycle `01KP5PB1ZXFKWKSM4KEG8QX5AV` ran end-to-end through `run_ingest → run_clustering → finish_cycle`.
- `articles_in_window=14`, `cluster_count=0`, `singleton_count=14`, `chosen_cluster_id=null`, `fallback_used=true`, `fallback_article_id=1` (correct fallback behavior on a 14-singleton day).
- `clusters` table: 14 candidates, 0 chosen (correct per D-12: fallback path leaves every row `chosen=False`).
- Exactly-one-winner invariant query: 0 rows.
- Determinism loop 3× identical (4 passed, 1.17s each run).

Step 7 (kill-switch-via-restart-with-marker) was inconclusive because `docker compose restart app` stopped emitting logs after `alembic_upgrade_start`. No `cycle_start` / `cycle_skipped` events were observed, so the operator could not visually confirm the PAUSED path fired. This is recorded below as a Phase 8 follow-up, NOT a Phase 5 defect, because:

1. The Phase 5 unit test `tests/unit/test_scheduler.py::test_paused_cycle_skips_run_clustering` independently proves `run_clustering` is not invoked when PAUSED is set.
2. INFRA-09 kill-switch was already operator-approved in Phase 1's compose smoke.
3. Phase 5 inserts `run_clustering` AFTER the PAUSED gate — it does not modify the gate.

---

## Follow-ups for Phase 8 Investigation

**1. `docker compose restart` log-stream observability gap**

- **Symptom:** After `docker compose restart app`, log output stops at `alembic_upgrade_start`. No subsequent `cycle_start`, `cycle_skipped`, or `cycle_end` events are visible via `docker compose logs -f app`.
- **Classification:** Phase 1/2 boot-sequence observability issue (likely a stdout buffering or re-attach glitch on restart; logs may still be reaching the volume file but not the follower).
- **Why not a Phase 5 defect:** Phase 5 does not touch the boot sequence, alembic wiring, or the PAUSED gate — it only appends `run_clustering` after those steps.
- **Recommended Phase 8 actions:**
  - Reproduce on a fresh restart with `docker compose logs --tail=1000 app` (not `-f`) to determine whether the events are written but not streamed vs. never written.
  - Verify log file on the `logs` volume (`/data/logs/*.jsonl`) captures the missing `cycle_skipped` event during PAUSED restarts.
  - Consider adding a `boot_complete` structured event + explicit stdout flush before APScheduler enters its blocking loop.
  - Add an OPS-level CLI (Phase 8 OPS-04 neighborhood) that tails the file-based log instead of stdout for live debugging, to insulate the operator workflow from Docker log-stream quirks.

---

## Gaps Summary

**None.** All 5 ROADMAP success criteria verified, all 7 CLUSTER-0* requirements satisfied, all 15 CONTEXT decisions honored, P-1 fix codified and tested, full unit + integration suites green, ruff clean, operator-verified live behavior confirms the fallback path on a real 14-singleton day.

Phase 5 is ready for Phase 6 (Synthesis). `SelectionResult` is the stable input contract.

---

*Verified: 2026-04-12*
*Verifier: Claude (gsd-verifier)*
