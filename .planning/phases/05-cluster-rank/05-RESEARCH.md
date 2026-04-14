# Phase 5: Cluster + Rank - Research

**Researched:** 2026-04-13
**Domain:** TF-IDF char n-gram clustering + agglomerative grouping + centroid-based anti-repetition (sklearn 1.8, pydantic v2, SA 2.0)
**Confidence:** HIGH — all sklearn APIs verified against 1.8.0 official docs; one critical sklearn behavioral pitfall discovered (see §Common Pitfalls P-1).

## Summary

Phase 5 is a deterministic pure-core module plugged between `run_ingest` and `finish_cycle`. sklearn 1.8's `AgglomerativeClustering` and `TfidfVectorizer` APIs are stable and directly support the CONTEXT-locked approach; the only open gap is a **sklearn behavioral caveat**: `stop_words` is silently **ignored** when `analyzer='char_wb'` — CONTEXT D-08 must be implemented by stripping stopwords at the preprocessor stage (or abandoning them entirely for char-ngrams, which is defensible at N<200 docs). This is the single most important finding; the planner needs to decide the approach in Wave 0.

Beyond that, the phase is a straight-line implementation: sort articles deterministically → fit TF-IDF once per cycle on the combined (current-cycle + 48h-history) corpus → cluster current cycle → rank candidates → re-use the same fit vectorizer to compute past-post centroids for anti-repeat → persist audit trail → return a frozen `SelectionResult`.

**Primary recommendation:** Implement `PT_EN_STOPWORDS` as a **preprocessor-level strip** (regex or word-split + filter before passing text to `TfidfVectorizer`) — do NOT rely on the vectorizer's `stop_words` parameter with char_wb. Drop `stop_words=` from the vectorizer construction to avoid silent false-confidence; document the rationale in a module docstring.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Anti-Repetition Centroid Strategy**
- **D-01:** Re-fit TF-IDF on combined corpus at anti-repeat check time. Every cycle the TF-IDF vocabulary is ephemeral. Build fresh vocabulary over `{current_cycle_articles} ∪ {last_48h_posts_source_texts}`. Re-vectorize both sides, cosine(winning_cluster_centroid, each_past_post_centroid). `posts.theme_centroid` BYTEA (Phase 2 D-07) is a DEBUG SNAPSHOT only, not the live anti-repeat vector.
- **D-02:** No `posts` schema change. Reuse `posts.cluster_id FK → clusters.member_article_ids → articles`. Add `tech_news_synth.db.posts.get_recent_posts_with_source_texts(session, within_hours=48)`.
- **D-03:** `ANTI_REPEAT_COSINE_THRESHOLD: float = 0.5` in Settings, env-configurable.

**Source Weights**
- **D-04:** Add `weight: float = 1.0` field to sources.yaml per-source entry. Extend `RssSource`/`HnFirebaseSource`/`RedditJsonSource`. Default 1.0 preserves backward compatibility.
- **D-05:** All v1 sources ship with `weight: 1.0`. Operator tunes post-observation.

**Clustering Algorithm**
- **D-06:** `sklearn.cluster.AgglomerativeClustering(metric="cosine", linkage="average", distance_threshold=0.35, n_clusters=None)`. Deterministic on fixed input order.
- **D-07:** Singletons excluded from winner selection but PERSISTED to `clusters` with `chosen=False`.
- **D-08:** Input representation: concat `(title + " " + summary)` → `unidecode(text)` → `TfidfVectorizer(analyzer="char_wb", ngram_range=(3,5), stop_words=PT_EN_STOPWORDS, lowercase=True, min_df=1)`. PT_EN_STOPWORDS = sklearn's `ENGLISH_STOP_WORDS` ∪ curated ~80-word PT-BR list.

**Winner Selection & Fallback**
- **D-09:** Rank key `(-source_count, -most_recent_ts.timestamp(), -weight_sum)`. Python stable sort preserves insertion order for ties. Walk sorted candidates; first non-repeat wins.
- **D-10:** Articles sorted `(published_at ASC, id ASC)` BEFORE vectorization for deterministic labels.
- **D-11:** Fallback: article with highest `source.weight`, tiebreak most recent `published_at`, tiebreak2 lowest `article.id`.

**Audit Trail**
- **D-12:** ALL candidate clusters (including singletons) persisted with `chosen=False` initially; UPDATE winner to `chosen=True`. Rejected-by-anti-repeat stay `chosen=False`.
- **D-13:** `run_log.counts` extends Phase 4's schema with `articles_in_window`, `cluster_count`, `singleton_count`, `chosen_cluster_id`, `rejected_by_antirepeat`, `fallback_used`, `fallback_article_id`.

**Integration**
- **D-14:** `run_cycle` flow: `start_cycle → run_ingest → run_clustering(session, cycle_id, settings, sources_config) → finish_cycle`. `run_clustering` returns `SelectionResult` (fields: `winner_cluster_id`, `winner_article_ids`, `fallback_article_id`, `rejected_by_antirepeat`, `all_cluster_ids`, `counts_patch`).
- **D-15:** 4 new Settings fields: `cluster_window_hours: int = 6`, `cluster_distance_threshold: float = 0.35`, `anti_repeat_cosine_threshold: float = 0.5`, `anti_repeat_window_hours: int = 48`.

### Claude's Discretion

- `SelectionResult` shape (recommend pydantic v2 frozen BaseModel for consistency with `ArticleRow` pattern).
- Module layout: recommended `src/tech_news_synth/cluster/{__init__,vectorize,rank,antirepeat,fallback,orchestrator,stopwords_pt}.py` (mirrors Phase 4 `ingest/`).
- Exact PT-BR stopword list contents (Claude picks sensible 50-100 word list).
- `centroid_terms` JSONB shape: `{"term": weight_float, ...}` sorted by weight DESC, top 20.
- Cache the fit TF-IDF vectorizer across anti-repeat check and cluster formation — ONE fit per cycle over combined corpus.

### Deferred Ideas (OUT OF SCOPE)

