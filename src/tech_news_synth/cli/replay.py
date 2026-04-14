"""``replay`` CLI (Phase 8 OPS-02 / D-01).

    python -m tech_news_synth replay --cycle-id 01K...

Re-runs synthesis for a past cycle WITHOUT writing a posts row (uses
``run_synthesis(..., persist=False)``). Prints a JSON payload to stdout:

    {cycle_id, text, hashtags, source_url, cost_usd,
     input_tokens, output_tokens, final_method}

Branches:
  * Winner-cluster path — original cycle persisted a ``posts`` row with a
    non-null ``cluster_id``. We look up the chosen cluster, build a minimal
    ``SelectionResult`` from its members + the post's ``theme_centroid``,
    and re-invoke synthesis.
  * Fallback-article path — the cycle took the single-article fallback.
    We read ``run_log.counts['fallback_article_id']`` for that cycle_id
    (Phase 5 contract, regression-locked by
    ``test_single_article_window_fallback``).
  * Unknown / unresolvable cycle → stderr + exit 1.

T-08-02 mitigation: ``persist=False`` is keyword-only, and we explicitly
``session.rollback()`` after synthesis to wipe any flushes. The integration
test locks the invariant that posts count is unchanged before/after replay.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import anthropic
from sqlalchemy import select

from tech_news_synth.cluster.models import SelectionResult
from tech_news_synth.config import load_settings
from tech_news_synth.db.models import Cluster, Post, RunLog
from tech_news_synth.db.session import SessionLocal, init_engine
from tech_news_synth.ingest.sources_config import load_sources_config
from tech_news_synth.logging import configure_logging
from tech_news_synth.synth.hashtags import load_hashtag_allowlist
from tech_news_synth.synth.orchestrator import run_synthesis


def _resolve_selection(session, cycle_id: str) -> SelectionResult | None:
    """Return a SelectionResult reconstructed from persisted cycle state, or
    None when the cycle cannot be resolved (missing entirely or cluster
    dangling)."""
    post = session.execute(
        select(Post).where(Post.cycle_id == cycle_id).limit(1)
    ).scalar_one_or_none()

    if post is not None and post.cluster_id is not None:
        cluster = session.get(Cluster, post.cluster_id)
        if cluster is None:
            return None
        return SelectionResult(
            winner_cluster_id=cluster.id,
            winner_article_ids=list(cluster.member_article_ids or []),
            fallback_article_id=None,
            rejected_by_antirepeat=[],
            all_cluster_ids=[cluster.id],
            counts_patch={},
            winner_centroid=post.theme_centroid,
        )

    # Fallback branch — read fallback_article_id from run_log.counts.
    run = session.execute(
        select(RunLog).where(RunLog.cycle_id == cycle_id).limit(1)
    ).scalar_one_or_none()
    fb_id = (run.counts or {}).get("fallback_article_id") if run else None
    if fb_id is None:
        return None
    return SelectionResult(
        winner_cluster_id=None,
        winner_article_ids=None,
        fallback_article_id=int(fb_id),
        rejected_by_antirepeat=[],
        all_cluster_ids=[],
        counts_patch={},
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="replay")
    parser.add_argument("--cycle-id", required=True, dest="cycle_id")
    args = parser.parse_args(argv)
    cid = args.cycle_id

    settings = load_settings()
    configure_logging(settings)
    init_engine(settings)
    sources_config = load_sources_config(Path(settings.sources_config_path))
    hashtag_allowlist = load_hashtag_allowlist(Path(settings.hashtags_config_path))

    with SessionLocal() as session:
        selection = _resolve_selection(session, cid)
        if selection is None:
            print(
                f"cycle-id {cid} not found or has no resolvable input",
                file=sys.stderr,
            )
            return 1

        anthropic_client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
        )
        synthesis = run_synthesis(
            session,
            cid,
            selection,
            settings,
            sources_config,
            anthropic_client,
            hashtag_allowlist,
            persist=False,
        )
        # T-08-02 defense: wipe any flushes. persist=False means insert_post
        # was not called, so nothing SHOULD be pending, but belt-and-suspenders.
        session.rollback()

    print(
        json.dumps(
            {
                "cycle_id": cid,
                "text": synthesis.text,
                "hashtags": synthesis.hashtags,
                "source_url": synthesis.source_url,
                "cost_usd": synthesis.cost_usd,
                "input_tokens": synthesis.input_tokens,
                "output_tokens": synthesis.output_tokens,
                "final_method": synthesis.final_method,
            },
            ensure_ascii=False,
        )
    )
    return 0
