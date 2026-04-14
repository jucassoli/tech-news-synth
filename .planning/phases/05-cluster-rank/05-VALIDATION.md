---
phase: 05
slug: cluster-rank
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-13
---

# Phase 05 — Validation Strategy

> Per-phase validation contract. Mix of unit (fixture-driven determinism) + integration (live postgres — anti-repeat + audit trail) + scheduler-wiring regression.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (inherits Phase 1-4 config) |
| **Config file** | `pyproject.toml` — no new markers |
| **Quick run command** | `uv run pytest tests/unit/test_cluster_* tests/unit/test_vectorize.py tests/unit/test_antirepeat.py tests/unit/test_fallback.py -q -x --ff` |
| **Full unit** | `uv run pytest tests/unit -q` |
| **Integration** | `uv run pytest tests/integration -q -x -m integration` (needs compose postgres) |
| **Full suite** | `uv run pytest tests/ -v --cov=tech_news_synth --cov-report=term-missing` |
| **Estimated runtime** | ~4s unit, ~12s integration |

---

## Sampling Rate

- **After every task commit:** quick run of cluster-touched tests.
- **After Wave 1 (vectorize + rank + antirepeat + fallback):** full unit suite.
- **After Wave 2 (orchestrator + scheduler wiring):** full unit + integration.
- **Before `/gsd-verify-work`:** full suite green + fixture determinism verified twice (same fixture → identical SelectionResult) + one compose smoke cycle.
- **Max feedback latency:** ~4s unit, ~20s integration.

---

## Per-Requirement Verification Map

| Requirement | Test Type | Automated Command | Wave 0 Dep |
|-------------|-----------|-------------------|------------|
| CLUSTER-01 (6h window, configurable) | unit + integration | `pytest tests/unit/test_cluster_window.py -q` + `pytest tests/integration/test_get_articles_in_window.py -q` | `tests/unit/test_cluster_window.py`, `tests/integration/test_get_articles_in_window.py` |
| CLUSTER-02 (TF-IDF char_wb 3-5 + PT+EN stopwords via PREPROCESSOR + unidecode + title+summary) | unit | `pytest tests/unit/test_vectorize.py -q` (asserts: char_wb analyzer; ngram_range=(3,5); preprocessor strips PT+EN stopwords at word level BEFORE char n-grams; unidecode applied; feature count reasonable; **`stop_words=None` — sklearn ignores it with char_wb, critical bug per research P-1**) | `tests/unit/test_vectorize.py`, `src/tech_news_synth/cluster/stopwords_pt.py` |
| CLUSTER-03 (Agglomerative cosine average dt=0.35; zero-or-more clusters) | unit | `pytest tests/unit/test_cluster_formation.py -q` (fixture: 12 articles 3 topics → 3 clusters; fixture: 6 all different → 6 singletons) | `tests/unit/test_cluster_formation.py`, `tests/fixtures/cluster/{hot_topic,slow_day,mixed}.json` |
| CLUSTER-04 (winner: src_count DESC → recency DESC → weight_sum DESC; singletons excluded; deterministic) | unit | `pytest tests/unit/test_rank.py tests/unit/test_cluster_determinism.py -q` (two runs same fixture → identical winner_cluster_id) | `tests/unit/test_rank.py`, `tests/unit/test_cluster_determinism.py` |
| CLUSTER-05 (anti-repeat cosine ≥ 0.5 vs 48h post centroids; re-fit on combined corpus) | integration | `pytest tests/integration/test_antirepeat.py -q` (seed `posts` row with posted_at 30h ago + its source articles; current cycle forms winner cluster with overlapping text; assert winner rejected + next-best selected) | `tests/integration/test_antirepeat.py`, `src/tech_news_synth/db/posts.py::get_recent_posts_with_source_texts` |
| CLUSTER-06 (fallback: single best article when no cluster valid) | unit | `pytest tests/unit/test_fallback.py -q` (slow_day fixture: all singletons → SelectionResult.winner=None, fallback_article_id set to highest-weight most-recent article) | `tests/unit/test_fallback.py` |
| CLUSTER-07 (all candidates persisted + winner flagged + rejected tracked) | integration | `pytest tests/integration/test_cluster_audit.py -q` (run_clustering writes N clusters rows with chosen=False; after selection, exactly one chosen=True; rejected_by_antirepeat ids captured in run_log.counts) | `tests/integration/test_cluster_audit.py` |

