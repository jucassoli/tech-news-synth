---
phase: 03-validation-gate
plan: 01
subsystem: validation-gate
tags: [smoke, gate, x-api, anthropic, oauth]
status: awaiting-operator-smoke
requires: [01-foundations/01-02]
provides:
  - "scripts/smoke_anthropic.py — GATE-01 Haiku 4.5 smoke (callable)"
  - "scripts/smoke_x_auth.py — GATE-02 X OAuth read smoke (callable)"
  - "scripts/smoke_x_post.py — GATE-03 X post+delete smoke (gated by --arm-live-post)"
  - ".planning/intel/x-api-baseline.md — GATE-04 intel template (operator fills)"
  - "MODEL_ID = 'claude-haiku-4-5' constant — single source of truth (T-03-07) for Phase 6 reuse"
  - "return_type=requests.Response pattern — to be reused by Phase 7 publish code"
affects: [".env contract (already established Phase 1)"]
tech-stack:
  added: []
  patterns:
    - "argparse-gated destructive operations (--arm-live-post)"
    - "subprocess.run() for CLI script unit tests (no scripts/__init__.py)"
    - "Module-level pricing/model constants for cost accounting + drift mitigation"
key-files:
  created:
    - scripts/smoke_anthropic.py
    - scripts/smoke_x_auth.py
    - scripts/smoke_x_post.py
    - tests/unit/test_smoke_scripts.py
    - .planning/intel/x-api-baseline.md
    - .planning/intel/.gitkeep
  modified: []
decisions:
  - "Honored CONTEXT D-01..D-07 verbatim; no deviations"
  - "MODEL_ID + Haiku pricing as module constants in smoke_anthropic.py (T-03-07 + cost reproducibility)"
  - "return_type=requests.Response only on smoke_x_post.py (D-discretion: smoke_x_auth doesn't need headers)"
metrics:
  duration-seconds: 205
  tasks-completed: 5
  tasks-total: 6
  unit-tests-baseline: 104
  unit-tests-now: 106
  completed-date: 2026-04-13
---

# Phase 3 Plan 01: Validation Gate — Smoke Scripts + Intel Doc Summary

Three standalone smoke scripts (Anthropic Haiku 4.5, X OAuth read, X post+delete round-trip), an intel-doc template, and an argparse-gate unit test — all automated code is in place; Task 6 (operator-driven live smoke runs against real APIs) is a blocking checkpoint awaiting human action.

## Status

**`awaiting-operator-smoke`** — Tasks 1–5 complete and committed. Task 6 is `checkpoint:human-verify`: operator must execute the three smoke scripts against real Anthropic + X APIs, fill `.planning/intel/x-api-baseline.md`, and stamp a GO/NO-GO decision before Phase 4 may begin. Claude cannot perform live API spend.

## What Was Built

| Task | Artifact | Commit |
|------|----------|--------|
| 1 | `scripts/smoke_anthropic.py` (GATE-01) | `c45c3b9` |
| 2 | `scripts/smoke_x_auth.py` (GATE-02) | `8043dcd` |
| 3 | `scripts/smoke_x_post.py` (GATE-03, --arm-live-post gate) | `de1397c` |
| 4 | `.planning/intel/x-api-baseline.md` + `.planning/intel/.gitkeep` (GATE-04 template) | `b48c143` |
| 5 | `tests/unit/test_smoke_scripts.py` (argparse gate test, 2 cases) | `cde498e` |
| 6 | Operator runbook execution + intel doc fill + GO/NO-GO | **PENDING** |

## Verification Results (automated portion)

- `uv run python scripts/smoke_anthropic.py --help` → exit 0, usage banner printed.
- `uv run python scripts/smoke_x_auth.py --help` → exit 0, usage banner printed.
- `uv run python scripts/smoke_x_post.py` (no flag) → exit 2, stderr contains `REFUSING: pass --arm-live-post`.
- `uv run python scripts/smoke_x_post.py --help` → shows `--arm-live-post` flag with REQUIRED warning.
- `uv run pytest tests/unit -q` → **106 passed** (104 baseline + 2 new).
- `uv run ruff check scripts/ tests/unit/test_smoke_scripts.py` → All checks passed.
- `grep -rE "sk-ant-|AAAA[A-Za-z0-9]{20,}" scripts/ .planning/intel/` → no matches (T-03-01, T-03-05).
- `grep -c "return_type=requests.Response" scripts/smoke_x_post.py` → 3 (docstring, comment, call site — RESEARCH §3/4 invariant satisfied).
- `grep "MODEL_ID = \"claude-haiku-4-5\"" scripts/smoke_anthropic.py` → exact match (T-03-07).
- `.planning/intel/x-api-baseline.md` contains literal `GO/NO-GO` token.

## Operator Smoke Results

**Pending — see Task 6 handoff below.** Will be appended to this SUMMARY (and to `.planning/intel/x-api-baseline.md`) once the operator runs the three smokes against live APIs.

## GO/NO-GO Decision

**PENDING** — to be set by operator after Step 5 of the Task 6 runbook in `03-01-PLAN.md`.

## Deviations from Plan

**None** — CONTEXT D-01..D-07 honored verbatim. One small style normalization happened mid-execution: `ruff` flagged `from datetime import timezone; datetime.now(timezone.utc)` (UP017) and was auto-fixed to `from datetime import UTC, datetime; datetime.now(UTC)`. This matches the existing Phase 1/2 codebase convention (e.g. `src/tech_news_synth/scheduler.py:128`, `src/tech_news_synth/db/posts.py:54`) and is functionally identical (Python 3.12 `datetime.UTC` is the alias for `timezone.utc`). Bundled into the Task 5 commit.

## Authentication Gates Encountered

None during executor runtime — all gates are in Task 6 (operator handoff), where live Anthropic + X credentials must be present in `.env`.

## Follow-Ups for Future Phases

- **Phase 6 (synthesis):** import `MODEL_ID` from a shared module rather than re-declaring; promote `scripts/smoke_anthropic.MODEL_ID` to e.g. `tech_news_synth.synthesis.constants.MODEL_ID` when Phase 6 lands. Pricing constants should live alongside.
- **Phase 7 (publish):** reuse the `return_type=requests.Response` pattern on `tweepy.Client.create_tweet` to read rate-limit headers for PUBLISH-03 (429 / `x-rate-limit-reset`) and PUBLISH-04 (daily-cap derivation from `x-user-limit-24hour-*`). The smoke captures both in its JSON output — store the same dict shape on the `posts` row.
- **Phase 8 (hardening):** if `MAX_MONTHLY_COST_USD` kill-switch (PUBLISH-05) needs to track Haiku cost separately from X cost, the `(input_tokens, output_tokens, cost_usd)` triple shape from `smoke_anthropic.py` is the schema to reuse on `posts.cost_usd_breakdown`.

## Self-Check: PASSED

- `scripts/smoke_anthropic.py` — FOUND
- `scripts/smoke_x_auth.py` — FOUND
- `scripts/smoke_x_post.py` — FOUND
- `tests/unit/test_smoke_scripts.py` — FOUND
- `.planning/intel/x-api-baseline.md` — FOUND
- `.planning/intel/.gitkeep` — FOUND
- Commit `c45c3b9` — FOUND
- Commit `8043dcd` — FOUND
- Commit `de1397c` — FOUND
- Commit `b48c143` — FOUND
- Commit `cde498e` — FOUND
