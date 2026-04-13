# Phase 3: Validation Gate — Research

**Researched:** 2026-04-13
**Domain:** Live smoke tests against Anthropic Messages API (Haiku 4.5) + X API v2 (tweepy OAuth 1.0a User Context), plus an intel/baseline doc
**Confidence:** HIGH

## Summary

Phase 3 is a small, tightly-scoped gate phase: **three standalone argparse scripts under `scripts/smoke_*.py`** plus **`.planning/intel/x-api-baseline.md`**. There is no pipeline code, no DB, no container requirement. The research risks are narrow and concrete — three SDK-shape questions (Anthropic `messages.create` usage accounting, tweepy `Client` OAuth construction, and the non-obvious path to rate-limit headers in tweepy 4.14) plus one pricing-constants question (current Haiku 4.5 USD/MTok).

The single non-obvious finding that changes how plans should be written: **tweepy 4.14's default `Response` namedtuple DOES NOT expose HTTP headers.** `x-rate-limit-*` and `x-user-limit-24hour-*` headers — which are the whole reason GATE-03 exists — are only reachable if the `Client` is constructed with `return_type=requests.Response`. Every other detail is standard. [CITED: tweepy GitHub Discussion #1984; tweepy docs]

**Primary recommendation:** Build `smoke_x_post.py` with `tweepy.Client(..., return_type=requests.Response)` so headers are readable. Build `smoke_x_auth.py` with default `return_type=Response` (no headers needed — just `get_me()` username). Build `smoke_anthropic.py` as a single `messages.create(model="claude-haiku-4-5", ...)` call that prints `response.usage.input_tokens` + `response.usage.output_tokens` × module-level pricing constants to stdout as JSON.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01** — Three smoke scripts at `scripts/smoke_anthropic.py`, `scripts/smoke_x_auth.py`, `scripts/smoke_x_post.py`. Standalone argparse CLIs. Each imports `tech_news_synth.config.load_settings` for `.env` loading + `SecretStr` hygiene. **NOT wired into `python -m tech_news_synth`.**
- **D-02** — Scripts run host-side via `uv run python scripts/smoke_*.py`. **No Postgres, no Docker.** `.env` is read from repo root.
- **D-03** — `smoke_x_post.py` requires literal `--arm-live-post` flag. Without it: exits 2 with a stderr warning. No env-var alias, no interactive prompt.
- **D-04** — Smoke tweet body (fixed): `[gate-smoke {utc_iso}] validating API access — this will be deleted within 60s`.
- **D-05** — On delete failure after successful post: exit non-zero, stderr `MANUAL CLEANUP REQUIRED: tweet_id=<id> — delete at https://x.com/ByteRelevant/status/<id>`. **No retry logic.**
- **D-06** — Intel doc `.planning/intel/x-api-baseline.md` fields: API cost (manually pasted from dev portal), daily cap (from header), rate-limit window (from headers), OAuth permissions, token cost (from `smoke_anthropic`), GO/NO-GO, date, tweet_id, cycle_id.
- **D-07** — Intel doc committed to git under `.planning/intel/`. No secrets inside.

### Claude's Discretion

- Exact `--arm-live-post` spelling (must be explicit long-form).
- Argparse shape inside each script.
- Output format of `smoke_anthropic.py` (recommend: JSON on stdout + human banner on stderr).
- structlog vs plain `print` (recommend: plain `print` — one-shot tools don't need structlog's context machinery).
- Retry policy (recommend: **no retries** — failure must surface).
- Whether to share `scripts/_common.py` helper (recommend: **no** in v1 — three scripts, ~40 lines of overlap, DRY cost higher than benefit).

### Deferred Ideas (OUT OF SCOPE)

- Automated cost scraping from X portal.
- Continuous cost monitoring (lives in Phase 8 / PUBLISH-05).
- Pytest mocks of Anthropic/tweepy for these scripts.
- Staging X account.
- Backoff/retry on rate limits (Phase 7).
- Containerized smoke runs.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GATE-01 | Smoke script confirms Anthropic access to `claude-haiku-4-5` returns valid completion | §Anthropic SDK usage + §Haiku 4.5 Pricing Constants |
| GATE-02 | Smoke script confirms X OAuth 1.0a User Context via `client.get_me()` returns @ByteRelevant | §tweepy Client Construction + §`get_me()` Shape |
| GATE-03 | Smoke script posts one real tweet to @ByteRelevant, captures rate-limit/daily-cap headers, deletes tweet, prints observed cost-per-post | §`create_tweet` Response + §**Reading Rate-Limit Headers in tweepy 4.14** (critical) + §`delete_tweet` Semantics + §Arm-Live-Post Gate |
| GATE-04 | `.planning/intel/x-api-baseline.md` documents cost/cap/permissions + GO/NO-GO | §Intel Doc Template |

</phase_requirements>

## Project Constraints (from CLAUDE.md)

- Python 3.12 (pinned in pyproject: `>=3.12,<3.13`).
- All timestamps UTC — use `datetime.now(timezone.utc).isoformat()`.
- Secrets are `SecretStr`; `.get_secret_value()` only at SDK boundary; never log raw.
- No secrets in git. Intel doc under `.planning/intel/` must contain zero secrets (verified manually + by existing pre-commit hook).
- Tech stack authoritative: `anthropic>=0.79,<0.80`, `tweepy>=4.14,<5` — **both already present** in `pyproject.toml`. No dep additions required.
- Ruff lint: `E, F, I, UP, B, DTZ, RUF`. `DTZ` means naive `datetime.now()` is forbidden — must use `datetime.now(timezone.utc)`.
- Tests live under `tests/unit/` or `tests/integration/`.