- Embeddings-based clustering (sentence-transformers / OpenAI / Voyage).
- Source weight auto-tuning.
- Cluster quality monitoring (Silhouette scores).
- Multi-lingual clustering (PT+EN only for v1).
- Centroid caching across cycles.
- pgvector / FAISS.
- Operator thumbs-up/down feedback.
- Semantic dedup at ingest time.
- Time-decay weighting of articles.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CLUSTER-01 | Clustering operates on articles from last `CLUSTER_WINDOW_HOURS` (default 6) across all active sources | §Architecture Patterns — `get_articles_in_window` helper; Settings field D-15 |
| CLUSTER-02 | TF-IDF with char n-grams (3-5), PT+EN stopwords, `unidecode` normalization on `title + " " + summary` | §Code Examples — `build_vectorizer()`; §Pitfalls P-1 stopwords+char_wb caveat |
| CLUSTER-03 | Agglomerative clustering with configurable cosine threshold (default 0.35) producing zero-or-more clusters | §Code Examples — `cluster_articles()`; sklearn 1.8 API verified |
| CLUSTER-04 | Winner selected deterministically: distinct source count → recency → source-weight sum | §Code Examples — `rank_candidates()`; Python stable sort semantics |
| CLUSTER-05 | Anti-repetition filter: cosine ≥ 0.5 against centroids of last 48h posts rejects winner | §Code Examples — `check_antirepeat()`; D-01 combined-corpus refit strategy |
| CLUSTER-06 | Fallback picker: single best-ranked article when no cluster qualifies | §Code Examples — `pick_fallback()` |
| CLUSTER-07 | Cluster-selection audit trail persisted per cycle | §Architecture Patterns — persist-then-update pattern; `insert_cluster` reused |

</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Python 3.12 only**; scikit-learn 1.8, numpy 2, psycopg 3.2, SA 2.0, pydantic 2.9 already pinned.
- **UTC everywhere**: `datetime.now(timezone.utc)`; never naive datetimes. TIMESTAMPTZ in Postgres.
- **Pure-function modules**, composition over classes — matches Phase 1/4 style. The only class-like thing Phase 5 should ship is the pydantic `SelectionResult` model.
- **Secrets via SecretStr**; no concern for Phase 5 (no external API keys).
- **ruff** clean required; tests via pytest with `pytest.mark.integration` gating DB access.
- **GSD workflow enforcement**: all file changes routed through `/gsd-execute-phase`.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| scikit-learn | 1.8.x (pinned `>=1.8,<2`) | `TfidfVectorizer` + `AgglomerativeClustering` + `cosine_similarity` | Already in pyproject. Deterministic, CPU-only, fast on <10k docs. [VERIFIED: scikit-learn.org/stable 1.8.0 docs] |
| numpy | 2.x (pinned `>=2,<3`) | Dense matrix ops, centroid mean, argsort | Required by sklearn 1.8; already pinned. `.toarray()` from sparse TF-IDF output. [VERIFIED: pyproject.toml] |
| unidecode | 1.3.x | ASCII-fold PT accents before vectorization (é → e, ç → c) | Already in pyproject; deterministic. [VERIFIED: pyproject.toml] |
| pydantic | 2.9.x | `SelectionResult` frozen model + extending `SourcesConfig` with `weight` field | Matches project pattern. [VERIFIED: pyproject.toml] |
| SQLAlchemy | 2.0.x | Core + ORM queries for `get_articles_in_window`, `get_recent_posts_with_source_texts`, cluster upserts | Already pinned; Phase 2 established patterns. [VERIFIED: pyproject.toml] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| scipy (transitive via sklearn) | 1.13+ | Sparse matrix → `.toarray()` conversion | Silently pulled by sklearn 1.8. Don't import directly; use sklearn's return types. [CITED: sklearn 1.8 version compat matrix] |
| structlog | 25.x | Per-stage log lines (cluster_start, cluster_end, antirepeat_rejected, fallback_used) | Already in project; inherit `cycle_id` contextvar. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `AgglomerativeClustering(metric='cosine')` | `DBSCAN(metric='cosine', eps=0.35)` | DBSCAN yields noise points (label=-1) directly — cleaner singleton semantics, but harder to reason about `eps` vs agglomerative's linkage distance. CONTEXT D-06 already locked agglomerative. [ASSUMED] |
| `char_wb` analyzer | `char` analyzer + explicit word-boundary padding | `char_wb` pads with spaces at word boundaries automatically. `char` is slightly noisier. CONTEXT D-08 locks `char_wb`. [VERIFIED: sklearn docs] |
| Re-fit TF-IDF on combined corpus | Persist `posts.theme_centroid` bytes and load them | Persisting would require Phase 7 writing centroid in the SAME vocabulary we use later — but vocabulary shifts each cycle. Re-fit solves vocabulary mismatch. CONTEXT D-01 locks re-fit. [VERIFIED: sklearn TfidfVectorizer vocab_ documentation] |

**Installation:** No new dependencies. Everything pinned in `pyproject.toml` already.

**Version verification:**
```bash
uv run python -c "import sklearn; print(sklearn.__version__)"  # expect 1.8.x
uv run python -c "import unidecode; print(unidecode.__version__)"  # expect 1.3.x
```

## Architecture Patterns

### Recommended Project Structure

```
src/tech_news_synth/
├── cluster/                    # NEW — mirrors ingest/ layout from Phase 4
│   ├── __init__.py
│   ├── stopwords_pt.py        # frozenset of ~80 PT-BR stopwords
│   ├── preprocess.py          # unidecode + stopword strip (see Pitfall P-1)
│   ├── vectorize.py           # build_vectorizer, fit_combined_corpus
│   ├── cluster.py             # run_agglomerative → labels_, centroids
│   ├── rank.py                # rank_candidates + SelectionResult model
│   ├── antirepeat.py          # check_antirepeat (consumes fit vectorizer)
│   ├── fallback.py            # pick_fallback (article-level)
│   └── orchestrator.py        # run_clustering (called by scheduler)
├── db/
│   ├── articles.py            # ADD: get_articles_in_window(session, hours)
│   ├── clusters.py            # ADD: update_chosen(session, cluster_id, True)
│   └── posts.py               # ADD: get_recent_posts_with_source_texts(session, hours)
├── ingest/
│   └── sources_config.py      # MODIFY: add weight: float = 1.0 to _SourceBase
├── config.py                  # ADD 4 new Settings fields (D-15)
└── scheduler.py               # MODIFY run_cycle to call run_clustering
```

