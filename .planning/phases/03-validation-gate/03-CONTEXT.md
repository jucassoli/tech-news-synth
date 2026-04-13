# Phase 3: Validation Gate - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver three standalone smoke scripts and one intel document that prove the external economic and authentication premises of the project BEFORE Phase 4 ingestion work begins: (1) Anthropic API access with `claude-haiku-4-5` returns valid completions; (2) X OAuth 1.0a User Context with 4 secrets returns the @ByteRelevant handle (Read+Write confirmed); (3) a real tweet can be posted to @ByteRelevant and deleted, capturing daily-cap + rate-limit headers and observed cost. Deliver `.planning/intel/x-api-baseline.md` with a GO/NO-GO recommendation for Phase 4. Out of scope: any pipeline code (ingestion, clustering, synthesis, publish logic), any production-path use of tweepy.Client.create_tweet outside the smoke script, any DB writes.

</domain>

<decisions>
## Implementation Decisions

### Script Layout & Invocation
- **D-01:** Smoke scripts live in **`scripts/smoke_*.py`** as standalone argparse CLIs. Three files: `scripts/smoke_anthropic.py`, `scripts/smoke_x_auth.py`, `scripts/smoke_x_post.py`. Each imports `tech_news_synth.config.load_settings` to reuse `.env` loading and `SecretStr` hygiene. Not wired into `python -m tech_news_synth` — keeps the production CLI surface clean; scripts can be deleted in a future cleanup after v1 is stable.
- **D-02:** Scripts run **host-side via `uv run python scripts/smoke_*.py`**. Operator has `uv` installed (Phase 1 baseline). `.env` is read from the repo root (same path as the container mount) — no Docker daemon required for GATE-01/02/03. Scripts must NOT import anything that requires a running postgres.