## Standard Stack

### Already Pinned (no change needed)

| Library | Version (pyproject) | Purpose | Verified |
|---------|---------------------|---------|----------|
| `anthropic` | `>=0.79,<0.80` | Claude Haiku 4.5 `messages.create` | [VERIFIED: pyproject.toml line 10] |
| `tweepy` | `>=4.14,<5` | X v2 `Client.create_tweet` / `get_me` / `delete_tweet` via OAuth 1.0a User Context | [VERIFIED: pyproject.toml line 11] |
| `pydantic-settings` | `>=2.6,<3` | `.env` + `SecretStr` — already loaded via `Settings` | [VERIFIED: pyproject.toml + src/tech_news_synth/config.py] |
| `python-ulid` | `>=3,<4` | `cycle_id` generation for intel doc audit trail (optional) | [VERIFIED: pyproject.toml line 24] |

### Dev dependencies (no additions needed)

Scripts are operator tools; no unit-test harness is required by CONTEXT.md. If the "tiny argparse gate test" recommendation in §Validation Architecture is accepted, `pytest>=8` is already present — no new dev dep needed.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `tweepy.Client` | Raw `requests` + OAuth1Session | More code; tweepy is already pinned and idiomatic. Reject. |
| `anthropic` SDK | Raw `httpx` POST to `/v1/messages` | Loses token-usage parsing conveniences; project standardizes on SDK. Reject. |
| structlog in smoke scripts | Plain `print` / `json.dumps` | For single-run operator tools, structlog's contextvar machinery is overhead without benefit. Recommend plain print per CONTEXT D-discretion. |

## Architecture Patterns

### Script Layout

```
scripts/
├── create_test_db.sh          # existing (Phase 2)
├── smoke_anthropic.py         # NEW — GATE-01
├── smoke_x_auth.py            # NEW — GATE-02
└── smoke_x_post.py            # NEW — GATE-03
```

Each script is ~60-120 lines, top-to-bottom linear. No shared helper in v1 (three scripts, low overlap — DRY would be premature).

### Pattern 1: Minimal Anthropic Smoke (GATE-01)

```python
# scripts/smoke_anthropic.py
"""GATE-01: confirm Anthropic access to claude-haiku-4-5.

Usage:
    uv run python scripts/smoke_anthropic.py [--prompt TEXT]

Exits:
    0 — completion received, token cost printed
    1 — Anthropic error (auth, model, network)
    2 — config error (missing ANTHROPIC_API_KEY)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from anthropic import Anthropic, APIError

from tech_news_synth.config import load_settings

# --- Pricing constants ---------------------------------------------------
# Claude Haiku 4.5 — USD per 1M tokens (BASE, no caching).
# Last verified: 2026-04-13 against https://platform.claude.com/docs/en/about-claude/pricing
HAIKU_4_5_INPUT_USD_PER_MTOK = 1.00
HAIKU_4_5_OUTPUT_USD_PER_MTOK = 5.00
MODEL_ID = "claude-haiku-4-5"


def main() -> int:
    parser = argparse.ArgumentParser(description="GATE-01 Anthropic smoke test.")
    parser.add_argument("--prompt", default="Responda apenas 'ok' em português.")
    parser.add_argument("--max-tokens", type=int, default=32)
    args = parser.parse_args()

    try:
        settings = load_settings()
    except Exception:
        return 2  # load_settings already wrote to stderr

    client = Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
    started_at = datetime.now(timezone.utc)
    try:
        resp = client.messages.create(
            model=MODEL_ID,
            max_tokens=args.max_tokens,
            messages=[{"role": "user", "content": args.prompt}],
        )
    except APIError as e:
        print(f"Anthropic API error: {e}", file=sys.stderr)
        return 1

    finished_at = datetime.now(timezone.utc)
    in_tok = resp.usage.input_tokens
    out_tok = resp.usage.output_tokens
    cost_usd = (
        in_tok / 1_000_000 * HAIKU_4_5_INPUT_USD_PER_MTOK
        + out_tok / 1_000_000 * HAIKU_4_5_OUTPUT_USD_PER_MTOK
    )
    # response.content is a list of content blocks; text block is [0].text
    completion = resp.content[0].text if resp.content else ""

    summary = {
        "phase": "GATE-01",
        "model": MODEL_ID,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_s": (finished_at - started_at).total_seconds(),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": round(cost_usd, 8),
        "completion": completion,
    }
    print(json.dumps(summary, indent=2))
    print("GATE-01 OK", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

[CITED: https://platform.claude.com/docs/en/about-claude/pricing — pricing table fetched 2026-04-13]

### Pattern 2: tweepy OAuth 1.0a User Context — Construction

**Exact constructor** [CITED: tweepy 4.14 docs, github.com/tweepy/tweepy client.py]:

```python
import tweepy