### Pattern 1: Pure core / imperative shell

**What:** `cluster/` modules are pure: in = data (list[Article], list[PostWithTexts], source_weights), out = data (labels, centroids, SelectionResult). DB I/O lives ONLY in `db/` helpers and `orchestrator.py` glue.

**When to use:** Default project-wide pattern; Phase 4 followed it.

**Example:**
```python
# cluster/cluster.py — pure
def run_agglomerative(
    X_dense: np.ndarray,  # shape (n_articles, n_features)
    distance_threshold: float,
) -> np.ndarray:  # shape (n_articles,) int labels
    model = AgglomerativeClustering(
        metric="cosine",
        linkage="average",
        distance_threshold=distance_threshold,
        n_clusters=None,
    )
    model.fit(X_dense)
    return model.labels_
```

### Pattern 2: ONE fit per cycle over combined corpus

**What:** Fit a single `TfidfVectorizer` on `[*current_cycle_texts, *past_post_source_texts]`. Reuse the same vectorizer (never re-fit) for:
1. Computing cluster centroids (mean of rows belonging to a label in the current-cycle slice).
2. Computing past-post centroids (mean of rows belonging to each past post in the history slice).

**Why:** Guarantees the two vectors live in the same feature space — the whole point of D-01.

**Bookkeeping:** Track the slice boundary: `current_cycle_range = (0, N_current)`, each past post has `(start, end)` indices in the combined matrix.

### Pattern 3: Persist-then-update for cluster audit

**What:** Flow:
1. INSERT all candidate clusters (multi-member and singletons) with `chosen=False`.
2. SELECT/rank candidates → walk anti-repeat filter → identify winner.
3. UPDATE winner's row to `chosen=True`.
4. Rejected clusters stay `chosen=False`; fallback case leaves NO cluster chosen.

This matches CONTEXT D-12 and keeps the audit trail queryable via `SELECT * FROM clusters WHERE cycle_id=? ORDER BY created_at`.

### Anti-Patterns to Avoid

- **Re-fitting TF-IDF separately for cluster phase and anti-repeat phase** — vocabularies diverge, cosines become meaningless. Fit ONCE over combined corpus.
- **Using `stop_words=` with `analyzer='char_wb'`** — silently ignored by sklearn. See Pitfall P-1.
- **Passing a scipy sparse matrix to `AgglomerativeClustering.fit()`** — must `.toarray()` first. See Pitfall P-2.
- **Randomizing article order before clustering** — breaks determinism (SC-2). Always sort `(published_at ASC, id ASC)`.
- **Writing `posts.theme_centroid` from Phase 5** — Phase 5 only READS centroids via re-fit. Phase 7 writes the debug snapshot.
- **Using `MAX_DF` default of 1.0 at N=60-200** — fine here because no single char-ngram dominates. But at N=10 a ngram might appear in every doc. With `min_df=1` and small N, keep `max_df=1.0` default.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| TF-IDF weighting | Custom IDF calculator | `sklearn.feature_extraction.text.TfidfVectorizer` | Handles smoothing, sublinear_tf, norm, vocab bookkeeping. Edge cases (single-char tokens, empty docs) are solved. |
| Agglomerative clustering | Custom pairwise linkage loop | `sklearn.cluster.AgglomerativeClustering(distance_threshold=...)` | O(n²) done right; determinism guaranteed. |
| Cosine similarity | `np.dot(a,b) / (np.linalg.norm(a)*np.linalg.norm(b))` | `sklearn.metrics.pairwise.cosine_similarity` | Handles zero-vectors, broadcasts over matrices, faster with BLAS. |
| ASCII-folding PT | Custom regex strip of combining chars | `unidecode` | Already pinned; handles edge cases (ñ, à, ç, emoji-in-title). |
| PT stopword list | Writing from scratch | Ship curated seed from CONTEXT `<specifics>` | Seed provided; operator tunes later. |
| Stable sort for deterministic tiebreak | Custom comparator with hashed tiebreaks | Python's built-in `list.sort(key=...)` on tuple | CPython's Timsort is stable by spec. |

**Key insight:** Every piece of the pipeline is a one-liner built on sklearn/numpy/stdlib. The phase's actual complexity is the *integration*: slice bookkeeping in combined corpus, persist-then-update for audit, and deterministic input ordering.

## Runtime State Inventory

**SKIPPED — this is a greenfield phase adding new tables/modules; no existing runtime state to rename or migrate.** The only persistent mutation Phase 5 produces is rows in `clusters` (Phase 2 table, already created); no schema changes; no external services hold state.

## Common Pitfalls

### P-1 (CRITICAL): `stop_words` is silently IGNORED when `analyzer='char_wb'`

**What goes wrong:** CONTEXT D-08 specifies `TfidfVectorizer(analyzer="char_wb", ngram_range=(3,5), stop_words=PT_EN_STOPWORDS, ...)`. sklearn's `TfidfVectorizer` only applies `stop_words` when `analyzer='word'`. With `char_wb`, the stopword list is **ignored entirely** and **no warning is raised** in sklearn 1.8.

**Why it happens:** `stop_words` filters *word tokens*; char_wb produces *character n-grams within word boundaries*. There's no word-token layer to filter against, so sklearn drops the parameter silently. [VERIFIED: sklearn TfidfVectorizer docs + GitHub issue #22196 + sklearn source]

**How to avoid — pick ONE of three approaches (decision needed in Wave 0):**

