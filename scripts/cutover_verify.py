#!/usr/bin/env python3
"""Post-24h live-cutover acceptance check (Phase 8 D-10 / SC-5).

Given a cutover timestamp via ``--since``, computes three invariants:

1. **Post count (24h):**
   ``COUNT(*) FROM posts WHERE status='posted' AND posted_at IN [since, since+24h)``.
   PASS ≥ 12.

2. **Anti-repeat audit (48h window, pre-cutover retrospective + cutover window):**
   Over posts with ``status='posted'`` and ``posted_at >= since - 48h``, compute
   pairwise Jaccard similarity on each pair's ``clusters.centroid_terms`` JSONB
   **keys** (stemmed term names). Flag pairs ≥ ``--jaccard-threshold``.

   *Explicit callout:* we use Jaccard over ``centroid_terms`` and NOT cosine
   over ``posts.theme_centroid`` bytes, because Phase 5 D-01 fits TF-IDF
   **per cycle** — the stored byte vectors live in per-cycle feature spaces
   and are not comparable across cycles. Jaccard over stemmed term names is
   deterministic and cheap.

3. **Cost envelope (24h):**
   ``SUM(cost_usd)`` over the 24h window, compared against baseline
   ``12 x $0.03 + 12 x $0.0001 = $0.3612`` from
   ``.planning/intel/x-api-baseline.md``. PASS <= ``--cost-multiplier`` x baseline.

**Verdict:** GO only if all three pass. Exit 0 on GO, 1 on NO-GO.

**Security (T-08-08 / Pitfall 5):** ``render_report`` reads ONLY from the
verdict dict — it never imports, prints, or references ``Settings``. A unit
test asserts no secret-shaped strings leak into the report.

Usage
-----
    uv run python scripts/cutover_verify.py --since 2026-04-15T00:00:00Z
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tech_news_synth.config import load_settings
from tech_news_synth.db.models import Cluster, Post
from tech_news_synth.db.session import SessionLocal, init_engine

# 12 tweets/24h x $0.03 + 12 x $0.0001 synth cost = $0.3612
# (from .planning/intel/x-api-baseline.md Phase 3 GO intel).
BASELINE_COST_24H_USD = 0.3612
DEFAULT_REPORT_PATH = ".planning/intel/cutover-report.md"
DEFAULT_JACCARD_THRESHOLD = 0.5
DEFAULT_COST_MULTIPLIER = 2.0


# ---------------------------------------------------------------------------
# Pure math
# ---------------------------------------------------------------------------
def term_jaccard(a: dict, b: dict) -> float:
    """Jaccard similarity over the ``.keys()`` of two centroid_terms dicts.

    Returns 0.0 if either dict is empty (short-circuit avoids div-by-zero and
    avoids false-positive ``0/0`` pairs for empty-term fallback posts).
    """
    set_a, set_b = set(a.keys()), set(b.keys())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


# ---------------------------------------------------------------------------
# DB-facing verdict computation
# ---------------------------------------------------------------------------
def compute_verdict(
    since: datetime,
    jaccard_threshold: float,
    cost_multiplier: float,
    session: Session,
) -> dict[str, Any]:
    """Issue the three queries and return the structured result dict."""
    now = datetime.now(UTC)
    since_plus_24h = since + timedelta(hours=24)
    window_start_48h = since - timedelta(hours=48)

    # 1. Post count in the 24h cutover window.
    posted_24h = int(
        session.execute(
            select(func.count(Post.id)).where(
                Post.status == "posted",
                Post.posted_at >= since,
                Post.posted_at < since_plus_24h,
            )
        ).scalar_one()
    )

    # 2. Jaccard dup audit over a 48h window anchored at --since.
    rows = session.execute(
        select(Post.id, Post.posted_at, Post.cluster_id, Cluster.centroid_terms)
        .join(Cluster, Post.cluster_id == Cluster.id, isouter=True)
        .where(Post.status == "posted", Post.posted_at >= window_start_48h)
        .order_by(Post.posted_at)
    ).all()

    suspects: list[dict[str, Any]] = []
    for i, (id_a, ts_a, _cid_a, terms_a) in enumerate(rows):
        for id_b, ts_b, _cid_b, terms_b in rows[i + 1 :]:
            if terms_a and terms_b:
                sim = term_jaccard(terms_a, terms_b)
                if sim >= jaccard_threshold:
                    suspects.append(
                        {
                            "post_a": id_a,
                            "post_b": id_b,
                            "posted_a": ts_a.isoformat() if ts_a is not None else None,
                            "posted_b": ts_b.isoformat() if ts_b is not None else None,
                            "jaccard": round(sim, 3),
                        }
                    )

    # 3. Cost sum in the 24h cutover window.
    cost_sum_raw = session.execute(
        select(func.coalesce(func.sum(Post.cost_usd), 0.0)).where(
            Post.status == "posted",
            Post.posted_at >= since,
            Post.posted_at < since_plus_24h,
        )
    ).scalar_one()
    # Numeric → Decimal → float for JSON/markdown friendliness.
    cost_sum_usd = float(cost_sum_raw) if cost_sum_raw is not None else 0.0

    count_ok = posted_24h >= 12
    dups_ok = len(suspects) == 0
    cost_cap = BASELINE_COST_24H_USD * cost_multiplier
    cost_ok = cost_sum_usd <= cost_cap
    verdict = "GO" if (count_ok and dups_ok and cost_ok) else "NO-GO"

    return {
        "since": since.isoformat(),
        "now": now.isoformat(),
        "posted_24h": posted_24h,
        "count_ok": count_ok,
        "jaccard_threshold": jaccard_threshold,
        "jaccard_suspects": suspects,
        "dups_ok": dups_ok,
        "cost_sum_usd": cost_sum_usd,
        "cost_baseline_usd": BASELINE_COST_24H_USD,
        "cost_multiplier": cost_multiplier,
        "cost_cap_usd": cost_cap,
        "cost_ok": cost_ok,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Markdown rendering (T-08-08: reads ONLY from result dict)
# ---------------------------------------------------------------------------
def render_report(result: dict[str, Any]) -> str:
    """Render a human-readable markdown report block from the verdict dict.

    Does not import or reference Settings. A unit test enforces that no
    secret-shaped strings appear in the output (T-08-08 / Pitfall 5).
    """
    verdict = result["verdict"]
    lines: list[str] = []
    lines.append(f"## Cutover verification — {result['now']}")
    lines.append("")
    lines.append(f"**Since:** `{result['since']}`   |   **Verdict:** **{verdict}**")
    lines.append("")

    lines.append("### Post count (24h)")
    lines.append(f"- Observed: **{result['posted_24h']}**")
    lines.append("- Target: ≥ 12")
    lines.append(f"- Pass: **{result['count_ok']}**")
    lines.append("")

    lines.append(f"### Jaccard dup audit (48h window, threshold ≥ {result['jaccard_threshold']})")
    suspects = result["jaccard_suspects"]
    lines.append(f"- Suspects found: **{len(suspects)}**")
    lines.append(f"- Pass: **{result['dups_ok']}**")
    if suspects:
        lines.append("")
        lines.append("| post_a | post_b | posted_a | posted_b | jaccard |")
        lines.append("| ------ | ------ | -------- | -------- | ------- |")
        for s in suspects:
            lines.append(
                f"| {s['post_a']} | {s['post_b']} | {s['posted_a']} | "
                f"{s['posted_b']} | {s['jaccard']} |"
            )
    lines.append("")

    lines.append("### Cost (24h)")
    lines.append(f"- Observed: **${result['cost_sum_usd']:.4f}**")
    lines.append(f"- Baseline: ${result['cost_baseline_usd']:.4f}")
    lines.append(
        f"- Cap (x{result['cost_multiplier']}): ${result['cost_cap_usd']:.4f}"
    )
    lines.append(f"- Pass: **{result['cost_ok']}**")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def _parse_since(raw: str) -> datetime:
    """Parse ISO8601 (with trailing Z allowed) into a UTC-aware datetime."""
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cutover_verify",
        description=(
            "Post-24h live-cutover acceptance check: post count, Jaccard dup "
            "audit (over centroid_terms), and cost sum against Phase 3 baseline."
        ),
    )
    parser.add_argument(
        "--since",
        required=True,
        help="Cutover timestamp (ISO8601 UTC, e.g. 2026-04-15T00:00:00Z).",
    )
    parser.add_argument(
        "--report-path",
        default=DEFAULT_REPORT_PATH,
        help=f"Append-only markdown report path (default: {DEFAULT_REPORT_PATH}).",
    )
    parser.add_argument(
        "--jaccard-threshold",
        type=float,
        default=DEFAULT_JACCARD_THRESHOLD,
        help="Jaccard similarity threshold to flag as duplicate (default: 0.5).",
    )
    parser.add_argument(
        "--cost-multiplier",
        type=float,
        default=DEFAULT_COST_MULTIPLIER,
        help="Multiplier over Phase 3 $0.3612 baseline for cost cap (default: 2.0).",
    )
    args = parser.parse_args(argv)

    since = _parse_since(args.since)
    settings = load_settings()
    init_engine(settings)
    with SessionLocal() as session:
        result = compute_verdict(
            since, args.jaccard_threshold, args.cost_multiplier, session
        )

    report_md = render_report(result)
    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("a", encoding="utf-8") as f:
        f.write(report_md)

    print(report_md)
    return 0 if result["verdict"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
