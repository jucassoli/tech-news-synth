# X API Baseline — Phase 3 Validation Gate

**Status:** FILLED
**Last updated:** 2026-04-13
**Operator:** jucassoli
**Commit:** filled in the same commit as this edit

## Measurement Context

- **Account:** @ByteRelevant
- **Tier:** pay-per-use (X Free tier deprecated 2026-02-06)
- **cycle_id:** n/a (smoke scripts do not emit a cycle_id)
- **Date of measurement:** 2026-04-13T18:25:59Z

## GATE-01 — Anthropic Haiku 4.5

- **Model id:** `claude-haiku-4-5`
- **Input tokens (sample):** 18
- **Output tokens (sample):** 4
- **Computed cost_usd (sample):** 0.000038
- **Pricing constants used:** $1.00/MTok input, $5.00/MTok output (last verified 2026-04-13)
- **Completion returned:** `"Ok"`

## GATE-02 — X OAuth 1.0a User Context

- **`get_me()` username:** ByteRelevant
- **User id:** 2042955761093873664
- **OAuth permissions:** Read+Write (inferred: GATE-03 post succeeded)

## GATE-03 — Live Post Round-Trip

- **tweet_id:** 2043757607970619474
- **posted_at:** 2026-04-13T18:25:59.339623+00:00
- **deleted_at:** 2026-04-13T18:25:59.898178+00:00
- **elapsed_ms (post only):** 377
- **Rate-limit headers observed:**
  - `x-rate-limit-limit`: 100
  - `x-rate-limit-remaining`: 99
  - `x-rate-limit-reset`: 1776105659
  - `x-user-limit-24hour-limit`: absent
  - `x-user-limit-24hour-remaining`: absent
  - `x-user-limit-24hour-reset`: absent
- **Daily cap (derived):** not exposed on this response — `x-user-limit-24hour-*` headers were absent on the pay-per-use tier. Per-window cap is `x-rate-limit-limit=100`. Practical daily cap is governed by the monthly cost cap (PUBLISH-05), not by X-side header enforcement.

**Manual visual verification** (done separately because auto-delete round-trip was ~560 ms, too fast to eyeball):
- Manual visible post succeeded and was confirmed on https://x.com/ByteRelevant profile
- Manual visible tweet_id: 2043759709690163452
- Manual visible tweet was deleted successfully

## Observed USD/Post (manual paste from X billing portal)

- **Source:** X Developer Portal → Billing / Usage (captured 2026-04-13)
- **Observed USD/post:** 0.03 (single-sample; balance moved from $10.00 → $9.97 after the one live-post validation)
- **Note:** Scripts cannot read this programmatically; operator pasted this value after the GATE-03 run.

## Cost Envelope Check (vs PROJECT.md budget $20-50/mo)

- **Target:** 12 posts/day × 30 days = 360 posts/month
- **Projected X cost/month:** 360 × $0.03 = **$10.80**
- **Projected Haiku cost/month:** 360 × $0.000038 ≈ **$0.01** (smoke prompt is tiny; real synthesis with ~250-token prompts will run ~$0.10-0.30/month — still negligible)
- **Total projected:** ~**$10.81** (X dominant)
- **Within $20-50/mo envelope?:** **YES — under the floor.** Projected burn is ~$11/month vs the $20-50/mo envelope. This is a comfortable margin: we can sustain 12 posts/day well under budget, and have headroom to absorb up to ~3× cost growth per post before hitting the envelope ceiling.

## How This Was Measured

- `scripts/smoke_anthropic.py` → GATE-01 values
- `scripts/smoke_x_auth.py` → GATE-02 values
- `scripts/smoke_x_post.py --arm-live-post` → GATE-03 values + rate-limit headers
- Observed USD/post: manual paste from X Developer Portal billing dashboard (balance delta $10.00 → $9.97 after one post)

## GO/NO-GO

**GO/NO-GO: GO**

Rationale: all three gates passed with real credentials against @ByteRelevant. Observed per-post cost of $0.03 yields ~$10.80/mo at target cadence — 2× below the budget floor, leaving ample headroom for future cost drift. OAuth 1.0a User Context confirmed Read+Write via a successful post+delete round-trip. Haiku 4.5 token cost is negligible. Phase 4 (Ingestion) may proceed.

**Cautions for Phase 7 (Publish):**
- `x-user-limit-24hour-*` headers were NOT present on this tier — the daily-cap guard in PUBLISH-04 must rely on the local `posts.posted_at` counter (already planned), NOT on response headers.
- Keep `MAX_MONTHLY_COST_USD` kill-switch (PUBLISH-05) conservative (~$25-30 initially) so one unexpected billing anomaly won't exhaust the envelope silently.
- Per-post cost is a single data point; monitor closely in the first week of live cadence and revise if the effective rate diverges from $0.03.