**Option A (recommended):** Strip stopwords in a preprocessor function before text hits the vectorizer.
```python
# cluster/preprocess.py
import re
from tech_news_synth.cluster.stopwords_pt import PT_EN_STOPWORDS
from unidecode import unidecode

_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)

def preprocess(text: str) -> str:
    """Lowercase → unidecode → strip stopword tokens → rejoin with spaces."""
    folded = unidecode(text).lower()
    tokens = _WORD_RE.findall(folded)
    kept = [t for t in tokens if t not in PT_EN_STOPWORDS]
    return " ".join(kept)
```
Then pass preprocessed strings to the vectorizer. `char_wb` will generate n-grams only from the retained words. Stopword "de" becomes no n-grams; meaningful words contribute their char-ngrams normally.

**Option B:** Pass `preprocessor=preprocess` as an argument to `TfidfVectorizer(preprocessor=preprocess, analyzer='char_wb', ...)`. Semantically identical; sklearn calls the hook before analyzer.

**Option C:** Skip stopwords entirely. At char_wb with ngram (3,5), stopwords like "de" contribute only 2 n-grams ("de ", " de") vs meaningful words contributing many. IDF downweights them naturally. At N=60-200 docs this is defensible.

**Recommendation:** Option A or B. Explicitness > relying on IDF. Document the CONTEXT-vs-reality gap in the module docstring: "NOTE: CONTEXT D-08 specified stop_words= on the vectorizer; sklearn silently ignores this with char_wb, so we strip stopwords in the preprocessor. Net behavior matches D-08 intent."

**Warning signs:** Cluster labels separate articles that should merge because stopword-heavy titles ("Apple anuncia o novo iPhone") share stopword char-ngrams with unrelated headlines.

### P-2: `AgglomerativeClustering.fit()` wants dense, not sparse

**What goes wrong:** `TfidfVectorizer.fit_transform()` returns `scipy.sparse.csr_matrix`. Passing that directly to `AgglomerativeClustering.fit(X_sparse)` raises `TypeError: A sparse matrix was passed, but dense data is required. Use X.toarray() to convert to a dense numpy array.`

**Why it happens:** Agglomerative computes a full distance matrix; requires dense arrays. sklearn does not auto-densify.

**How to avoid:** `X_dense = X_sparse.toarray()` before `model.fit(X_dense)`. At N=200 × ~5000 features × 8 bytes = ~8MB dense — trivial. [VERIFIED: sklearn 1.8 AgglomerativeClustering docs §X parameter]

### P-3: `n_clusters=None` REQUIRES `distance_threshold` (and vice versa)

**What goes wrong:** Forgetting one of the pair raises at fit time: `ValueError: n_clusters must be None if distance_threshold is not None`.

**How to avoid:** Always pass both explicitly: `AgglomerativeClustering(metric="cosine", linkage="average", distance_threshold=settings.cluster_distance_threshold, n_clusters=None)`. [VERIFIED: sklearn docs]

### P-4: Empty cycle window → sklearn fit fails on zero samples

**What goes wrong:** `get_articles_in_window(hours=6)` returns []. Vectorizer.fit([]) raises `ValueError: empty vocabulary`.

**How to avoid:** Short-circuit in orchestrator:
```python
if not current_articles:
    return SelectionResult(
        winner_cluster_id=None, winner_article_ids=None,
        fallback_article_id=None, rejected_by_antirepeat=[],
        all_cluster_ids=[],
        counts_patch={"articles_in_window": 0, "cluster_count": 0, "singleton_count": 0,
                      "chosen_cluster_id": None, "rejected_by_antirepeat": [],
                      "fallback_used": False, "fallback_article_id": None},
    )
```
Single article also short-circuits to fallback (no clustering possible).

### P-5: Deterministic tiebreak depends on stable input order

**What goes wrong:** Two runs on same fixture produce different `winner_cluster_id` because input article order differs (DB ordering is not guaranteed without ORDER BY).

**How to avoid:** `get_articles_in_window` MUST apply `ORDER BY published_at ASC, id ASC`. Document as a contract in the helper's docstring. Assert in an integration test that two runs return identical `SelectionResult`.

### P-6: Combined-corpus slice bookkeeping errors

**What goes wrong:** Compute past-post centroid using wrong row slice of the combined matrix → cosine comparisons are meaningless. Subtle bug — won't crash, just returns wrong winners.

**How to avoid:** Explicit ranges dataclass:
```python
@dataclass(frozen=True)
class CorpusSlices:
    current_range: tuple[int, int]  # [0, N_current)
    past_post_ranges: dict[int, tuple[int, int]]  # post_id -> [start, end)
```
Assert invariants in a unit test: `sum(end-start for (s,e) in ranges) == X.shape[0]`.

### P-7: `unidecode` on emoji/CJK silently empties the string

**What goes wrong:** Title = "🚀 Rocket launches", `unidecode("🚀 Rocket launches")` = " Rocket launches" (emoji → empty). Short titles that are all-emoji → empty string → empty feature vector → all-zero cosine.

**How to avoid:** `unidecode` returns "" for unmappable chars — this is fine for emoji (they carry no clustering signal in PT). But guard against articles where `preprocess(title + " " + summary) == ""` post-stopword-strip. Drop such articles from the window (log warning). Unit test with emoji-only title.

### P-8: `AgglomerativeClustering` with N=1 raises

