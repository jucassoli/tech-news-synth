"""Phase 5 orchestrator — ``run_clustering`` (D-14).

Flow:
  1. Load articles in ``CLUSTER_WINDOW_HOURS`` (P-5 sort contract)
  2. Short-circuit empty/N<2 → fallback or empty SelectionResult (P-4/P-8)
  3. Fit TF-IDF ONCE over combined corpus (current + 48h posts) — D-01
  4. Run agglomerative clustering on current slice → labels
  5. Build ClusterCandidate list (one per distinct label)
  6. INSERT every candidate (incl. singletons) with chosen=False — D-12 audit
  7. rank_candidates (excludes singletons, D-07)
  8. Walk ranked candidates; first non-anti-repeat wins
  9. UPDATE winner row to chosen=True; else fallback via pick_fallback
  10. Return SelectionResult with counts_patch for run_log.counts merge

Caller (scheduler) owns the transaction and commits.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

import numpy as np

from tech_news_synth.cluster.antirepeat import check_antirepeat
from tech_news_synth.cluster.cluster import compute_centroid, run_agglomerative
from tech_news_synth.cluster.fallback import pick_fallback
from tech_news_synth.cluster.models import SelectionResult
from tech_news_synth.cluster.rank import ClusterCandidate, rank_candidates
from tech_news_synth.cluster.vectorize import fit_combined_corpus, top_k_terms
from tech_news_synth.db.articles import get_articles_in_window
from tech_news_synth.db.clusters import insert_cluster, update_cluster_chosen
from tech_news_synth.db.posts import (
    get_recent_posted_article_ids,
    get_recent_posts_with_source_texts,
)
from tech_news_synth.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from tech_news_synth.config import Settings
    from tech_news_synth.db.models import Article
    from tech_news_synth.ingest.sources_config import SourcesConfig


_log = get_logger(__name__)


def _empty_counts_patch(articles_in_window: int = 0) -> dict[str, object]:
    return {
        "articles_in_window": articles_in_window,
        "cluster_count": 0,
        "singleton_count": 0,
        "chosen_cluster_id": None,
        "rejected_by_antirepeat": [],
        "fallback_used": False,
        "fallback_article_id": None,
        "fallback_blocked_by_recent_posts": False,
    }


def run_clustering(
    session: Session,
    cycle_id: str,
    settings: Settings,
    sources_config: SourcesConfig,
) -> SelectionResult:
    """D-14 orchestrator. Pure-core + DB glue. Never commits; caller commits."""
    log = _log.bind(phase="cluster")
    source_weights: dict[str, float] = {s.name: s.weight for s in sources_config.sources}

    # Step 1 — load window. P-5: DB sort is authoritative; belt-and-suspenders
    # Python sort enforces invariant if SA query ever drifts.
    articles: list[Article] = get_articles_in_window(session, settings.cluster_window_hours)
    articles.sort(key=lambda a: (a.published_at, a.id))

    # Step 2a — P-4: empty window short-circuit (no TF-IDF fit needed).
    if not articles:
        log.info("cluster_empty_window")
        return SelectionResult(
            winner_cluster_id=None,
            winner_article_ids=None,
            fallback_article_id=None,
            rejected_by_antirepeat=[],
            all_cluster_ids=[],
            counts_patch=_empty_counts_patch(0),
        )

    # Step 2b — P-8: N==1 → fallback directly (can't cluster a single point).
    if len(articles) < 2:
        patch = _empty_counts_patch(len(articles))
        recent_article_ids = get_recent_posted_article_ids(
            session, settings.anti_repeat_window_hours
        )
        fb_id = pick_fallback(
            articles,
            source_weights,
            excluded_article_ids=recent_article_ids,
        )
        if fb_id is None:
            patch["fallback_blocked_by_recent_posts"] = True
            log.info(
                "cluster_single_article_fallback_blocked",
                excluded_count=len(recent_article_ids),
            )
            return SelectionResult(
                winner_cluster_id=None,
                winner_article_ids=None,
                fallback_article_id=None,
                rejected_by_antirepeat=[],
                all_cluster_ids=[],
                counts_patch=patch,
            )

        log.info("cluster_single_article_fallback", fallback_article_id=fb_id)
        patch["fallback_used"] = True
        patch["fallback_article_id"] = fb_id
        return SelectionResult(
            winner_cluster_id=None,
            winner_article_ids=None,
            fallback_article_id=fb_id,
            rejected_by_antirepeat=[],
            all_cluster_ids=[],
            counts_patch=patch,
        )

    # Step 3 — fit combined corpus (current + 48h posts).
    current_texts = [f"{a.title} {a.summary or ''}".strip() for a in articles]
    past_posts = get_recent_posts_with_source_texts(
        session, settings.anti_repeat_window_hours
    )
    fitted = fit_combined_corpus(current_texts, past_posts)

    # Step 4 — cluster current slice.
    X_current = fitted.X[fitted.current_range[0] : fitted.current_range[1]]
    labels = run_agglomerative(X_current, settings.cluster_distance_threshold)

    # Step 5 — group articles by label.
    by_label: dict[int, list[int]] = defaultdict(list)
    for idx, label in enumerate(labels):
        by_label[int(label)].append(idx)

    # Step 6 — persist ALL candidates (incl. singletons) with chosen=False (D-12).
    all_cluster_ids: list[int] = []
    candidates: list[ClusterCandidate] = []
    singleton_count = 0
    for _label, row_indices in sorted(by_label.items()):
        members = [articles[i] for i in row_indices]
        article_ids = [a.id for a in members]
        sources = {a.source for a in members}
        source_count = len(sources)
        most_recent_ts = max(a.published_at for a in members)
        weight_sum = sum(source_weights.get(a.source, 1.0) for a in members)
        centroid = compute_centroid(
            fitted.X, [fitted.current_range[0] + i for i in row_indices]
        )
        terms = top_k_terms(centroid, fitted.vectorizer, k=20)

        cluster_row = insert_cluster(
            session,
            cycle_id=cycle_id,
            member_article_ids=article_ids,
            centroid_terms=terms,
            chosen=False,
            coverage_score=float(source_count),
        )
        all_cluster_ids.append(cluster_row.id)
        if source_count < 2:
            singleton_count += 1

        candidates.append(
            ClusterCandidate(
                cluster_db_id=cluster_row.id,
                member_article_ids=article_ids,
                source_count=source_count,
                most_recent_ts=most_recent_ts,
                weight_sum=weight_sum,
                centroid=centroid,
            )
        )

    session.flush()  # ensure all ids are durable before UPDATE.

    # Step 7-8 — rank (excl. singletons) + anti-repeat walk.
    ranked = rank_candidates(candidates)
    cluster_count = len(ranked)
    rejected: list[int] = []
    winner: ClusterCandidate | None = None
    for cand in ranked:
        hits = check_antirepeat(
            cand.centroid, fitted, past_posts, settings.anti_repeat_cosine_threshold
        )
        if hits:
            rejected.append(cand.cluster_db_id)
            log.info(
                "cluster_rejected_antirepeat",
                cluster_db_id=cand.cluster_db_id,
                colliding_post_ids=hits,
            )
            continue
        winner = cand
        break

    # Step 9 — update winner or fallback.
    counts_patch: dict[str, object] = {
        "articles_in_window": len(articles),
        "cluster_count": cluster_count,
        "singleton_count": singleton_count,
        "chosen_cluster_id": None,
        "rejected_by_antirepeat": list(rejected),
        "fallback_used": False,
        "fallback_article_id": None,
    }

    if winner is not None:
        update_cluster_chosen(session, winner.cluster_db_id, True)
        counts_patch["chosen_cluster_id"] = winner.cluster_db_id
        # Phase 6 plumbing (D-09): serialize centroid for downstream synth.
        # ``winner.centroid`` is the cluster centroid vector returned by
        # compute_centroid; coerce to float32 for compact BYTEA storage.
        winner_centroid_bytes = np.asarray(winner.centroid, dtype=np.float32).tobytes()
        log.info(
            "cluster_winner",
            cluster_db_id=winner.cluster_db_id,
            source_count=winner.source_count,
        )
        return SelectionResult(
            winner_cluster_id=winner.cluster_db_id,
            winner_article_ids=winner.member_article_ids,
            fallback_article_id=None,
            rejected_by_antirepeat=rejected,
            all_cluster_ids=all_cluster_ids,
            counts_patch=counts_patch,
            winner_centroid=winner_centroid_bytes,
        )

    # Fallback path.
    recent_article_ids = get_recent_posted_article_ids(
        session, settings.anti_repeat_window_hours
    )
    fb_id = pick_fallback(
        articles,
        source_weights,
        excluded_article_ids=recent_article_ids,
    )
    if fb_id is None:
        counts_patch["fallback_blocked_by_recent_posts"] = True
        log.info(
            "cluster_fallback_blocked",
            rejected=rejected,
            excluded_count=len(recent_article_ids),
        )
        return SelectionResult(
            winner_cluster_id=None,
            winner_article_ids=None,
            fallback_article_id=None,
            rejected_by_antirepeat=rejected,
            all_cluster_ids=all_cluster_ids,
            counts_patch=counts_patch,
        )

    counts_patch["fallback_used"] = True
    counts_patch["fallback_article_id"] = fb_id
    log.info("cluster_fallback", fallback_article_id=fb_id, rejected=rejected)
    return SelectionResult(
        winner_cluster_id=None,
        winner_article_ids=None,
        fallback_article_id=fb_id,
        rejected_by_antirepeat=rejected,
        all_cluster_ids=all_cluster_ids,
        counts_patch=counts_patch,
    )


__all__ = ["run_clustering"]
