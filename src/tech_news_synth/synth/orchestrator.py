"""Phase 6 orchestrator — ``run_synthesis`` (Plan 06-02).

Composes the pure-core synth modules (06-01) into a persistent phase step:

    scheduler → run_synthesis(session, cycle_id, selection, settings,
                              sources_config, anthropic_client, allowlist)
             → SynthesisResult (with post_id populated)

Flow (winner branch):
  1. ``get_articles_by_ids`` → materialize cluster members (input-order).
  2. ``pick_articles_for_synthesis`` → 3-5 diverse-source picks (D-01).
  3. ``pick_source_url`` → highest-weight URL (D-02).
  4. ``select_hashtags(cluster.centroid_terms, allowlist)`` → 1-2 tags (D-11).
  5. Retry loop: up to ``synthesis_max_retries + 1`` attempts. Each attempt:
     - Build system + user (or retry) prompt.
     - ``call_haiku`` → (text, in_tok, out_tok). Accumulate tokens.
     - Compose candidate = ``format_final_post(text, url, hashtags)``.
     - If ``weighted_len(candidate) <= 280`` → break (completed).
     - Else re-prompt with ``build_retry_prompt``.
  6. If loop exhausted → ``word_boundary_truncate`` last body, then
     reformat final_text. ``final_method="truncated"``.
  7. ``insert_post(status='pending'|'dry_run', theme_centroid, cost_usd,
     synthesized_text=final_text, hashtags, error_detail=attempt_log?)``.
  8. Return ``SynthesisResult`` with ``counts_patch`` for run_log merge.

Fallback branch (single article):
  - ``session.get(Article, fallback_article_id)``; single-item ``selected``.
  - ``source_url = article.url``; ``cluster_id = None``; ``theme_centroid = None``.
  - ``centroid_terms = {}`` → hashtags = ``allowlist.default[:max_tags]``.

Invariants:
  - ``weighted_len(final_text) <= 280`` ALWAYS (asserted before insert_post).
  - ``cost_usd > 0`` whenever Anthropic returned (even DRY_RUN; D-12).
  - Anthropic exceptions propagate (no swallow) → INFRA-08 at scheduler.
  - Empty selection (both winner AND fallback None) → ``ValueError`` (defensive;
    caller must short-circuit).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

from tech_news_synth.db.articles import get_articles_by_ids
from tech_news_synth.db.models import Article, Cluster
from tech_news_synth.db.posts import insert_post
from tech_news_synth.logging import get_logger
from tech_news_synth.synth.article_picker import pick_articles_for_synthesis
from tech_news_synth.synth.charcount import weighted_len
from tech_news_synth.synth.client import call_haiku
from tech_news_synth.synth.hashtags import HashtagAllowlist, select_hashtags
from tech_news_synth.synth.models import SynthesisResult
from tech_news_synth.synth.pricing import compute_cost_usd
from tech_news_synth.synth.prompt import (
    build_retry_prompt,
    build_system_prompt,
    build_user_prompt,
    format_final_post,
)
from tech_news_synth.synth.truncate import word_boundary_truncate
from tech_news_synth.synth.url_picker import pick_source_url

if TYPE_CHECKING:
    import anthropic
    from sqlalchemy.orm import Session

    from tech_news_synth.cluster.models import SelectionResult
    from tech_news_synth.config import Settings
    from tech_news_synth.ingest.sources_config import SourcesConfig


_log = get_logger(__name__)


def run_synthesis(
    session: Session,
    cycle_id: str,
    selection: SelectionResult,
    settings: Settings,
    sources_config: SourcesConfig,
    anthropic_client: anthropic.Anthropic,
    hashtag_allowlist: HashtagAllowlist,
    *,
    persist: bool = True,
) -> SynthesisResult:
    """Compose synthesis and (optionally) persist a posts row (Plan 06-02 / Phase 8 D-12).

    ``persist=True`` (default): writes a posts row via ``insert_post``. This is the
    scheduler's production path; the returned ``SynthesisResult`` has
    ``post_id=<int>`` and ``status ∈ {pending, dry_run}``.

    ``persist=False``: skips the ``insert_post`` call entirely (no DB writes from
    this function). Returns ``SynthesisResult`` with ``post_id=None`` and
    ``status='replay'``. Consumed by ``cli.replay`` (OPS-02).
    """
    log = _log.bind(phase="synth", cycle_id=cycle_id)

    # --- Step 1: defensive empty-selection guard ---
    if selection.winner_cluster_id is None and selection.fallback_article_id is None:
        raise ValueError(
            "run_synthesis called with empty selection — caller must short-circuit"
        )

    # --- Step 2: branch on winner vs fallback ---
    cluster_id: int | None
    theme_centroid: bytes | None
    centroid_terms: dict[str, float]
    selected: list[Article]
    source_url: str

    if selection.winner_cluster_id is not None:
        # Winner path
        ids = selection.winner_article_ids or []
        articles_all = get_articles_by_ids(session, ids)
        if not articles_all:
            raise ValueError(
                f"winner cluster {selection.winner_cluster_id} has no articles"
            )
        selected = pick_articles_for_synthesis(articles_all, max_articles=5)
        source_weights = {
            s.name: getattr(s, "weight", 1.0)
            for s in sources_config.sources
        }
        source_url = pick_source_url(selected, source_weights)
        cluster_id = selection.winner_cluster_id
        theme_centroid = selection.winner_centroid  # may be None in legacy cases
        cluster_row = session.get(Cluster, cluster_id)
        centroid_terms = (
            dict(cluster_row.centroid_terms) if cluster_row is not None and cluster_row.centroid_terms else {}
        )
    else:
        # Fallback path
        article = session.get(Article, selection.fallback_article_id)
        if article is None:
            raise ValueError(
                f"fallback article {selection.fallback_article_id} not found"
            )
        selected = [article]
        source_url = article.url
        cluster_id = None
        theme_centroid = None
        centroid_terms = {}

    # --- Step 3: hashtags (D-05, D-11) ---
    hashtags = select_hashtags(
        centroid_terms, hashtag_allowlist, top_k=10, max_tags=2
    )
    # Enforce hashtag budget (weighted). Pathological tags → drop last.
    while (
        hashtags
        and len(hashtags) > 1
        and weighted_len(" ".join(hashtags)) > settings.hashtag_budget_chars
    ):
        hashtags = hashtags[:-1]

    # --- Step 4: prompt + retry loop (D-06) ---
    body_budget = settings.synthesis_char_budget
    system = build_system_prompt(body_budget)
    user_prompt = build_user_prompt(selected)
    current_prompt = user_prompt

    attempt_log: list[dict] = []
    total_input_tokens = 0
    total_output_tokens = 0
    body_text: str | None = None
    final_method: Literal["completed", "truncated"] = "completed"
    max_attempts = settings.synthesis_max_retries + 1
    last_text = ""

    for attempt in range(1, max_attempts + 1):
        text, in_tok, out_tok = call_haiku(
            anthropic_client, system, current_prompt, settings.synthesis_max_tokens
        )
        total_input_tokens += in_tok
        total_output_tokens += out_tok
        last_text = text
        candidate = format_final_post(text, source_url, hashtags)
        cand_len = weighted_len(candidate)
        attempt_log.append(
            {"attempt": attempt, "length": cand_len, "text_preview": text[:120]}
        )
        log.info(
            "synth_attempt",
            attempt=attempt,
            length=cand_len,
            input_tokens=in_tok,
            output_tokens=out_tok,
        )
        if cand_len <= 280:
            body_text = text
            break
        # Prepare retry prompt for next iteration
        current_prompt = build_retry_prompt(text, cand_len, body_budget - 10)
    else:
        # Exhausted attempts — truncate last body to fit remaining budget
        hashtag_block = " ".join(hashtags)
        # Overhead: " " + URL (t.co 23 chars) + optional (" " + hashtag_block)
        overhead = 1 + 23
        if hashtag_block:
            overhead += 1 + weighted_len(hashtag_block)
        body_budget_hard = max(0, 280 - overhead)
        body_text = word_boundary_truncate(last_text, body_budget_hard)
        final_method = "truncated"
        log.warning(
            "synth_truncated",
            final_length_estimate=weighted_len(
                format_final_post(body_text, source_url, hashtags)
            ),
        )

    assert body_text is not None
    final_text = format_final_post(body_text, source_url, hashtags)
    assert weighted_len(final_text) <= 280, "weighted_len invariant violated"
    attempts_count = len(attempt_log)

    # --- Step 5: cost + status ---
    cost_usd = compute_cost_usd(total_input_tokens, total_output_tokens)
    status: Literal["pending", "dry_run", "replay"]
    if not persist:
        status = "replay"
    else:
        status = "dry_run" if settings.dry_run else "pending"
    error_detail = (
        json.dumps(attempt_log, ensure_ascii=False)
        if final_method == "truncated"
        else None
    )

    # --- Step 6: persist (Phase 8 D-12: skipped when persist=False) ---
    post_id: int | None
    if persist:
        post = insert_post(
            session,
            cycle_id=cycle_id,
            cluster_id=cluster_id,
            status=status,
            theme_centroid=theme_centroid,
            synthesized_text=final_text,
            hashtags=hashtags,
            cost_usd=cost_usd,
            error_detail=error_detail,
        )
        session.flush()
        post_id = post.id
    else:
        post_id = None

    log.info(
        "synth_done",
        attempts=attempts_count,
        final_method=final_method,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        cost_usd=cost_usd,
        post_id=post_id,
        persist=persist,
    )

    return SynthesisResult(
        text=final_text,
        body_text=body_text,
        hashtags=hashtags,
        source_url=source_url,
        attempts=attempts_count,
        final_method=final_method,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        cost_usd=cost_usd,
        post_id=post_id,
        status=status,
        counts_patch={
            "synth_attempts": attempts_count,
            "synth_truncated": final_method == "truncated",
            "synth_input_tokens": total_input_tokens,
            "synth_output_tokens": total_output_tokens,
            "synth_cost_usd": cost_usd,
            "char_budget_used": weighted_len(final_text),  # Phase 8 OPS-01 D-06 field 6
            "post_id": post_id,
        },
    )


__all__ = ["run_synthesis"]
