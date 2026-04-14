"""STORE-03 — clusters repository.

Module-level functions; caller owns the transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tech_news_synth.db.models import Cluster


def insert_cluster(
    session: Session,
    cycle_id: str,
    member_article_ids: Sequence[int],
    centroid_terms: dict[str, Any] | None = None,
    chosen: bool = False,
    coverage_score: float | None = None,
) -> Cluster:
    """Insert a cluster row for the given cycle. Returns the persisted row.

    Requires that a ``run_log`` row for ``cycle_id`` already exists (FK).
    Caller commits.
    """
    cluster = Cluster(
        cycle_id=cycle_id,
        member_article_ids=list(member_article_ids),
        centroid_terms=centroid_terms or {},
        chosen=chosen,
        coverage_score=coverage_score,
    )
    session.add(cluster)
    session.flush()
    return cluster


def get_clusters_for_cycle(session: Session, cycle_id: str) -> list[Cluster]:
    """Return clusters for ``cycle_id`` ordered by id ascending."""
    return list(
        session.execute(
            select(Cluster).where(Cluster.cycle_id == cycle_id).order_by(Cluster.id)
        ).scalars()
    )


def update_cluster_chosen(session: Session, cluster_id: int, chosen: bool) -> None:
    """Flip the ``chosen`` flag on a persisted cluster row (D-12 audit trail).

    Raises ``ValueError`` if the row doesn't exist — caller bug since all
    candidates are inserted before this is called (D-12 persist-all-first).
    """
    result = session.execute(
        update(Cluster).where(Cluster.id == cluster_id).values(chosen=chosen)
    )
    if result.rowcount == 0:
        raise ValueError(f"cluster_id={cluster_id} not found")
    session.flush()


__all__ = ["get_clusters_for_cycle", "insert_cluster", "update_cluster_chosen"]
