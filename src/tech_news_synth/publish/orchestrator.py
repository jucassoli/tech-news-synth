"""Phase 7 orchestrator — run_publish.

Handles the 3 status outcomes that run_publish itself produces:
  - 'posted'  — X API 2xx, DB transitioned to status='posted'
  - 'failed'  — X API 4xx/5xx/network/429, DB transitioned to status='failed'
  - 'dry_run' — upstream set status='dry_run'; no X call, row untouched

Scheduler-level outcomes (``capped``, ``empty``) are produced by
``scheduler.run_cycle`` BEFORE calling (or instead of calling) run_publish —
the ``PublishResult`` model accepts those status values so the scheduler can
build a uniform result object.

Contract with Plan 07-01:
  - ``post_tweet`` never raises (returns ``XCallOutcome``).
  - ``update_post_to_posted`` / ``update_post_to_failed`` do NOT touch
    ``cost_usd`` (T-07-07 regression guarded).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from structlog.contextvars import bind_contextvars

from tech_news_synth.db.posts import (
    get_post_tweets,
    insert_post_tweets,
    update_post_to_failed,
    update_post_to_posted,
    update_post_tweet_id,
)
from tech_news_synth.logging import get_logger
from tech_news_synth.publish.client import post_tweet
from tech_news_synth.publish.models import PublishResult

if TYPE_CHECKING:
    import tweepy
    from sqlalchemy.orm import Session

    from tech_news_synth.config import Settings
    from tech_news_synth.synth.models import SynthesisResult

_log = get_logger(__name__)


def run_publish(
    session: Session,
    cycle_id: str,
    synthesis_result: SynthesisResult,
    settings: Settings,
    x_client: tweepy.Client | None,
) -> PublishResult:
    """One publish attempt per cycle (D-03).

    Pre-conditions:
      - ``synthesis_result.post_id`` is the row to transition.
      - ``synthesis_result.status`` is ``'pending'`` (publish) or
        ``'dry_run'`` (skip).
      - ``x_client`` is built by scheduler when status='pending'; may be
        None when status='dry_run'.
    """
    bind_contextvars(phase="publish", post_id=synthesis_result.post_id)
    log = _log.bind(phase="publish", cycle_id=cycle_id, post_id=synthesis_result.post_id)

    # --- DRY_RUN short-circuit (D-09) ---
    if synthesis_result.status == "dry_run":
        log.info("publish_skipped_dry_run", post_id=synthesis_result.post_id)
        return PublishResult(
            post_id=synthesis_result.post_id,
            status="dry_run",
            tweet_id=None,
            attempts=0,
            elapsed_ms=0,
            error_detail=None,
            counts_patch={
                "publish_status": "dry_run",
                "tweet_id": None,
            },
        )

    # --- Live publish path (PUBLISH-01/02/03) ---
    assert x_client is not None, "x_client required when synthesis_result.status != 'dry_run'"
    assert synthesis_result.post_id is not None, "synthesis_result must have post_id for publish"

    thread_texts = synthesis_result.thread_texts or [synthesis_result.text]
    if not get_post_tweets(session, synthesis_result.post_id):
        insert_post_tweets(session, synthesis_result.post_id, thread_texts)
    posted_ids: list[str] = []
    total_elapsed_ms = 0
    reply_to_id: str | None = None
    failed_part: int | None = None

    for idx, text in enumerate(thread_texts, start=1):
        outcome = post_tweet(x_client, text, in_reply_to_tweet_id=reply_to_id)
        total_elapsed_ms += outcome.elapsed_ms
        if outcome.status == "posted":
            assert outcome.tweet_id is not None, "XCallOutcome('posted') must carry tweet_id"
            update_post_tweet_id(
                session,
                synthesis_result.post_id,
                idx,
                outcome.tweet_id,
            )
            posted_ids.append(outcome.tweet_id)
            reply_to_id = outcome.tweet_id
            continue

        failed_part = idx
        break

    # --- Success branch ---
    if failed_part is None:
        posted_at = datetime.now(UTC)
        root_tweet_id = posted_ids[0]
        update_post_to_posted(
            session,
            synthesis_result.post_id,
            root_tweet_id,
            posted_at,
        )
        log.info(
            "publish_posted",
            post_id=synthesis_result.post_id,
            tweet_id=root_tweet_id,
            elapsed_ms=total_elapsed_ms,
            thread_parts_posted=len(posted_ids),
        )
        return PublishResult(
            post_id=synthesis_result.post_id,
            status="posted",
            tweet_id=root_tweet_id,
            attempts=len(thread_texts),
            elapsed_ms=total_elapsed_ms,
            error_detail=None,
            counts_patch={
                "publish_status": "posted",
                "tweet_id": root_tweet_id,
                "publish_elapsed_ms": total_elapsed_ms,
                "thread_parts_planned": len(thread_texts),
                "thread_parts_posted": len(posted_ids),
            },
            tweet_ids=posted_ids,
            parts_posted=len(posted_ids),
        )

    # --- Failure branch (rate_limited or publish_error) ---
    outcome = outcome  # last failed outcome from the loop above
    error_detail = outcome.error_detail or {"reason": "publish_error", "message": "unknown"}
    error_json = json.dumps(error_detail, ensure_ascii=False, default=str)
    update_post_to_failed(session, synthesis_result.post_id, error_json)

    if outcome.status == "rate_limited":
        reset_epoch = error_detail.get("x_rate_limit_reset") or 0
        try:
            reset_epoch_int = int(reset_epoch)
        except (TypeError, ValueError):
            reset_epoch_int = 0
        reset_iso = (
            datetime.fromtimestamp(reset_epoch_int, UTC).isoformat() if reset_epoch_int else None
        )
        log.warning(
            "rate_limit_hit",
            post_id=synthesis_result.post_id,
            reset_at=reset_iso,
            retry_after_seconds=error_detail.get("retry_after_seconds"),
        )
        counts_patch: dict[str, object] = {
            "publish_status": "failed",
            "tweet_id": posted_ids[0] if posted_ids else None,
            "rate_limited": True,
            "publish_elapsed_ms": total_elapsed_ms,
            "thread_parts_planned": len(thread_texts),
            "thread_parts_posted": len(posted_ids),
            "thread_failed_part": failed_part,
        }
    else:
        log.error(
            "publish_failed",
            post_id=synthesis_result.post_id,
            reason=error_detail.get("reason"),
            status_code=error_detail.get("status_code"),
            tweepy_error_type=error_detail.get("tweepy_error_type"),
            failed_part=failed_part,
        )
        counts_patch = {
            "publish_status": "failed",
            "tweet_id": posted_ids[0] if posted_ids else None,
            "publish_error_reason": error_detail.get("reason"),
            "publish_elapsed_ms": total_elapsed_ms,
            "thread_parts_planned": len(thread_texts),
            "thread_parts_posted": len(posted_ids),
            "thread_failed_part": failed_part,
        }

    return PublishResult(
        post_id=synthesis_result.post_id,
        status="failed",
        tweet_id=posted_ids[0] if posted_ids else None,
        attempts=len(thread_texts),
        elapsed_ms=total_elapsed_ms,
        error_detail=error_detail,
        counts_patch=counts_patch,
        tweet_ids=posted_ids,
        parts_posted=len(posted_ids),
        failed_part=failed_part,
    )


__all__ = ["run_publish"]
