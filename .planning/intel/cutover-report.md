# Cutover Report — tech-news-synth live ship (@ByteRelevant)

> Append-only. `scripts/cutover_verify.py` appends one
> `## Cutover verification — {iso_ts}` block per invocation.
> The operator fills the **Sign-Off** section below after reviewing the
> automated report block and spot-checking the timeline at
> <https://x.com/ByteRelevant>.

## Acceptance Criteria (Phase 8 SC-5 / D-10)

- [ ] ≥ 12 posted tweets in first 24h after cutover
- [ ] Zero Jaccard duplicates (≥ 0.5 similarity over `centroid_terms`)
      across a 48h window anchored at cutover
- [ ] Total cost_usd within 2× Phase 3 baseline
      (baseline = $0.3612 → cap = $0.7224)

## How to Run

```bash
# 24h after cutover (cutover_ts recorded per DEPLOY.md §7.2 step 6):
docker compose run --rm app \
    uv run python scripts/cutover_verify.py \
    --since "<cutover_ts>"
```

Exit codes: `0` on GO, `1` on NO-GO. The markdown report block is appended
to this file AND echoed to stdout regardless of verdict.

**Method note.** Duplicate detection uses **Jaccard over the JSONB keys
of `clusters.centroid_terms`** — NOT cosine similarity over
`posts.theme_centroid` bytes. Phase 5 D-01 fits TF-IDF per-cycle, so the
byte vectors live in per-cycle feature spaces and are not comparable
across cycles; stemmed term names in `centroid_terms` are stable and
give a deterministic, conservative cross-cycle similarity signal.

---

## Operator Sign-Off (fill after cutover_verify runs)

| Field                                         | Value |
| --------------------------------------------- | ----- |
| Cutover ts (UTC, from DEPLOY.md §7.2 step 6)  |       |
| Verification ts (UTC)                         |       |
| Verdict from script                           | [ ] GO / [ ] NO-GO |
| Manual spot-check of @ByteRelevant timeline   | [ ] passed / [ ] issues |
| Anomalies observed                            |       |
| SC-5 Decision                                 | [ ] v1 ACCEPTED / [ ] rollback per DEPLOY.md §7.3 |
| Operator                                      |       |

---

## Automated reports

<!-- cutover_verify.py appends "## Cutover verification — ..." blocks below -->