### Live-Post Gate (GATE-03)
- **D-03:** `smoke_x_post.py` is **fully automated, no interactive prompt**, but **armed by an explicit flag**: the script refuses to run unless invoked with `--arm-live-post` (exits 2 with a big warning otherwise). This is a defense-in-depth replacement for the interactive `y/N` confirm — same safety guarantee (running the script by mistake doesn't post), no stdin coupling, better for automation records. The flag's literal token is required; no env-var alias.
- **D-04:** **Smoke tweet body** is a fixed harmless string with ISO-8601 UTC timestamp + marker: `[gate-smoke {utc_iso}] validating API access — this will be deleted within 60s`. Deterministic, grep-friendly, self-documenting for any human who sees it in the ~5-second window before deletion.
- **D-05:** On **delete failure after a successful post**, the script exits non-zero with a prominent stderr line: `MANUAL CLEANUP REQUIRED: tweet_id=<id> — delete at https://x.com/ByteRelevant/status/<id>`. No retry logic (keep the failure mode simple; rare path). The incident is captured in `x-api-baseline.md` if it occurs during the official gate run.

### Intel Doc (GATE-04)
- **D-06:** `.planning/intel/x-api-baseline.md` template structure (filled by operator after running smoke_x_post):
  - **API cost** — observed USD/post (pasted from X developer portal billing page after the test; scripts can't read this programmatically). Note: "single sample; actual monthly burn may differ."
  - **Daily cap** — extracted from `x-rate-limit-limit` response header on `create_tweet`.
  - **Rate-limit window** — `x-rate-limit-reset` + `x-rate-limit-remaining`.
  - **OAuth permissions** — Read+Write status from `get_me` response (inferred: post succeeded → write confirmed).
  - **Token cost (Haiku 4.5)** — input + output tokens × USD/1M from smoke_anthropic output.
  - **GO/NO-GO** — operator judgment: is the cost within the ~$20-50/mo budget envelope from PROJECT.md for 12 posts/day × 30 days?
  - **Date of measurement** + **tweet_id** + **cycle_id** (for audit trail).
- **D-07:** Intel doc is **versioned in git** (under `.planning/intel/`). Contains no secrets. May contain hashed identifiers (tweet_id is public; no PII).

### Claude's Discretion
- Exact `--arm-live-post` flag spelling (but MUST require explicit long-form opt-in).
- Argparse shape inside each smoke script.
- How `smoke_anthropic.py` formats token/cost output (table, JSON, or plain). Recommend JSON to stdout + human-readable stderr.
- Whether smoke scripts log via structlog (probably yes for consistency) or plain print (simpler; fine for one-shot tools). Claude picks.
- Retry policy on transient 5xx from Anthropic / X (recommend: no retries in smoke scripts — failure should surface immediately).
- Whether the three smoke scripts share a tiny `scripts/_common.py` helper (loads Settings, prints banner) — Claude picks based on DRY vs simplicity balance.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project context
- `.planning/PROJECT.md` — X pay-per-use decision, cost envelope, Haiku 4.5 model id
- `.planning/REQUIREMENTS.md` §GATE-01..GATE-04
- `.planning/ROADMAP.md` §"Phase 3: Validation Gate"
- `.planning/phases/01-foundations/01-CONTEXT.md` — D-01 package `tech_news_synth`, D-05 `python -m tech_news_synth` entry, SecretStr hygiene
- `.planning/phases/01-foundations/01-02-SUMMARY.md` — Settings class shape
- `CLAUDE.md` — tech stack (tweepy 4.14, anthropic 0.79)

### Research outputs
- `.planning/research/STACK.md` — anthropic 0.79 + Haiku 4.5 model id + tweepy 4.14 OAuth 1.0a
- `.planning/research/FEATURES.md` — cost envelope rationale

### External specs (read when implementing)
- tweepy `Client.get_me()` + `create_tweet()` + `delete_tweet()` — https://docs.tweepy.org/en/stable/client.html
- tweepy OAuth 1.0a User Context — https://docs.tweepy.org/en/stable/authentication.html
- Anthropic Python SDK `messages.create` — https://github.com/anthropics/anthropic-sdk-python
- Claude model pricing (Haiku 4.5) — https://platform.claude.com/docs/en/about-claude/models/overview
- X API v2 `create_tweet` response headers — https://developer.x.com/en/docs/twitter-api/rate-limits

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (from Phases 1-2)
- `tech_news_synth.config.load_settings()` — validates and loads `.env`. Smoke scripts call this for early fail-fast on missing secrets.
- `tech_news_synth.config.Settings` fields: `anthropic_api_key`, `x_consumer_key`, `x_consumer_secret`, `x_access_token`, `x_access_token_secret` (all `SecretStr`).
- `tech_news_synth.ids.new_cycle_id()` — ULID for correlating smoke runs in the baseline doc (optional but nice).
- `tech_news_synth.logging.configure_logging()` + `get_logger()` — smoke scripts CAN use it for JSON-line output; optional.

### Dependencies Already Pinned (pyproject.toml)
- `anthropic` (Phase 1 baseline)
- `tweepy>=4.14,<5` — need to verify this is already a dep; if not, Phase 3 adds it. Check pyproject.

### Established Patterns
- `SecretStr.get_secret_value()` to materialize before passing to SDK clients. Never log raw.
- `datetime.now(timezone.utc).isoformat()` for timestamps (Phase 1 UTC invariant).
- structlog for JSON logs; plain `print` is acceptable for one-shot operator tools.
- Tests live under `tests/unit/` or `tests/integration/`; smoke scripts are NOT in `src/`, so test import paths use `scripts/` directly or skip tests entirely.

### Integration Points
- `.env` at repo root — already used by Settings. Smoke scripts must NOT create a separate `.env.smoke`; everything loads from the single source.
- `.planning/intel/` directory — new for this phase. Future phases may add more intel files (source-health, cluster-quality, etc.).
- `scripts/` directory already exists (Phase 2 added `scripts/create_test_db.sh`). Phase 3 adds three `.py` files.

</code_context>

<specifics>
## Specific Ideas

- The `smoke_x_post.py` flow is strict-linear: load Settings → build tweepy.Client → create_tweet(body) → capture response + headers → delete_tweet(id) → print summary (JSON on stdout; human readable on stderr). No retries.
- The `--arm-live-post` flag is a literal string match; the script refuses if it's missing or misspelled.
- `smoke_anthropic.py` uses a minimal prompt like `"Responda apenas 'ok' em português."` to keep tokens (and cost) at floor-level. Print input+output token counts and computed USD cost using a hard-coded USD/1M-tokens constant referenced from Claude model docs.
- `smoke_x_auth.py` is strictly read-only (`get_me()`). Safe to run unarmed.

</specifics>

<deferred>
## Deferred Ideas

- **Automated cost scraping** — not possible without X portal API access; manual paste stays for v1.
- **Continuous cost monitoring** — Phase 8 (PUBLISH-05 `MAX_MONTHLY_COST_USD` kill-switch) handles this via summed `posts.cost_usd`; not a gate concern.
- **Pytest unit tests for smoke scripts** — scripts are operator tools run once per milestone; mocking the SDKs isn't worth the maintenance cost. If tests become needed later, `respx` + `pytest-mock` are the tools.
- **Multi-account / staging X handle** — operator has only @ByteRelevant; no staging account. If this becomes a problem, acquire a throwaway dev handle in a future milestone.
- **Backoff / retry for rate limits** — smoke scripts surface failure immediately; retry logic lives in Phase 7 publish code.
- **Containerized smoke runs** — runbook optionally documents `docker compose exec app uv run python scripts/smoke_*.py` but scripts are primarily host-run.

</deferred>

---

*Phase: 03-validation-gate*
*Context gathered: 2026-04-13 via /gsd-discuss-phase (inline)*