**Cross-cutting — stopword preprocessor (research P-1):** `tests/unit/test_vectorize.py::test_stopwords_stripped_before_char_ngrams` asserts: input `"uma nova API de IA"` with PT stopwords `{"uma", "de"}` → preprocessor output `"nova API IA"` (tokens stripped at word level) → char_wb n-grams built from stripped text. This is the ONLY way to honor CLUSTER-02 stopword requirement with char_wb analyzer.

**Cross-cutting — SelectionResult determinism:** `tests/unit/test_cluster_determinism.py` runs `run_clustering_pure(articles, source_weights, recent_posts_texts)` twice on the same fixture and asserts `result1 == result2` (pydantic frozen models are comparable).

**Cross-cutting — scheduler wiring:** update `tests/unit/test_scheduler.py` — add mock for `run_clustering` returning a canned SelectionResult; assert call ordering `run_ingest → run_clustering → finish_cycle`; assert `counts_patch` merged into `counts` passed to `finish_cycle`.

**Cross-cutting — `weight` field backward compat:** `tests/unit/test_sources_config.py::test_weight_defaults_to_1_0` — yaml without `weight` field loads successfully; every source has `weight == 1.0`.

---

## Wave 0 Requirements

- [ ] `src/tech_news_synth/cluster/` package tree (`__init__.py`, `stopwords_pt.py`, `vectorize.py`, `rank.py`, `antirepeat.py`, `fallback.py`, `orchestrator.py`, `models.py`)
- [ ] `src/tech_news_synth/cluster/stopwords_pt.py` — `PT_STOPWORDS: frozenset[str]` with ~80-100 words seed
- [ ] Fixture files under `tests/fixtures/cluster/`:
  - `hot_topic.json` — 12 articles, 3 topics, 3 sources each (clear 3-member winner)
  - `slow_day.json` — 6 articles all unique topics (all singletons → fallback)
  - `mixed.json` — 10 articles, 1 clear cluster + 4 singletons
  - `anti_repeat_hit.json` — current cycle winner text overlaps a 30h-ago post
  - `tiebreak.json` — 2 clusters same source count → recency tiebreak
- [ ] Red-stub test files for every test listed in the per-requirement table (pytest.skip until code lands)
- [ ] `Settings` extended with 4 new fields (`cluster_window_hours`, `cluster_distance_threshold`, `anti_repeat_cosine_threshold`, `anti_repeat_window_hours`) + `.env.example` + `test_config.py` additions
- [ ] `sources_config.py` extended with `weight: float = Field(default=1.0, ge=0.0, le=10.0)` per-source field + `test_sources_config.py::test_weight_default` case

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real cycle persists candidate clusters with chosen flag | CLUSTER-07 | Needs live postgres + live ingest | After compose smoke on Phase 5 build: `docker compose exec postgres psql -U app -d tech_news_synth -c "SELECT cycle_id, COUNT(*), SUM(CASE WHEN chosen THEN 1 ELSE 0 END) AS chosen FROM clusters GROUP BY cycle_id ORDER BY cycle_id DESC LIMIT 3;"` — each recent cycle shows `COUNT > 0` and `chosen IN (0, 1)` (1 if a winner; 0 if fallback used). |
| Determinism holds on identical fixture data | CLUSTER-04 | Run test twice to prove no RNG leak | `for i in 1 2 3; do uv run pytest tests/unit/test_cluster_determinism.py -q 2>&1 \| tail -3; done` — all 3 runs identical output. |
| Kill-switch still paused clustering | INFRA-09 (carry-over) | Live toggle | `docker compose exec app touch /data/paused` → next cycle logs `cycle_skipped`, `clusters` table unchanged. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` (unit/integration) or `<manual>` verify
- [ ] Stopword preprocessor (research P-1) implemented and tested
- [ ] Determinism test runs green 3× in a row
- [ ] Wave 0 fixtures + stubs created before Wave 1 code
- [ ] Phase 1-4 baseline preserved (161 unit + 38 integration)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
