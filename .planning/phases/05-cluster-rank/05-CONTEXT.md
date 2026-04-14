# Phase 5: Cluster + Rank - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver a deterministic pure-core clustering + ranking module that:
1. Pulls the last `CLUSTER_WINDOW_HOURS` (default 6) of articles from Phase 4's `articles` table.
2. Vectorizes `title + " " + summary` via TF-IDF char n-grams (3-5) with PT+EN stopwords and `unidecode` ASCII-folding.
3. Clusters with `AgglomerativeClustering(metric="cosine", linkage="average", distance_threshold=0.35)`.
4. Ranks multi-member clusters by (distinct_source_count DESC, most_recent_article DESC, source_weight_sum DESC).
5. Anti-repeat: rejects winner whose re-fit-corpus centroid has cosine ≥ `ANTI_REPEAT_COSINE_THRESHOLD` (default 0.5) against any post published within the last 48h; falls through to next-best cluster.
6. Fallback picker: if no cluster remains, pick the single most-recent article from the highest-weight source.
7. Persist audit trail — every candidate cluster written to `clusters` table with `chosen` flag and scores.

Scope includes: `sources.yaml` schema extension (per-source `weight: float = 1.0`); pure-function `cluster.py` module; anti-repeat helper (re-fits TF-IDF on combined corpus); integration into `run_cycle` between `run_ingest` and `finish_cycle`; `SelectionResult` dataclass returned for Phase 6 (synthesis) consumption. Out of scope: synthesis prompting (Phase 6), publish logic (Phase 7), `posts.theme_centroid` population (written by Phase 7 — Phase 5 only CONSUMES centroids via re-fit, never writes them).

</domain>

<decisions>
## Implementation Decisions

### Anti-Repetition Centroid Strategy
- **D-01:** **Re-fit TF-IDF on combined corpus at anti-repeat check time.** Every cycle the TF-IDF vocabulary is ephemeral. To compare the cycle's winning cluster centroid against last-48h posts, fetch the posts' source-article texts (via `posts.cluster_id → clusters.member_article_ids → articles.title + summary`) and build a fresh TF-IDF vocabulary over the union of `{current_cycle_articles} ∪ {last_48h_posts_source_texts}`. Re-vectorize both sides, compute cosine(winning_cluster_centroid, each_past_post_centroid). This resolves the vocabulary-mismatch concern flagged by Phase 2 research.
  - Cost: one extra TF-IDF fit per cycle (~50-200 docs × ~5000 features) ≈ 100-300ms. Acceptable at 2h cadence.
  - `posts.theme_centroid` BYTEA column (Phase 2 D-07) becomes a DEBUG SNAPSHOT of the centroid at synthesis time (Phase 7 still writes it), not the live anti-repeat compare vector.

- **D-02:** **No `posts` schema change.** Reuse existing `posts.cluster_id FK → clusters.member_article_ids → articles`. Add a read helper `tech_news_synth.db.posts.get_recent_posts_with_source_texts(session, within_hours=48) -> list[PostWithTexts]` that performs the JOIN. ~30 posts/48h × 3-5 articles each = trivial join cost.

- **D-03:** **`ANTI_REPEAT_COSINE_THRESHOLD: float = 0.5`** in Settings. Env-configurable. Matches CLUSTER-05. Operator tunes after observing first-week behavior.

### Source Weights (CLUSTER-04 Tiebreak)
- **D-04:** **Add `weight: float = 1.0` field to sources.yaml per-source entry.** Extends Phase 4's `RssSource`/`HnFirebaseSource`/`RedditJsonSource` pydantic models with an optional field (default 1.0 preserves backward compatibility with existing Phase 4 tests and prod yaml). Exposed through existing `sources_config` loaded in `__main__.py`; propagated to `run_clustering` via a `dict[source_name, weight]` derived once per cycle.

- **D-05:** **All v1 sources ship with `weight: 1.0`.** No curated defaults. Operator tunes post-observation (expected 1-2 week lag). With equal weights, tiebreak 2 mathematically reduces to tiebreak 1, which is fine — noisy tiebreaks stay deterministic because of D-10.

