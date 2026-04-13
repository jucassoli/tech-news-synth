"""STORE-03 — clusters repo persists per-cycle metadata."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from tech_news_synth.db.clusters import get_clusters_for_cycle, insert_cluster
from tech_news_synth.db.run_log import start_cycle


def _seed_run_log(db_session, cycle_id: str) -> str:
    start_cycle(db_session, cycle_id)
    return cycle_id


def test_insert_cluster_persists_arrays_and_jsonb(db_session) -> None:
    cid = _seed_run_log(db_session, "01CLUSTERSEED00000000000001")
    cluster = insert_cluster(
        db_session,
        cycle_id=cid,
        member_article_ids=[1, 2, 3, 4],
        centroid_terms={"ai": 0.7, "openai": 0.3},
        chosen=True,
        coverage_score=0.85,
    )
    assert cluster.id is not None
    assert cluster.cycle_id == cid
    assert cluster.member_article_ids == [1, 2, 3, 4]
    assert cluster.centroid_terms == {"ai": 0.7, "openai": 0.3}
    assert cluster.chosen is True
    assert cluster.coverage_score == 0.85
    assert cluster.created_at is not None


def test_get_clusters_for_cycle_returns_in_id_order(db_session) -> None:
    cid = _seed_run_log(db_session, "01CLUSTERORDER0000000000001")
    insert_cluster(db_session, cycle_id=cid, member_article_ids=[1])
    insert_cluster(db_session, cycle_id=cid, member_article_ids=[2, 3])
    insert_cluster(db_session, cycle_id=cid, member_article_ids=[4])

    found = get_clusters_for_cycle(db_session, cid)
    assert len(found) == 3
    ids = [c.id for c in found]
    assert ids == sorted(ids)
    assert [c.member_article_ids for c in found] == [[1], [2, 3], [4]]


def test_get_clusters_for_unknown_cycle_returns_empty(db_session) -> None:
    assert get_clusters_for_cycle(db_session, "01NEVEREXISTED00000000001") == []


def test_cluster_without_run_log_violates_fk(db_session) -> None:
    """FK constraint: cluster.cycle_id must reference run_log.cycle_id."""
    with pytest.raises(IntegrityError):
        # insert_cluster itself flushes — FK violation surfaces immediately.
        insert_cluster(db_session, cycle_id="01ORPHAN0000000000000000001", member_article_ids=[])
