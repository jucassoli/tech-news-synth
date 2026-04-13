# X API Baseline — Phase 3 Validation Gate

**Status:** PENDING — fill after running smoke scripts
**Last updated:** YYYY-MM-DD
**Operator:** <github-handle>
**Commit:** <git-sha-after-filling>

## Measurement Context

- **Account:** @ByteRelevant
- **Tier:** pay-per-use (X Free tier deprecated 2026-02-06)
- **cycle_id:** <ULID from smoke_x_post run, if generated>
- **Date of measurement:** YYYY-MM-DDTHH:MM:SSZ

## GATE-01 — Anthropic Haiku 4.5

- **Model id:** `claude-haiku-4-5`
- **Input tokens (sample):** <int>
- **Output tokens (sample):** <int>
- **Computed cost_usd (sample):** <float>
- **Pricing constants used:** $1.00/MTok input, $5.00/MTok output (last verified 2026-04-13)
- **Completion returned:** <quote the `completion_text` field>

## GATE-02 — X OAuth 1.0a User Context

- **`get_me()` username:** ByteRelevant
- **User id:** <numeric>
- **OAuth permissions:** Read+Write (inferred: GATE-03 post succeeded)

## GATE-03 — Live Post Round-Trip

- **tweet_id:** <numeric string>
- **posted_at:** <UTC ISO>
- **deleted_at:** <UTC ISO>
- **elapsed_ms (post only):** <int>
- **Rate-limit headers observed:**
  - `x-rate-limit-limit`: <value>
  - `x-rate-limit-remaining`: <value>
  - `x-rate-limit-reset`: <epoch>
  - `x-user-limit-24hour-limit`: <value or "absent">
  - `x-user-limit-24hour-remaining`: <value or "absent">
  - `x-user-limit-24hour-reset`: <value or "absent">
- **Daily cap (derived):** <integer posts/24h, from `x-user-limit-24hour-limit` if present>

## Observed USD/Post (manual paste from X billing portal)

- **Source:** X Developer Portal → Billing / Usage (URL at time of capture)
- **Observed USD/post:** <float> (single-sample; actual monthly burn may differ)
- **Note:** Scripts cannot read this programmatically; operator pastes value here.

## Cost Envelope Check (vs PROJECT.md budget $20-50/mo)

- **Target:** 12 posts/day × 30 days = 360 posts/month
- **Projected X cost/month:** 360 × <observed_usd_per_post> = $<float>
- **Projected Haiku cost/month:** 360 × <cost_usd sample from GATE-01> = $<float> (upper bound; real synthesis will use more tokens than the smoke prompt)
- **Total projected:** $<float>
- **Within $20-50/mo envelope?:** YES / NO

## How This Was Measured

- `scripts/smoke_anthropic.py` → GATE-01 values
- `scripts/smoke_x_auth.py` → GATE-02 values
- `scripts/smoke_x_post.py --arm-live-post` → GATE-03 values + rate-limit headers
- Observed USD/post: manual paste from X Developer Portal billing dashboard

## GO/NO-GO

**GO/NO-GO: PENDING — fill after smoke runs**

Rationale: <1-3 sentences. If NO-GO, document why (cost breach, auth failure, rate-limit concern) and what needs to change before Phase 4 can start.>