**What goes wrong:** At N=1 in the current cycle, `model.fit(X)` raises ValueError (can't cluster a single point with distance_threshold + n_clusters=None). [ASSUMED — verify in Wave 0 test]

**How to avoid:** Short-circuit N<2 to the fallback path before calling `fit`.

### P-9: `posts.status='posted'` filter is critical for anti-repeat

**What goes wrong:** Including `pending`/`failed`/`dry_run` posts in the history corpus means we compare against tweets that never went live. Legitimate reposts get blocked.

**How to avoid:** `get_recent_posts_with_source_texts` MUST filter `posts.status = 'posted' AND posts.posted_at IS NOT NULL AND posts.posted_at > NOW() - INTERVAL ':hours hours'`. Document in helper docstring.

### P-10: Float comparison for `coverage_score` DB roundtrip

**What goes wrong:** Persisting `coverage_score = float(source_count)` then reading back — float vs int semantic drift. Existing `Cluster.coverage_score: Mapped[float | None]` accepts either.

**How to avoid:** Store `float(distinct_source_count)` consistently. Test reads back as float.

## Code Examples

Verified against sklearn 1.8 API.

### Build the vectorizer (with Option A preprocessor)

```python
# cluster/vectorize.py
from sklearn.feature_extraction.text import TfidfVectorizer
from tech_news_synth.cluster.preprocess import preprocess

def build_vectorizer(min_df: int = 1) -> TfidfVectorizer:
    """NOTE: CONTEXT D-08 specified stop_words= on the vectorizer; sklearn
    silently ignores this with analyzer='char_wb' (see RESEARCH P-1). We strip
    stopwords in preprocess() before feeding text, so net behavior matches intent.
    """
    return TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(3, 5),
        lowercase=True,        # redundant since preprocess() lowercases, but harmless
        min_df=min_df,
        preprocessor=preprocess,  # Option B — call our stopword-strip per doc
    )
```

### Fit combined corpus + track slices

```python
# cluster/vectorize.py
import numpy as np
from dataclasses import dataclass

@dataclass(frozen=True)
class FittedCorpus:
    vectorizer: TfidfVectorizer
    X: np.ndarray                             # dense, shape (N_total, N_features)
    current_range: tuple[int, int]            # [0, N_current)
    past_post_ranges: dict[int, tuple[int, int]]  # post_id -> [start, end)

def fit_combined_corpus(
    current_texts: list[str],
    past_posts: list["PostWithTexts"],  # each with .post_id, .source_texts: list[str]
) -> FittedCorpus:
    corpus: list[str] = list(current_texts)
    past_ranges: dict[int, tuple[int, int]] = {}
    for p in past_posts:
        start = len(corpus)
        corpus.extend(p.source_texts)
        past_ranges[p.post_id] = (start, len(corpus))
    vec = build_vectorizer()
    X_sparse = vec.fit_transform(corpus)
    X = X_sparse.toarray()  # P-2: densify for agglomerative
    return FittedCorpus(vec, X, (0, len(current_texts)), past_ranges)
```

### Run clustering + extract centroids

```python
# cluster/cluster.py
import numpy as np
from sklearn.cluster import AgglomerativeClustering

def run_agglomerative(X_current: np.ndarray, distance_threshold: float) -> np.ndarray:
    """Return integer label per row. P-3: n_clusters=None + distance_threshold required."""
    if X_current.shape[0] < 2:
        # P-8: agglomerative can't fit N<2; caller should fallback.
        return np.zeros(X_current.shape[0], dtype=int)
    model = AgglomerativeClustering(
        metric="cosine",
        linkage="average",
        distance_threshold=distance_threshold,
        n_clusters=None,
    )
    model.fit(X_current)
    return model.labels_

def compute_centroid(X: np.ndarray, row_indices: list[int]) -> np.ndarray:
    """Mean of rows → 1D ndarray shape (N_features,)."""
    return X[row_indices].mean(axis=0)
```

### Extract top-K centroid terms for JSONB

```python
# cluster/vectorize.py
def top_k_terms(centroid: np.ndarray, vectorizer: TfidfVectorizer, k: int = 20) -> dict[str, float]:
    """Return {term: weight} sorted by weight DESC, top-k."""
    feature_names = vectorizer.get_feature_names_out()  # ndarray of str
    top_idx = np.argsort(centroid)[::-1][:k]
    return {str(feature_names[i]): float(centroid[i]) for i in top_idx if centroid[i] > 0}
```

### Anti-repeat check

```python
# cluster/antirepeat.py
from sklearn.metrics.pairwise import cosine_similarity

def check_antirepeat(
    winning_centroid: np.ndarray,                   # shape (N_features,)
    fitted: FittedCorpus,
    past_posts: list[PostWithTexts],
    threshold: float,
) -> list[int]:
    """Return list of past post_ids whose centroid cosine >= threshold."""
    rejects: list[int] = []
    winner_2d = winning_centroid.reshape(1, -1)
    for p in past_posts:
        start, end = fitted.past_post_ranges[p.post_id]
        past_centroid = fitted.X[start:end].mean(axis=0).reshape(1, -1)
        sim = float(cosine_similarity(winner_2d, past_centroid)[0, 0])
        if sim >= threshold:
            rejects.append(p.post_id)
    return rejects
```

### Rank candidates + walk through anti-repeat

```python
# cluster/rank.py
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class ClusterCandidate:
    cluster_db_id: int              # row id after INSERT with chosen=False
    member_article_ids: list[int]
    source_count: int
    most_recent_ts: datetime
    weight_sum: float
    centroid: np.ndarray

def rank_candidates(candidates: list[ClusterCandidate]) -> list[ClusterCandidate]:
    """D-09 rank key; stable sort preserves insertion order for ties."""
    return sorted(
        candidates,
        key=lambda c: (-c.source_count, -c.most_recent_ts.timestamp(), -c.weight_sum),
    )
```

### Fallback article picker

```python
# cluster/fallback.py
def pick_fallback(
    articles: list[Article],
    source_weights: dict[str, float],
) -> int | None:
    if not articles:
        return None
    chosen = min(
        articles,
        key=lambda a: (
            -source_weights.get(a.source, 1.0),
            -(a.published_at.timestamp() if a.published_at else 0.0),
            a.id,
        ),
    )
    return chosen.id
```

### SelectionResult pydantic model

```python
# cluster/rank.py
from pydantic import BaseModel, ConfigDict

class SelectionResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    winner_cluster_id: int | None
    winner_article_ids: list[int] | None
    fallback_article_id: int | None
    rejected_by_antirepeat: list[int]  # cluster DB ids
    all_cluster_ids: list[int]
    counts_patch: dict[str, object]  # JSON-serializable
```

### `get_articles_in_window` helper

```python
# db/articles.py (addition)
from datetime import UTC, datetime, timedelta
from sqlalchemy import select

def get_articles_in_window(session: Session, hours: int) -> list[Article]:
    """Articles with published_at >= now() - hours, sorted deterministically.

    Sort (published_at ASC, id ASC) is required for reproducible cluster labels (P-5).
    """
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    return list(session.execute(
        select(Article)
        .where(Article.published_at >= cutoff)
        .order_by(Article.published_at.asc(), Article.id.asc())
    ).scalars())
```

### `get_recent_posts_with_source_texts` helper

```python
# db/posts.py (addition)
from dataclasses import dataclass
from sqlalchemy import select
from tech_news_synth.db.models import Article, Cluster, Post

@dataclass(frozen=True)
class PostWithTexts:
    post_id: int
    source_texts: list[str]  # each = f"{title} {summary or ''}"

def get_recent_posts_with_source_texts(
    session: Session, within_hours: int
) -> list[PostWithTexts]:
    """Posts with status='posted' in last `within_hours`, each with its
    cluster's member article texts. P-9: status filter is critical."""
    cutoff = datetime.now(UTC) - timedelta(hours=within_hours)
    # SA 2.0 ORM approach — simpler than UNNEST-heavy Core query.
    rows = session.execute(
        select(Post.id, Cluster.member_article_ids)
        .join(Cluster, Cluster.id == Post.cluster_id)
        .where(
            Post.status == "posted",
            Post.posted_at.is_not(None),
            Post.posted_at >= cutoff,
        )
    ).all()
    out: list[PostWithTexts] = []
    for post_id, article_ids in rows:
        articles = list(session.execute(
            select(Article.title, Article.summary)
            .where(Article.id.in_(article_ids))
            .order_by(Article.id.asc())
        ).all())
        texts = [f"{t} {s or ''}".strip() for (t, s) in articles]
        if texts:  # skip posts whose articles were GC'd
            out.append(PostWithTexts(post_id=post_id, source_texts=texts))
    return out
```

### `update_cluster_chosen` helper

```python
# db/clusters.py (addition)
def update_cluster_chosen(session: Session, cluster_id: int, chosen: bool) -> None:
    cluster = session.execute(
        select(Cluster).where(Cluster.id == cluster_id)
    ).scalar_one()
    cluster.chosen = chosen
    session.flush()
```

### Scheduler wiring (run_cycle extension)

```python
# scheduler.py — inside run_cycle try block
if sources_config is not None:
    http_client = build_http_client()
    ingest_counts = run_ingest(session, sources_config, http_client, settings)
    # Phase 5 — NEW
    selection = run_clustering(session, cycle_id, settings, sources_config)
    counts = {**ingest_counts, **selection.counts_patch}
    session.commit()  # persist cluster audit before finish_cycle
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `AgglomerativeClustering(affinity='cosine', ...)` | `AgglomerativeClustering(metric='cosine', ...)` | sklearn 1.2 | Using `affinity=` in 1.8 raises or warns; must use `metric=`. [VERIFIED: sklearn changelog] |
| `stop_words='english'` with char_wb | Preprocessor-based stopword strip | Always (sklearn never filtered stopwords with non-word analyzers) | Planner must implement Option A/B from P-1; the CONTEXT D-08 spec's vectorizer kwarg is a no-op. [VERIFIED: sklearn issue #22196] |
| Storing centroid bytes and comparing | Re-fit TF-IDF per cycle on combined corpus | CONTEXT D-01 | Vocabulary drift makes persisted centroids meaningless. Re-fit is O(300 docs × 5000 features) ≈ ~200ms. |

**Deprecated/outdated (do NOT use):**
- `affinity=` parameter on AgglomerativeClustering.
- `np.frombuffer` on stored `posts.theme_centroid` for anti-repeat — use the re-fit approach instead. (The byte column stays for Phase 7 debug.)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 60-200 docs × ~5000 char_wb features → ~8MB dense, ~200-500ms fit | §Performance | If wrong, cycle latency bumps from ~1s to 3-5s. Still acceptable at 2h cadence. |
| A2 | Anti-repeat corpus is typically ~300 docs (current cycle + ~25 posts × 4 articles each) | §Performance | Over-estimate raises memory to ~20MB dense. Fine. |
| A3 | sklearn 1.8 `AgglomerativeClustering.fit(X)` on N=1 raises ValueError | P-8 | Unverified in docs; Wave 0 unit test confirms. Mitigation: short-circuit N<2 anyway. |
| A4 | `unidecode` returns "" for emoji/CJK (not raises) | P-7 | Documented behavior; low risk. Unit test with 🚀 covers. |
| A5 | DBSCAN with eps=0.35 would yield comparable clusters to Agglomerative | §Alternatives | Irrelevant — locked to Agglomerative by D-06. Assumption only if we need to revisit. |
| A6 | `scipy.sparse.csr_matrix.toarray()` memory is tractable at this scale | P-2, §Performance | At N=200 × 5000 × 8B = 8MB. Verified math, confident. |
| A7 | CONTEXT D-13's `chosen_cluster_id` in counts is the DB integer id, not a cycle-local index | D-13 interpretation | Assumed integer DB id (consistent with other _id fields). If wrong, planner reads as label int. Low risk — operator readable either way. |
| A8 | Structlog contextvar `cycle_id` bound in `run_cycle` propagates into Phase 5 orchestrator logs automatically | §Architecture | VERIFIED via Phase 4 summary — structlog contextvars are process-wide. |

**Claims needing user confirmation:** A1, A2, A3 (performance + N=1 behavior). If operator wants hard guarantees, Wave 0 benchmarks + unit tests resolve all three.

## Open Questions

1. **Stopwords + char_wb approach (Option A vs B vs C from P-1)**
   - What we know: `stop_words=` is silently ignored; preprocessor-based strip is the fix.
   - What's unclear: Does the planner want explicit strip (A/B) or trust IDF (C)?
   - Recommendation: **Option A (preprocessor function)** — most explicit, matches CONTEXT D-08 intent, testable via unit test on a known "de de de" string.

2. **`SelectionResult.counts_patch` value types**
   - What we know: D-13 schema has mixed types (int, list, bool, int|null).
   - What's unclear: Do we declare `dict[str, object]` (loose) or a pydantic model per field (strict)?
   - Recommendation: Loose `dict[str, object]` for now; tighten in Phase 8 observability if needed. JSON-serializable test as a gate.

3. **Should `run_clustering` commit its own cluster inserts, or delegate to scheduler?**
   - What we know: Phase 2 established "caller owns txn". Phase 4 orchestrator returns counts and lets scheduler commit.
   - What's unclear: Cluster INSERTs need DB ids back to UPDATE `chosen=True`. That's doable within one txn via `session.flush()`.
   - Recommendation: `run_clustering` uses `session.flush()` to obtain cluster ids, does NOT commit. Scheduler commits after merging counts.

4. **Fallback when both current cycle AND anti-repeat reject everything?**
   - What we know: CONTEXT D-11 says fallback article by weight/recency; D-07 excludes singletons from winning.
   - What's unclear: If ALL multi-member clusters are anti-repeat-rejected, does fallback run?
   - Recommendation: **Yes** — fallback is the "always something to publish" guarantee (Core Value). D-11 wording "if no cluster remains" covers both empty-candidate and all-rejected cases.

5. **Weight-sum semantics at equal weights**
   - What we know: D-05 says all v1 sources = 1.0.
   - Observation: `weight_sum = source_count × 1.0 = source_count` → tiebreak 2 degenerates to tiebreak 1. Documented in CONTEXT D-05 as "fine".
   - No action needed; just note in rank.py docstring.

## Environment Availability

**SKIPPED — no external tooling beyond already-pinned deps.** scikit-learn 1.8, unidecode, numpy, pydantic, sqlalchemy are all in `pyproject.toml`. No new OS packages, no services, no CLI utilities.

Verification:
```bash
uv run python -c "import sklearn, numpy, unidecode; print(sklearn.__version__, numpy.__version__, unidecode.__version__)"
```

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-mock + time-machine + respx (existing) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/unit/test_cluster_*.py -q` |
| Full suite command | `uv run pytest tests/unit -q` + `POSTGRES_HOST=$(docker inspect ... ) uv run pytest tests/integration -q -m integration` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| CLUSTER-01 | Window query returns only articles in last N hours, sorted `(published_at ASC, id ASC)` | integration | `pytest tests/integration/test_articles_window.py -x -m integration` | Wave 0 |
| CLUSTER-02 | TF-IDF uses char_wb (3,5); preprocess strips PT+EN stopwords + unidecode | unit | `pytest tests/unit/test_cluster_vectorize.py -x` | Wave 0 |
| CLUSTER-03 | `run_agglomerative` on fixture yields expected labels at distance_threshold=0.35 | unit | `pytest tests/unit/test_cluster_algorithm.py -x` | Wave 0 |
| CLUSTER-04 | `rank_candidates` tiebreaks deterministically on synthetic cluster list | unit | `pytest tests/unit/test_cluster_rank.py -x` | Wave 0 |
| CLUSTER-05 | Anti-repeat rejects cluster whose centroid ≥ 0.5 to 48h post centroid (re-fit corpus) | integration | `pytest tests/integration/test_antirepeat.py -x -m integration` | Wave 0 |
| CLUSTER-06 | Fallback picker returns best article on slow-day fixture (no clusters ≥2 sources) | unit | `pytest tests/unit/test_cluster_fallback.py -x` | Wave 0 |
| CLUSTER-07 | All candidate clusters persisted with chosen flag; winner updated to True | integration | `pytest tests/integration/test_cluster_audit.py -x -m integration` | Wave 0 |
| — | Determinism: same fixture → identical `SelectionResult.winner_cluster_id` across runs | unit | `pytest tests/unit/test_cluster_determinism.py -x` | Wave 0 |
| — | Settings loads 4 new fields with correct defaults + validation | unit | `pytest tests/unit/test_config.py::test_cluster_settings -x` | MODIFY existing |
| — | `SourcesConfig` loads `weight: 1.0` default; explicit weight override works | unit | `pytest tests/unit/test_sources_config.py::test_weight_field -x` | MODIFY existing |
| — | Scheduler `run_cycle` wires `run_clustering` after `run_ingest` | unit | `pytest tests/unit/test_scheduler.py::test_phase5_wiring -x` | MODIFY existing |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/unit/test_cluster_*.py -q` (fast, DB-free).
- **Per wave merge:** Full unit suite + integration suite.
- **Phase gate:** Full suite green before `/gsd-verify-work`.

### Wave 0 Gaps

Files to create (red-stub initially, filled across waves):
- [ ] `tests/unit/test_cluster_preprocess.py` — stopword strip + unidecode + emoji handling
- [ ] `tests/unit/test_cluster_vectorize.py` — `build_vectorizer`, `fit_combined_corpus`, `top_k_terms`, slice bookkeeping invariants
- [ ] `tests/unit/test_cluster_algorithm.py` — `run_agglomerative` with deterministic fixture → expected labels; N<2 short-circuit
- [ ] `tests/unit/test_cluster_rank.py` — `rank_candidates` tuple sort; equal-weight tiebreak; empty candidate list
- [ ] `tests/unit/test_cluster_antirepeat.py` — cosine-matrix math with synthetic centroids
- [ ] `tests/unit/test_cluster_fallback.py` — article weight/recency/id sort
- [ ] `tests/unit/test_cluster_determinism.py` — run twice, same fixtures → same SelectionResult
- [ ] `tests/integration/test_articles_window.py` — `get_articles_in_window` ORDER BY correctness + window cutoff
- [ ] `tests/integration/test_posts_recent.py` — `get_recent_posts_with_source_texts` status filter + text assembly
- [ ] `tests/integration/test_antirepeat.py` — end-to-end: seeded past post → current-cycle duplicate cluster rejected
- [ ] `tests/integration/test_cluster_audit.py` — all clusters INSERTed, winner UPDATE to chosen=True
- [ ] `tests/fixtures/cluster/hot_topic.json` — 12 articles, 3-source winner
- [ ] `tests/fixtures/cluster/slow_day.json` — 6 articles, 6 topics → fallback
- [ ] `tests/fixtures/cluster/anti_repeat_hit.json` — current winner matches 30h-old post

Files to modify:
- `tests/unit/test_config.py` — add test for 4 new Settings fields
- `tests/unit/test_sources_config.py` — add `weight` field test
- `tests/unit/test_scheduler.py` — add Phase 5 wiring test
- `config/sources.yaml` (and `.example`) — DOES NOT need modification (default 1.0 is transparent); but fixtures may set explicit weights for testing

Framework install: none — all deps pinned.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — (internal module, no auth boundaries) |
| V3 Session Management | no | — (re-uses Phase 2 session-per-cycle) |
| V4 Access Control | no | — (operator-only module) |
| V5 Input Validation | yes | pydantic v2 on `SourcesConfig.weight` (`ge=0.0, le=10.0`), Settings numeric bounds |
| V6 Cryptography | no | — (TF-IDF is deterministic numeric, no crypto) |

### Known Threat Patterns for {Python + sklearn + SA 2.0}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| T-05-01: TF-IDF memory exhaustion via unbounded N docs | Denial of Service | Window bounded by `CLUSTER_WINDOW_HOURS` × `max_articles_per_fetch` × source count; ~200 max at v1 scale. No additional guard needed. |
| T-05-02: Pickle-based model artifact ingestion (`joblib.load`) | Tampering / RCE | N/A — sklearn state never persisted; every cycle re-fits from scratch. |
| T-05-03: Malicious article content injection (cluster-bombing via crafted titles) | Tampering | TF-IDF is pure numeric over char n-grams; no eval/template injection path. Pydantic validates article fields upstream in Phase 4. |
| T-05-04: Anti-repeat bypass via paraphrase | Spoofing | Inherent limitation of TF-IDF lexical overlap. Documented in CONTEXT `<deferred>` (embedding-based dedup is v2). Operator monitors via `clusters.centroid_terms` audit. |
| T-05-05: Concurrent cycle race (two agglomerative fits in-flight, both writing clusters) | Tampering (race) | Mitigated by Phase 1 `BlockingScheduler` `max_instances=1` + `coalesce=True`. Single-process PID 1 prevents concurrent `run_cycle`. |
| T-05-06: Source weight range abuse (operator sets `weight: 9999`) | Tampering (config) | Bounded by pydantic `Field(default=1.0, ge=0.0, le=10.0)` in `_SourceBase`. Boot fails on out-of-range. |
| T-05-07: SQL injection via source name / article text in `get_recent_posts_with_source_texts` | Tampering | All queries use SA 2.0 parameterized bind params (`select(...).where(...).in_(...)`); no f-string SQL. |
| T-05-08: Integer overflow in tiebreak timestamps | Tampering | Python int has no overflow; `timestamp()` returns float. No risk. |

**Performance / DoS notes:**
- At 60-200 docs × ~5000 features × 8B = 2.4-8MB dense matrix. Single-digit MB. Safe.
- Anti-repeat corpus: ~300 docs × 5000 features = ~12MB. Safe.
- Agglomerative is O(n² log n); at n=200 it's trivial.

## Sources

### Primary (HIGH confidence)
- [sklearn 1.8 AgglomerativeClustering](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.AgglomerativeClustering.html) — `metric=` (renamed from `affinity=` in 1.2), `n_clusters=None` requires `distance_threshold`, dense input required, `labels_` return type
- [sklearn 1.8 TfidfVectorizer](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html) — `char_wb` vs `char`, `fit_transform` returns scipy sparse, `get_feature_names_out()`, `preprocessor` hook
- [sklearn 1.8 cosine_similarity](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.pairwise.cosine_similarity.html) — matrix cosine, broadcasts over rows
- [pyproject.toml (this repo)](./pyproject.toml) — confirmed pinned versions
- [CONTEXT.md (this phase)](.planning/phases/05-cluster-rank/05-CONTEXT.md) — locked decisions D-01..D-15
- [Phase 2 02-02-SUMMARY.md](.planning/phases/02-storage-layer/02-02-SUMMARY.md) — `insert_cluster`, `get_clusters_for_cycle` contracts
- [Phase 4 04-02-SUMMARY.md](.planning/phases/04-ingestion/04-02-SUMMARY.md) — `run_ingest` / counts schema integration point
- [src/tech_news_synth/db/models.py](./src/tech_news_synth/db/models.py) — verified Cluster/Post/Article shapes

### Secondary (MEDIUM confidence)
- [sklearn GitHub issue #22196 - char_wb + stop_words](https://github.com/scikit-learn/scikit-learn/issues/22196) — confirms stop_words ignored with char_wb analyzer
- [CLAUDE.md + STACK.md](.planning/research/STACK.md) — Python 3.12 + sklearn 1.8 compatibility

### Tertiary (LOW confidence — flagged as [ASSUMED])
- Performance numbers (A1, A2) — order-of-magnitude estimates from doc complexity, not measured. Wave 0 benchmark resolves.
- N=1 agglomerative behavior (A3) — inferred from API requirements; Wave 0 unit test confirms.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all deps pinned, APIs verified against sklearn 1.8 docs
- Architecture: HIGH — mirrors Phase 4 layout; pure-core pattern established
- Pitfalls: HIGH — P-1 (stop_words+char_wb) verified via sklearn docs + issue tracker; others verified against API surface
- Validation: HIGH — test map 1:1 with CLUSTER-01..07

**Research date:** 2026-04-13
**Valid until:** 2026-05-13 (30 days — sklearn 1.8 is stable; no imminent breaking changes expected)