client = tweepy.Client(
    consumer_key=settings.x_consumer_key.get_secret_value(),
    consumer_secret=settings.x_consumer_secret.get_secret_value(),
    access_token=settings.x_access_token.get_secret_value(),
    access_token_secret=settings.x_access_token_secret.get_secret_value(),
    # DO NOT pass bearer_token — that forces OAuth 2.0 app-only and breaks writes
    # wait_on_rate_limit defaults to False — keep it False in smoke scripts (fail fast)
)
```

Full signature (positional + keyword-only) [CITED: tweepy source code]:

```python
class tweepy.Client(
    bearer_token=None,
    consumer_key=None,
    consumer_secret=None,
    access_token=None,
    access_token_secret=None,
    *,
    return_type=tweepy.Response,       # ⚠ default — namedtuple without headers
    wait_on_rate_limit=False,
)
```

For `smoke_x_auth.py` (no header access needed), use the default `return_type`. For `smoke_x_post.py` (headers ARE needed), **override to `requests.Response`** — see Pattern 3.

### Pattern 3: Reading X Rate-Limit Headers in tweepy 4.14 (CRITICAL)

**The non-obvious finding.** The default `tweepy.Response` is a `collections.namedtuple` with fields `(data, includes, errors, meta)` — **no headers, no raw response**. The tweepy maintainers explicitly refused to add a headers field before a v5 release (breaking change). [CITED: https://github.com/tweepy/tweepy/discussions/1984]

**The workaround** is documented: construct the `Client` with `return_type=requests.Response`. Then every method (`create_tweet`, `delete_tweet`, `get_me`) returns a raw `requests.Response` whose `.headers` dict exposes `x-rate-limit-*` and `x-user-limit-24hour-*`. [CITED: tweepy docs client.py — `return_type: Type[Union[dict, requests.Response, Response]]`]

```python
import requests
import tweepy

client = tweepy.Client(
    consumer_key=...,
    consumer_secret=...,
    access_token=...,
    access_token_secret=...,
    return_type=requests.Response,   # ← critical override
)

# create_tweet — now returns a requests.Response
r = client.create_tweet(text=body)
assert isinstance(r, requests.Response)

# body — JSON payload at .json()["data"]
tweet_id = r.json()["data"]["id"]