### Clustering Algorithm
- **D-06:** **`sklearn.cluster.AgglomerativeClustering(metric="cosine", linkage="average", distance_threshold=0.35, n_clusters=None)`.** Matches CLUSTER-03 verbatim. Deterministic on fixed input order. `distance_threshold=0.35` means distances ≥ 0.35 break clusters apart (equivalent to similarity ≤ 0.65 — articles less similar than that don't cluster together). `linkage="average"` is noise-tolerant vs `"single"` (chaining) and `"complete"` (over-fragmentation).

- **D-07:** **Singletons excluded from winner selection.** A cluster with `member_article_ids.length == 1` is NOT a valid winner candidate (CLUSTER-04 primary = distinct source count; single article = source count 1, never beats multi-source). Singletons are still PERSISTED to `clusters` with `chosen=False` for audit. The fallback picker (CLUSTER-06) handles the "no valid winner" case via a separate article-level rank.

- **D-08:** **Input representation:** concat `(title + " " + summary)` → `unidecode(text)` → `TfidfVectorizer(analyzer="char_wb", ngram_range=(3,5), stop_words=PT_EN_STOPWORDS, lowercase=True, min_df=1)`. `PT_EN_STOPWORDS` is the union of:
  - sklearn's built-in `ENGLISH_STOP_WORDS` (frozenset)
  - A curated PT-BR list of ~80 high-frequency words (shipped as `src/tech_news_synth/cluster/stopwords_pt.py`): `["de", "a", "o", "que", "e", "do", "da", "em", "um", "para", "é", "com", "não", "uma", "os", "no", "se", "na", "por", "mais", "as", "dos", "como", "mas", "foi", "ao", ...]`.

### Winner Selection & Fallback
- **D-09:** **Winner selection algorithm** (pure function):
  ```
  candidates = [c for c in clusters if c.source_count >= 2]   # exclude singletons (D-07)
  rank_key = lambda c: (-c.source_count, -c.most_recent_ts.timestamp(), -c.weight_sum)
  candidates.sort(key=rank_key)   # Python's stable sort preserves insertion order for ties
  for cand in candidates:
      if not _is_repeat(cand, recent_posts, threshold):
          return cand  # winner
  return None  # trigger fallback
  ```

- **D-10:** **Deterministic ordering:** articles are sorted by `(published_at ASC, id ASC)` BEFORE vectorization. Guarantees identical cluster labels across runs on the same data (required by SC-2). Ordering is the deterministic substrate — hash-based tiebreaks fall out of Python's stable sort on tuples.

- **D-11:** **Fallback picker (CLUSTER-06):** if winner selection returns `None` (no eligible cluster OR all rejected by anti-repeat), return the single `Article` with: primary = highest `source.weight`, tiebreak = most recent `published_at`, tiebreak2 = lowest `article.id`. Wrapped in `SelectionResult(winner=None, fallback_article_id=<id>, ...)`.

### Audit Trail (CLUSTER-07)
- **D-12:** **ALL candidate clusters persisted per cycle.** For each cluster formed (including singletons):
  - INSERT a `clusters` row with `cycle_id`, `member_article_ids`, `centroid_terms` (JSONB of top-20 TF-IDF terms by weight — operator-readable), `chosen=False`, `coverage_score=distinct_source_count`.
  - After winner selection + anti-repeat, UPDATE the winning row to `chosen=True`.
  - Rejected-by-anti-repeat clusters stay `chosen=False` with their scores preserved — operator can diff "would have won but for repeat" by querying cluster ordering vs chosen flag.
  - For fallback case, NO `clusters` row is updated to chosen (fallback is an article, not a cluster); the audit signal is `run_log.counts.fallback_used=true`.

- **D-13:** **`run_log.counts` additions (Phase 5 extends Phase 4's schema):**
  ```json
  {
    "articles_fetched": {...},      // Phase 4
    "articles_upserted": N,          // Phase 4
    "sources_ok": N,                 // Phase 4
    "sources_error": N,              // Phase 4
    "sources_skipped_disabled": N,   // Phase 4
    "articles_in_window": N,         // Phase 5 — articles pulled for clustering
    "cluster_count": N,              // Phase 5 — non-singleton candidate count
    "singleton_count": N,            // Phase 5 — audit
    "chosen_cluster_id": <id|null>,  // Phase 5 — null = fallback used
    "rejected_by_antirepeat": [<cluster_id>, ...],
    "fallback_used": bool,
    "fallback_article_id": <id|null>
  }
  ```

### Integration
- **D-14:** **`run_cycle` flow after Phase 5:**
  ```
  start_cycle → run_ingest → run_clustering(session, cycle_id, settings, sources_config) → finish_cycle
  ```
  `run_clustering` returns a `SelectionResult` dataclass (pydantic v2 model or frozen dataclass) with fields: `winner_cluster_id: int | None`, `winner_article_ids: list[int] | None`, `fallback_article_id: int | None`, `rejected_by_antirepeat: list[int]`, `all_cluster_ids: list[int]`, `counts_patch: dict` (the Phase 5 additions to `run_log.counts`). The scheduler merges `counts_patch` into the ingest counts before passing to `finish_cycle`. Phase 6 (synthesis) will later read `SelectionResult` to feed its prompt.

- **D-15:** **Settings additions (2 new fields):**
  - `cluster_window_hours: int = Field(default=6, ge=1, le=72)` — CLUSTER-01
  - `cluster_distance_threshold: float = Field(default=0.35, ge=0.0, le=1.0)` — CLUSTER-03
  - `anti_repeat_cosine_threshold: float = Field(default=0.5, ge=0.0, le=1.0)` — CLUSTER-05
  - `anti_repeat_window_hours: int = Field(default=48, ge=1, le=168)` — CLUSTER-05 48h default
  (4 fields total; update `.env.example` + `tests/unit/test_config.py`.)

### Claude's Discretion
- Exact shape of `SelectionResult` (frozen dataclass vs pydantic BaseModel) — recommend pydantic for consistency with ArticleRow pattern, but either works.
- Module layout: recommended `src/tech_news_synth/cluster/{__init__,vectorize,rank,antirepeat,fallback,orchestrator,stopwords_pt}.py` (mirrors Phase 4's `ingest/` layout).
- Exact PT-BR stopword list contents — Claude picks a sensible 50-100 word list; operator can tune later.
- How `centroid_terms` JSONB is serialized (recommend `{"term": weight_float, ...}` dict sorted by weight DESC, top 20 terms).
- Whether to cache the fit TF-IDF vectorizer across anti-repeat check and cluster formation (YES — fit once per cycle over combined corpus, reuse for both cluster centroid computation and past-post centroid computation; ONE fit per cycle).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project context
- `.planning/PROJECT.md` — clustering rationale, core value
- `.planning/REQUIREMENTS.md` §CLUSTER-01..CLUSTER-07
- `.planning/ROADMAP.md` §"Phase 5: Cluster + Rank"
- `.planning/phases/02-storage-layer/02-CONTEXT.md` (D-07 BYTEA centroid)
- `.planning/phases/02-storage-layer/02-02-SUMMARY.md` (clusters/posts repo interfaces)
- `.planning/phases/04-ingestion/04-CONTEXT.md` (sources.yaml schema — extending it)
- `.planning/phases/04-ingestion/04-02-SUMMARY.md` (Article table fully populated by Phase 4)
- `CLAUDE.md`

### Research outputs
- `.planning/research/STACK.md` — scikit-learn 1.8, unidecode, python-slugify pinned
- `.planning/research/ARCHITECTURE.md` — TF-IDF + cosine rationale
- `.planning/research/PITFALLS.md` — TF-IDF vocabulary ephemerality gotchas

### External specs
- sklearn TfidfVectorizer — https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html
- sklearn AgglomerativeClustering — https://scikit-learn.org/stable/modules/generated/sklearn.cluster.AgglomerativeClustering.html
- sklearn cosine_similarity — https://scikit-learn.org/stable/modules/generated/sklearn.metrics.pairwise.cosine_similarity.html

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (Phases 1-4)
- `tech_news_synth.db.session.SessionLocal` — reuse context-managed sessions.
- `tech_news_synth.db.models.Article, Cluster, Post, RunLog` — SA 2.0 models.
- `tech_news_synth.db.clusters.insert_cluster` + `get_clusters_for_cycle` (Phase 2).
- `tech_news_synth.db.articles` (Phase 2) — add a new `get_articles_in_window(session, hours) -> list[Article]` helper here (Phase 5 extension).
- `tech_news_synth.db.posts` (Phase 2) — add `get_recent_posts_with_source_texts(session, within_hours) -> list[PostWithTexts]` helper here.
- `tech_news_synth.ingest.sources_config.SourcesConfig` (Phase 4) — extend with per-source `weight`.
- `tech_news_synth.logging.get_logger()` — structlog; inherit `cycle_id`.

### Established Patterns
- Pure-function modules; composition over classes (Phase 1 style).
- pydantic v2 at schema boundaries.
- UTC everywhere; `datetime.now(timezone.utc)`.
- Integration tests gated by `pytest.mark.integration` + transactional rollback.
- Deterministic behavior tested via fixtures (e.g., seed 20 fake articles → assert same winner every run).

### Integration Points
- `src/tech_news_synth/scheduler.py::run_cycle` — add `selection = run_clustering(session, cycle_id, settings, sources_config)` between `run_ingest` and `finish_cycle`. Merge `selection.counts_patch` into ingest counts.
- `src/tech_news_synth/__main__.py` — already loads `sources_config`; weight field flows through automatically via pydantic defaults.
- `src/tech_news_synth/ingest/sources_config.py` — add `weight: float = Field(default=1.0, ge=0.0, le=10.0)` to each source variant base class.
- No compose.yaml changes.
- No new external deps — `scikit-learn`, `unidecode` already pinned in Phase 1 baseline.

</code_context>

<specifics>
## Specific Ideas

- PT-BR stopword seed list: `de, a, o, que, e, do, da, em, um, para, é, com, não, uma, os, no, se, na, por, mais, as, dos, como, mas, foi, ao, ele, das, tem, à, seu, sua, ou, ser, quando, muito, há, nos, já, está, eu, também, só, pelo, pela, até, isso, ela, entre, era, depois, sem, mesmo, aos, ter, seus, quem, nas, me, esse, eles, estão, você, tinha, foram, essa, num, nem, suas, meu, às, minha, têm, numa, pelos, elas, havia, seja, qual, será, nós, tenho, lhe, deles, essas, esses, pelas, este, fosse`.
- `centroid_terms` JSONB shape: `{"kube": 0.34, "gpt": 0.28, ...}` (top-20 terms, weights as float). Used by operator inspection only, not anti-repeat math.
- Winning cluster's `centroid_terms` can later feed Phase 6's prompt for topic anchoring.
- Fallback article-level rank: `sort(articles, key=lambda a: (-source_weights.get(a.source, 1.0), -a.published_at.timestamp(), a.id))[0]`.
- Integration test fixture files: `tests/fixtures/cluster/slow_day.json` (6 articles, 6 different topics → no clusters, trigger fallback), `tests/fixtures/cluster/hot_topic.json` (12 articles, 3 on same topic from 3 sources → clear winner), `tests/fixtures/cluster/anti_repeat_hit.json` (current cycle winner matches a post from 30h ago).

</specifics>

<deferred>
## Deferred Ideas

- **Embeddings-based clustering** (sentence-transformers / OpenAI / Voyage) — revisit only if TF-IDF empirically fails on PT-BR tech headlines. 1-2 months of production data needed first.
- **Source weight auto-tuning** — learn from engagement/click-through; premature.
- **Cluster quality monitoring** — Silhouette scores, coherence metrics. Phase 8 observability concern.
- **Multi-lingual clustering** — PT+EN only for v1 (CLAUDE.md scope).
- **Centroid caching across cycles** — every cycle re-fits; no memoization needed at this volume.
- **pgvector / FAISS** — not justified at ~30 rows/48h.
- **Active cluster-quality feedback** (operator thumbs-up/down) — no UI in v1.
- **Semantic dedup at ingest time** — Phase 4 only deduplicates on canonical URL; semantic dedup is Phase 5's scope.
- **Time-decay weighting of articles** — simpler to trust 6h window cutoff.

</deferred>

---

*Phase: 05-cluster-rank*
*Context gathered: 2026-04-13 via /gsd-discuss-phase*