# headers — now accessible
daily_cap = r.headers.get("x-user-limit-24hour-limit")            # e.g. "100"
daily_remaining = r.headers.get("x-user-limit-24hour-remaining")  # e.g. "99"
daily_reset = r.headers.get("x-user-limit-24hour-reset")          # unix ts
rate_limit = r.headers.get("x-rate-limit-limit")
rate_remaining = r.headers.get("x-rate-limit-remaining")
rate_reset = r.headers.get("x-rate-limit-reset")
```

**Header names verified** [CITED: devcommunity.x.com Basic Plan investigation thread]:
- `x-user-limit-24hour-limit`, `x-user-limit-24hour-remaining`, `x-user-limit-24hour-reset` — the **daily cap** (what the intel doc wants).
- `x-rate-limit-limit`, `x-rate-limit-remaining`, `x-rate-limit-reset` — the **per-endpoint window** (usually 15 min for v2 posting).

Both sets must be captured and recorded in the intel doc.

### Pattern 4: Live-Post Smoke (GATE-03) — Full Skeleton

```python
# scripts/smoke_x_post.py
"""GATE-03: post+delete one real tweet; capture rate-limit / daily-cap headers.

REQUIRES --arm-live-post. Running without it exits 2 (safe no-op).

Usage:
    uv run python scripts/smoke_x_post.py --arm-live-post

Exits:
    0 — posted and deleted cleanly, summary JSON on stdout
    1 — post failed (auth/429/network) OR delete failed (see MANUAL CLEANUP line)
    2 — missing --arm-live-post flag, or config error
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

import requests
import tweepy

from tech_news_synth.config import load_settings
from tech_news_synth.ids import new_cycle_id  # optional — ULID for audit trail

ARM_FLAG = "--arm-live-post"
ARM_WARNING = (
    "REFUSED: smoke_x_post.py will publish a REAL tweet to @ByteRelevant.\n"
    "This script refuses to run without the explicit arming flag.\n"
    f"To proceed: uv run python scripts/smoke_x_post.py {ARM_FLAG}\n"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="GATE-03 X live-post smoke.")
    parser.add_argument("--arm-live-post", action="store_true", required=False)
    args = parser.parse_args()

    if not args.arm_live_post:
        print(ARM_WARNING, file=sys.stderr)
        return 2

    try:
        settings = load_settings()
    except Exception:
        return 2

    cycle_id = new_cycle_id()
    body = (
        f"[gate-smoke {datetime.now(timezone.utc).isoformat()}] "
        "validating API access — this will be deleted within 60s"
    )
    assert len(body) <= 280, f"smoke body too long: {len(body)}"

    client = tweepy.Client(
        consumer_key=settings.x_consumer_key.get_secret_value(),
        consumer_secret=settings.x_consumer_secret.get_secret_value(),
        access_token=settings.x_access_token.get_secret_value(),
        access_token_secret=settings.x_access_token_secret.get_secret_value(),
        return_type=requests.Response,
    )

    # --- POST -----------------------------------------------------------
    post_started = datetime.now(timezone.utc)
    try:
        post_resp: requests.Response = client.create_tweet(text=body)
        post_resp.raise_for_status()
    except (tweepy.TweepyException, requests.HTTPError) as e:
        print(f"create_tweet FAILED: {e}", file=sys.stderr)
        return 1
    post_finished = datetime.now(timezone.utc)

    tweet_id = post_resp.json()["data"]["id"]
    headers = dict(post_resp.headers)

    # --- DELETE ---------------------------------------------------------
    try:
        del_resp: requests.Response = client.delete_tweet(id=tweet_id)
        del_resp.raise_for_status()
        delete_ok = True
    except (tweepy.TweepyException, requests.HTTPError) as e:
        delete_ok = False
        # D-05: MANUAL CLEANUP banner
        print(
            f"MANUAL CLEANUP REQUIRED: tweet_id={tweet_id} — "
            f"delete at https://x.com/ByteRelevant/status/{tweet_id}\n"
            f"reason: {e}",
            file=sys.stderr,
        )

    summary = {
        "phase": "GATE-03",
        "cycle_id": cycle_id,
        "tweet_id": tweet_id,
        "post_started_at": post_started.isoformat(),
        "post_finished_at": post_finished.isoformat(),
        "post_duration_s": (post_finished - post_started).total_seconds(),
        "delete_ok": delete_ok,
        "rate_limit": {
            "limit": headers.get("x-rate-limit-limit"),
            "remaining": headers.get("x-rate-limit-remaining"),
            "reset": headers.get("x-rate-limit-reset"),
        },
        "daily_cap": {
            "limit": headers.get("x-user-limit-24hour-limit"),
            "remaining": headers.get("x-user-limit-24hour-remaining"),
            "reset": headers.get("x-user-limit-24hour-reset"),
        },
    }
    print(json.dumps(summary, indent=2))
    return 0 if delete_ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

### Pattern 5: Auth Smoke (GATE-02) — Minimal

`smoke_x_auth.py` is read-only — `get_me()` — and does not need header access. Default `return_type` is fine.

```python
client = tweepy.Client(
    consumer_key=..., consumer_secret=...,
    access_token=..., access_token_secret=...,
)
resp = client.get_me()  # returns tweepy.Response namedtuple
# resp.data is a User model with .id, .name, .username
if resp.data is None:
    print("get_me returned no data (auth invalid?)", file=sys.stderr)
    return 1
username = resp.data.username
# Verify expected handle:
if username != "ByteRelevant":
    print(f"UNEXPECTED HANDLE: got @{username}, expected @ByteRelevant", file=sys.stderr)
    return 1
```

[CITED: tweepy docs `get_me()` — returns Response with `.data` as User model]

**Write-permission inference:** `get_me()` succeeding proves tokens are valid. It does NOT prove tokens have Write scope — only `create_tweet` does. That's why GATE-03 exists as a separate gate, not a flag on GATE-02.

### Anti-Patterns to Avoid

- **Passing `bearer_token=` AND the 4 OAuth1 secrets** — tweepy picks bearer; `create_tweet` fails with 403. Pass only the 4 secrets. [CITED: PITFALLS.md §2]
- **Assuming `tweepy.Response.meta` or `.includes` contains headers** — it does not. Only `return_type=requests.Response` surfaces headers. [CITED: tweepy Discussion #1984]
- **Retrying on 429 inside the smoke script** — CONTEXT.md D-03/D-05 say fail fast; retry logic is Phase 7's problem.
- **Logging `SecretStr.get_secret_value()` output** — the whole point of SecretStr is that `repr()` shows `'**********'`. Never print the materialized value. Only pass it to SDK clients. [CITED: config.py docstring + PITFALLS #7 T-01-03]
- **Using `structlog` in a one-shot script for JSON summary** — overkill. `json.dumps(summary)` on stdout + `print(..., file=sys.stderr)` for banners is cleaner and more machine-parseable.
- **Hard-coding the model id as `claude-3-haiku-20240307` or `claude-haiku-3-5`** — both deprecated (Haiku 3 retires 2026-04-19, one week from this research). Use `claude-haiku-4-5`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| OAuth 1.0a signing for X | Custom HMAC-SHA1 signer | `tweepy.Client(consumer_key=..., ...)` | Nonce/timestamp/signature base string is a classic footgun; tweepy is tested. |
| Parsing Anthropic `/v1/messages` response | Custom JSON parser | `anthropic.Anthropic().messages.create(...)` → `.usage.input_tokens` | SDK already handles retries/typing; no reason to reimplement. |
| Rate-limit header parsing | String manipulation | `requests.Response.headers.get(...)` after `return_type=requests.Response` | `requests` gives a dict-like case-insensitive header map. |
| Generating correlation IDs | `uuid4().hex[:8]` or timestamp strings | `tech_news_synth.ids.new_cycle_id()` (ULID) | Already implemented in Phase 1 (D-09). Time-sortable, 26 chars. |
| Loading `.env` + validating secrets | Custom `os.environ` reads | `tech_news_synth.config.load_settings()` | Phase 1 built this with `SecretStr` + fail-fast validation. |

**Key insight:** Phase 1 already built every non-SDK piece these smoke scripts need. The value added in Phase 3 is SDK glue + one-shot operator UX (JSON summary + arm gate) — nothing more.

## Haiku 4.5 Pricing Constants (Verified 2026-04-13)

| Tier | Input ($/MTok) | Output ($/MTok) |
|------|----------------|-----------------|
| Base (standard) | **$1.00** | **$5.00** |
| 5m cache write | $1.25 | — |
| 1h cache write | $2.00 | — |
| Cache read | $0.10 | — |
| Batch API (50% off) | $0.50 | $2.50 |

[CITED: https://platform.claude.com/docs/en/about-claude/pricing — pricing table for "Claude Haiku 4.5" row, fetched 2026-04-13]

Smoke script uses **base tier only** (no caching, no batch). Hard-code as module-level constants:

```python
HAIKU_4_5_INPUT_USD_PER_MTOK = 1.00     # last verified 2026-04-13
HAIKU_4_5_OUTPUT_USD_PER_MTOK = 5.00    # last verified 2026-04-13
```

**Sanity sample:** 500 input tokens + 30 output tokens ≈ `500/1e6 × $1 + 30/1e6 × $5 = $0.0005 + $0.00015 = $0.00065 per call`. Negligible for gate purposes.

**Estimated monthly envelope** (for intel doc GO/NO-GO math): 12 posts/day × 30 days × ~2000 in + ~150 out tokens ≈ `720 × (2000×$1 + 150×$5) / 1e6 = 720 × ($0.002 + $0.00075) = ~$2/month` on Anthropic side. The dominant cost is X posting, not LLM. This matches the PROJECT.md "$20-50/mo" envelope (80-90% X, <10% LLM).

## X API v2 Pay-Per-Use Cost Mechanics

**Cannot be read programmatically from the API.** X exposes per-post cost only in the developer portal billing UI. The smoke script:
- captures `tweet_id`, timestamps, and rate-limit/daily-cap headers,
- prints the time window of the post (so operator knows which row to look up),
- **operator manually pastes the USD cost** from the billing dashboard into `x-api-baseline.md`.

[ASSUMED] This matches tweepy/X API v2's documented surface — no "cost" response header is standard. If X later adds one, the intel doc can be updated.

## Common Pitfalls

### Pitfall 1: Default tweepy Response drops headers silently

**What goes wrong:** Script calls `client.create_tweet(...)`, gets a `tweepy.Response` namedtuple, tries `response.headers` → `AttributeError`. Operator assumes headers are missing and writes them as "unknown" in the intel doc — losing the daily cap data that's the whole point of GATE-03.

**Why:** Default `return_type=tweepy.Response` is `(data, includes, errors, meta)` only. No headers by design. [CITED: Discussion #1984]

**How to avoid:** Explicitly pass `return_type=requests.Response` in `smoke_x_post.py`. Add a one-line comment explaining why, so future maintainers don't "simplify" it away.

**Warning signs:** `AttributeError: 'Response' object has no attribute 'headers'`, or intel doc rows with `daily_cap: null`.

### Pitfall 2: App Read-only permission silently breaks create_tweet

**What goes wrong:** X dev portal defaults apps to Read-only. `get_me()` works. `create_tweet` returns 403 Forbidden with a cryptic message. If permission was changed Read→Write AFTER tokens were generated, old tokens are still Read-only — must regenerate. [CITED: PITFALLS.md §2]

**How to avoid:** Before running GATE-02/03, operator verifies in X dev portal:
1. App has **Read and Write** permission.
2. Access tokens were generated (or regenerated) AFTER setting Read+Write.

Document this as a **manual pre-flight step** in the Phase 3 runbook.

**Warning signs:** GATE-02 passes, GATE-03 fails with 403. The error message names "oauth 1.0a user context" and/or "elevated access".

### Pitfall 3: Delete fails — leaving the smoke tweet live on @ByteRelevant

**What goes wrong:** Post succeeds, delete throws (network blip, rare 5xx). Without a prominent alert, operator closes the terminal and the gate-smoke tweet sits on the public account until noticed. CONTEXT.md D-05 mandates a loud stderr banner.

**How to avoid:** Surround `delete_tweet` in try/except, print the `MANUAL CLEANUP REQUIRED: tweet_id=... — delete at https://x.com/ByteRelevant/status/<id>` banner to **stderr**, exit non-zero. Do **not** retry (D-05).

**Warning signs:** Non-zero exit from `smoke_x_post.py` after a successful post. Check stderr for the banner.

### Pitfall 4: Smoke tweet consumes pay-per-use credits silently

**What goes wrong:** Every run of `smoke_x_post.py --arm-live-post` burns one real post from the daily cap + incurs real USD cost. Running it 5 times during debugging = 5 posts = ~5¢-25¢ + 5 of the daily cap used up. If run in a loop by mistake, could burn a whole day's quota.

**How to avoid:**
- `--arm-live-post` flag (D-03) prevents accidental invocation.
- Runbook states: "run this ONCE per gate cycle, then document results in `x-api-baseline.md`".
- **Never** add retry logic to this script.

**Warning signs:** X portal shows multiple smoke posts in a short window; daily-cap `remaining` drops faster than expected.

### Pitfall 5: Logging SecretStr value leaks credentials

**What goes wrong:** Debug `print(settings)` is safe (SecretStr renders `'**********'`). But `print(settings.anthropic_api_key.get_secret_value())` prints the raw key. In a script that eventually gets `tee`'d to a log file, this leaks the credential to disk / screen-share / CI artifact. [CITED: config.py docstring T-01-03, PITFALLS.md]

**How to avoid:** The ONLY place `.get_secret_value()` appears in Phase 3 code is inline in the SDK constructor arguments. Never assign to a variable, never pass to `print`, never include in the JSON summary.

**Warning signs:** Any string starting `sk-ant-` visible in stdout / stderr / logs.

## Runtime State Inventory

**Skipped** — Phase 3 is greenfield (new files under `scripts/` and `.planning/intel/`). No rename, refactor, or migration. No stored state to audit.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `uv` | host-side script invocation | ✓ (Phase 1 baseline) | — | `python` direct if venv activated |
| `python>=3.12` | all scripts | ✓ | 3.12 | — |
| `anthropic` | GATE-01 | ✓ (pyproject) | 0.79.x | — |
| `tweepy` | GATE-02, GATE-03 | ✓ (pyproject) | 4.14.x | — |
| `requests` | GATE-03 (`return_type=requests.Response`) | ✓ (tweepy transitive) | 2.32+ | — |
| `.env` with 5 secrets | all scripts | [VERIFIED: present as `.env.example`] — operator copies to `.env` and fills real values | — | — |
| Network egress to `api.anthropic.com` | GATE-01 | [ASSUMED: VPS/host has internet] | — | — |
| Network egress to `api.twitter.com` / `api.x.com` | GATE-02, GATE-03 | [ASSUMED] | — | — |
| X Developer Portal: app in Read+Write + tokens generated AFTER | GATE-03 | **MANUAL PRE-FLIGHT** — operator must verify | — | No fallback; gate fails |
| Anthropic account with credit balance > $0 | GATE-01 | **MANUAL PRE-FLIGHT** — operator verifies billing | — | No fallback |
| X developer account with pay-per-use enabled + billing card | GATE-03 | **MANUAL PRE-FLIGHT** | — | No fallback |

**Missing dependencies with no fallback:** none (scripts self-contained; all deps already pinned).

**Missing dependencies with fallback:** none.

**Manual pre-flight checklist** (runbook, not code):
1. Operator has valid `.env` with all 5 secrets filled.
2. X app is **Read and Write**.
3. X access tokens were generated AFTER setting Read+Write.
4. Anthropic account has credit balance.
5. X developer account has pay-per-use + billing enabled.

## `.env.example` Status

[VERIFIED] — all 5 secrets for Phase 3 are already declared in `.env.example` (Phase 1 baseline). No additions needed:

- `ANTHROPIC_API_KEY` ✓
- `X_CONSUMER_KEY` ✓
- `X_CONSUMER_SECRET` ✓
- `X_ACCESS_TOKEN` ✓
- `X_ACCESS_TOKEN_SECRET` ✓

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x [VERIFIED: pyproject.toml line 34] |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (pythonpath=`src`, testpaths=`tests`) |
| Quick run command | `uv run pytest tests/unit/ -q` |
| Full suite command | `uv run pytest tests/ -q` |

### Phase Requirements → Test Map

Per CONTEXT.md, smoke scripts are operator tools — full unit tests that mock the SDKs are **deferred**. However, one thin test per script verifies the argparse gate logic without SDK calls. These are cheap (~5 lines each), prevent the `--arm-live-post` safety regressing, and run in the normal `pytest` suite.

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| GATE-01 | `smoke_anthropic.py` calls Haiku 4.5 and prints token/cost summary | manual-only (operator run) | `uv run python scripts/smoke_anthropic.py` → check exit 0 + JSON | ❌ Wave 0 |
| GATE-02 | `smoke_x_auth.py` → `get_me()` returns `ByteRelevant` | manual-only (operator run) | `uv run python scripts/smoke_x_auth.py` → check exit 0 + username | ❌ Wave 0 |
| GATE-03 | `smoke_x_post.py --arm-live-post` posts, captures headers, deletes | manual-only (operator run, one-shot) | `uv run python scripts/smoke_x_post.py --arm-live-post` | ❌ Wave 0 |
| GATE-03 (safety) | `smoke_x_post.py` with no flag refuses and exits 2 | unit (argparse only) | `pytest tests/unit/test_smoke_arm_gate.py -x` | ❌ Wave 0 |
| GATE-04 | `.planning/intel/x-api-baseline.md` exists + all fields populated | manual — doc review | `test -s .planning/intel/x-api-baseline.md && grep -q 'GO\|NO-GO' .planning/intel/x-api-baseline.md` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/unit/ -q` (runs the one argparse-gate test + existing 64 tests).
- **Per wave merge:** `uv run pytest tests/ -q` (full suite; Phase 3 adds no integration tests).
- **Phase gate:** operator runs all three smoke scripts manually, records results in `x-api-baseline.md`, commits the doc. `/gsd-verify-work` confirms file exists + fields populated + commit present.

### Wave 0 Gaps

- [ ] `scripts/smoke_anthropic.py` — covers GATE-01
- [ ] `scripts/smoke_x_auth.py` — covers GATE-02
- [ ] `scripts/smoke_x_post.py` — covers GATE-03 (functional + arm-gate)
- [ ] `tests/unit/test_smoke_arm_gate.py` — argparse-only test that `smoke_x_post.py` exits 2 without `--arm-live-post`
- [ ] `.planning/intel/` directory (new) + `x-api-baseline.md` (operator-filled, committed)
- [ ] Runbook notes (can live in commit body or a `scripts/README.md`) documenting pre-flight checklist + smoke invocation order

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | yes | `tweepy.Client` OAuth 1.0a User Context (4 secrets); `Anthropic(api_key=...)` — reuse SDK auth |
| V3 Session Management | no | no user sessions; these are machine-to-API calls |
| V4 Access Control | partial | `--arm-live-post` flag is a human-in-the-loop control, not a permission check |
| V5 Input Validation | minimal | smoke tweet body is a fixed template (D-04); no user-supplied content |
| V6 Cryptography | yes (via SDK) | OAuth 1.0a HMAC-SHA1 signing is tweepy's responsibility — do NOT reimplement |
| V7 Error Handling | yes | errors must not leak secrets; failures surface to stderr with SDK-provided messages only |
| V10 Malicious Code | yes | smoke scripts must not execute user-supplied strings |

### Known Threat Patterns for Phase 3

| Threat ID | Pattern | STRIDE | Mitigation |
|-----------|---------|--------|------------|
| T-03-01 | Secret leak in script stdout/stderr | Information Disclosure | SecretStr + `.get_secret_value()` inline in SDK constructor only; never `print()` secrets; JSON summary excludes secrets by construction |
| T-03-02 | Accidental live post during debugging | Tampering (self-inflicted) | D-03 `--arm-live-post` gate: argparse `action="store_true"`, exit 2 if absent, loud warning banner |
| T-03-03 | Tweet delete fails → gate-smoke tweet stays public on @ByteRelevant | Tampering (reputational) | D-05 MANUAL CLEANUP banner on stderr + non-zero exit; accepted residual risk (no retry) |
| T-03-04 | Rate-limit / daily-cap depletion during smoke | Denial of Service (self-inflicted) | Smoke runs ONCE per gate cycle; no retry; `--arm-live-post` prevents unintentional loops |
| T-03-05 | API key leaked via `x-api-baseline.md` commit | Information Disclosure | D-07 explicit "no secrets in intel doc"; pre-commit hook from INFRA-04 scans for leaked secrets; template has no secret fields |
| T-03-06 | Smoke tweet text injection / XSS-like attack in post body | Tampering | N/A — body is fixed template (D-04); no dynamic content |
| T-03-07 | Haiku model-id drift (hard-coded wrong id) | Availability | Hard-code `claude-haiku-4-5` once in `smoke_anthropic.py`; same constant is used by Phase 6 — single source of truth check at phase boundary |

## Intel Doc Template (GATE-04)

Proposed skeleton for `.planning/intel/x-api-baseline.md` — operator fills bracketed fields after running smoke scripts. **No secrets anywhere in this doc.**

```markdown
# X API + Anthropic Baseline

**Measured:** [YYYY-MM-DD HH:MM UTC]
**Cycle ID:** [ULID from smoke_x_post.py summary]
**Account:** @ByteRelevant
**Anthropic model:** claude-haiku-4-5
**Measured by:** [operator name/handle]

## GATE-01 — Anthropic Smoke

| Field | Value |
|-------|-------|
| Exit code | [0] |
| Input tokens | [N] |
| Output tokens | [N] |
| Computed cost USD | [$0.00065] |
| Duration (s) | [X] |
| Completion text | `[ok]` |

Pricing constants used (verified 2026-04-13):
- Input: $1.00 / 1M tokens
- Output: $5.00 / 1M tokens

## GATE-02 — X OAuth Smoke

| Field | Value |
|-------|-------|
| Exit code | [0] |
| Handle returned | @[ByteRelevant] |
| OAuth flow | OAuth 1.0a User Context (4 secrets) |
| App permissions (verified in dev portal) | [Read and Write] |

## GATE-03 — X Live Post + Delete

| Field | Value |
|-------|-------|
| Exit code | [0] |
| Tweet ID | [numeric string] |
| Post duration (s) | [X] |
| Delete succeeded | [yes] |
| `x-user-limit-24hour-limit` (daily cap) | [N] |
| `x-user-limit-24hour-remaining` | [N] |
| `x-user-limit-24hour-reset` (unix ts) | [N → ISO: YYYY-MM-DDTHH:MM:SSZ] |
| `x-rate-limit-limit` (per-endpoint window) | [N] |
| `x-rate-limit-remaining` | [N] |
| `x-rate-limit-reset` | [N → ISO] |

## Observed Cost per Post

| Field | Value |
|-------|-------|
| Source | X Developer Portal → Billing (manual lookup) |
| Date of billing entry | [YYYY-MM-DD] |
| USD charged for this post | [$0.00NN] |
| Notes | Single sample; monthly burn may differ. |

## Budget Projection

Assuming 12 posts/day × 30 days = 360 posts/month:

| Component | Unit cost | Monthly |
|-----------|-----------|---------|
| X post (pay-per-use) | $[0.00NN] | $[N.NN] |
| Anthropic Haiku 4.5 (~2000 in + ~150 out per post) | ~$0.0028/post | ~$1.00 |
| **Total estimate** | | **$[N.NN]** |

PROJECT.md envelope: $20-50/month.

## OAuth Permissions State

- Confirmed Read+Write via successful `create_tweet` in GATE-03.
- Access tokens were generated/regenerated on [YYYY-MM-DD] after setting Read+Write.

## GO / NO-GO Decision

**Decision:** [GO | NO-GO]
**Rationale:** [one paragraph — does projected monthly cost fit envelope? Are caps sufficient for 12 posts/day? Any anomalies in headers?]
**Next step:** [Proceed to Phase 4 | Revise cadence to N posts/day | Escalate]

## How This Was Measured

1. `uv run python scripts/smoke_anthropic.py` — one `messages.create` call against `claude-haiku-4-5` with a minimal PT-BR prompt; token counts + computed USD cost in JSON summary.
2. `uv run python scripts/smoke_x_auth.py` — one `client.get_me()` call with OAuth 1.0a User Context; username verified == "ByteRelevant".
3. `uv run python scripts/smoke_x_post.py --arm-live-post` — one `create_tweet` + one `delete_tweet` cycle; rate-limit + daily-cap headers captured via `return_type=requests.Response`.
4. Per-post USD cost pasted from X Developer Portal billing dashboard (not readable from API).

## Audit Trail

- `smoke_anthropic.py` JSON summary: [paste here]
- `smoke_x_post.py` JSON summary: [paste here]
- Commit containing this doc: [git sha]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| X Free tier (500 posts/month) | Pay-per-use default | 2026-02-06 | All new X dev accounts are metered; cost envelope required. [CITED: PITFALLS.md §1] |
| Haiku 3 (`claude-3-haiku-20240307`) | Haiku 4.5 (`claude-haiku-4-5`) | Haiku 3 retires 2026-04-19 (6 days after this research) | Must use `claude-haiku-4-5` or builds break in one week. [CITED: Anthropic model deprecations page] |
| `tweepy.API` (v1.1 endpoints) | `tweepy.Client` (v2) with OAuth 1.0a User Context | v1.1 endpoints paywalled/deprecated for posting | Use `Client.create_tweet`, not `API.update_status`. [CITED: CLAUDE.md STACK] |

**Deprecated / outdated:**
- `claude-3-haiku-20240307` — retires 2026-04-19.
- `tweepy.API.update_status` — v1.1 endpoint.
- `anthropic` SDK <0.49 — predates Haiku 4.5 ids.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | X API response headers use `x-user-limit-24hour-*` (daily cap) in addition to `x-rate-limit-*` | §Pattern 3 | Low — script reads both sets with `.get()`; missing keys yield `None`, recorded as-is in intel doc. No crash. Source: devcommunity.x.com Basic Plan thread — may differ per-tier. |
| A2 | X does not expose per-post USD cost in any response header | §X Pay-Per-Use Cost Mechanics | Low — intel doc template already plans for manual billing-portal lookup. If a header exists, template can be updated. |
| A3 | `response.content[0].text` is the correct path for Haiku 4.5 completion text | §Pattern 1 | Low — standard `anthropic` SDK response shape since 0.49+. If the content block order changes (e.g., tool use), smoke script would need to filter for `type == "text"`. For Phase 3's minimal prompt, only one text block returns. |
| A4 | VPS / operator host has network egress to `api.anthropic.com` and `api.x.com` | §Environment Availability | High if wrong — gate fails entirely. But this is a baseline assumption; operator runs these scripts on the same host where the production agent will run. |
| A5 | `.get_secret_value()` output is not captured by pytest's stderr/stdout capture in a way that ends up in CI artifacts | §Security T-03-01 | Low — smoke scripts never print secret values; argparse-gate unit test never constructs SDK clients. |

**The planner should treat A1 as the highest-risk assumption:** if the observed header names differ from the documented set, the intel doc's "daily cap" field may be blank. Plan should record whatever headers ARE present (store full `dict(response.headers)` in the JSON summary as a debug field) so the operator has raw data even if specific keys are missing.

## Open Questions

1. **Should the argparse-gate unit test actually invoke `smoke_x_post.main()` as a subprocess, or import and call it directly?**
   - What we know: invoking `main()` with no flag returns 2 cleanly without touching the network.
   - What's unclear: whether running as a subprocess (via `subprocess.run([sys.executable, "scripts/smoke_x_post.py"])`) is more faithful to the real invocation path.
   - Recommendation: **import + call** — faster, no subprocess overhead, and `argparse.parse_args([])` exercises the exact branch.

2. **Does `tweepy.Client.delete_tweet(id=...)` on an already-deleted tweet return success or 404?**
   - What we know: delete semantics are usually idempotent in REST design, but X API v2 behavior is not documented in the search results.
   - What's unclear: if GATE-03 runs, succeeds, then is re-run before a rate-limit reset, does the second delete fail?
   - Recommendation: treat 404 on delete as **success** for GATE-03 purposes (tweet is gone — goal achieved). Wrap in try/except for specific `tweepy.NotFound`. [ASSUMED]

3. **Does `smoke_anthropic.py` need a system prompt, or is `messages=[{"role":"user", ...}]` enough?**
   - Answer: Enough. Haiku 4.5 responds fine without a system prompt. Keep the script minimal.

## Sources

### Primary (HIGH confidence)
- [Anthropic Pricing — Claude Haiku 4.5](https://platform.claude.com/docs/en/about-claude/pricing) — fetched 2026-04-13; base input $1/MTok, output $5/MTok
- [tweepy 4.14 Client source](https://github.com/tweepy/tweepy/blob/master/tweepy/client.py) — `__init__` signature with `return_type` kwarg
- [tweepy Discussion #1984: Add a headers field to Response](https://github.com/tweepy/tweepy/discussions/1984) — headers NOT in default Response; workaround = `return_type=requests.Response`
- `pyproject.toml` — `anthropic>=0.79,<0.80` and `tweepy>=4.14,<5` already pinned
- `src/tech_news_synth/config.py` — Settings class with 5 SecretStr fields confirmed
- `.env.example` — 5 required secrets present
- CLAUDE.md §STACK — tweepy 4.14 OAuth 1.0a User Context rationale, Haiku 4.5 model id
- `.planning/research/PITFALLS.md` — Pitfall 1 (X Free tier gone) + Pitfall 2 (Read-only permission trap)

### Secondary (MEDIUM confidence)
- [X Developer Community: Basic Plan rate limit investigation](https://devcommunity.x.com/t/twitter-api-v2-rate-limit-investigation-basic-plan/231386) — header names `x-user-limit-24hour-*` and `x-rate-limit-*` on `create_tweet`
- tweepy 4.14 Response docs — verified via WebSearch (WebFetch 403'd)

### Tertiary (LOW confidence)
- Exact rate-limit header names on pay-per-use tier (inferred from Basic Plan thread) — validated at runtime via GATE-03

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — both SDKs already pinned in pyproject; no version research needed
- Architecture patterns: HIGH — tweepy Client constructor, Anthropic messages.create usage shape verified from official sources
- Rate-limit header access in tweepy: HIGH — the `return_type=requests.Response` workaround is officially documented by the maintainers in Discussion #1984
- Pricing constants: HIGH — fetched directly from platform.claude.com 2026-04-13
- Pitfalls: HIGH — reuses existing PITFALLS.md entries for Phase 3-relevant threats

**Research date:** 2026-04-13
**Valid until:** 2026-05-13 (pricing is stable-ish; Haiku 3 retirement on 2026-04-19 means re-verify model id if plan execution slips past that date — but `claude-haiku-4-5` is unaffected by the Haiku 3 retirement)
