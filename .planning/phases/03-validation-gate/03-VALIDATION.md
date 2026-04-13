---
phase: 03
slug: validation-gate
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-13
---

# Phase 03 — Validation Strategy

> Per-phase validation contract. Phase 3 is **operator-driven**: most verification is manual runbook execution against live external APIs.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (inherits Phase 1/2 config) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (no changes) |
| **Quick run command** | `uv run pytest tests/unit/test_smoke_scripts.py -q` |
| **Full suite command** | `uv run pytest tests/ -v --cov=tech_news_synth` |
| **Estimated runtime** | ~0.5s unit (one argparse gate test); manual runs = operator time |

---

## Sampling Rate

- **After every task commit:** `uv run pytest tests/unit -q` must stay green (104 baseline + ~1 new).
- **Before `/gsd-verify-work`:**
  - Full unit suite green
  - Operator has run all three smoke scripts successfully (stdout captured)
  - `.planning/intel/x-api-baseline.md` exists, committed, has GO/NO-GO filled
- **Max feedback latency:** ~1s unit; smoke runs are one-shot.

---

## Per-Requirement Verification Map

| Requirement | Test Type | Automated / Manual | Command |
|-------------|-----------|--------------------|---------|
| GATE-01 (`smoke_anthropic` returns valid completion + token/cost) | manual + 1 unit | manual smoke run + unit asserts script imports without side effects | `uv run python scripts/smoke_anthropic.py` → exit 0 + JSON with `completion_text`, `input_tokens`, `output_tokens`, `cost_usd` on stdout |
| GATE-02 (`smoke_x_auth` confirms OAuth 1.0a + @ByteRelevant Read+Write) | manual + 1 unit | manual smoke run | `uv run python scripts/smoke_x_auth.py` → exit 0 + `{"username": "ByteRelevant", ...}` on stdout |
| GATE-03 (`smoke_x_post` posts + deletes + captures headers/cost) | manual + 1 unit | manual smoke with live post | `uv run python scripts/smoke_x_post.py --arm-live-post` → exit 0 + JSON with `tweet_id`, `posted_at`, `deleted_at`, `rate_limit_headers`, `elapsed_ms` |
| GATE-04 (`.planning/intel/x-api-baseline.md` documents cost, cap, OAuth, GO/NO-GO) | manual | committed markdown | file exists, template filled, `GO/NO-GO:` line present, tweet_id + date present |

**Cross-cutting — `--arm-live-post` gate test (D-03):** `tests/unit/test_smoke_scripts.py::test_smoke_x_post_refuses_without_arm` imports `scripts.smoke_x_post` as a module, invokes its argparse entrypoint with `sys.argv = ["smoke_x_post.py"]` (no flag), asserts `SystemExit(2)` is raised and stderr contains the warning. No SDK mocking — pure argparse check.

**Cross-cutting — secret-hygiene spot check:** After each smoke run, operator greps stdout+stderr for any raw secret value (`grep -E "sk-ant-|<known-access-token>"`) — must return nothing. Documented in runbook.

---

## Wave 0 Requirements

- [ ] Verify `tweepy>=4.14,<5` is present in `pyproject.toml` (per research: already pinned — confirm)
- [ ] Verify all 5 API keys present in `.env.example` (per research: yes — confirm)
- [ ] `.planning/intel/` directory exists (add `.gitkeep` if empty so git tracks it before first intel doc)
- [ ] `scripts/` directory exists (from Phase 2; confirm)
- [ ] `tests/unit/test_smoke_scripts.py` red stub (argparse gate test; fails until `scripts/smoke_x_post.py` exists)

---

## Manual-Only Verifications (Operator Runbook)

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Anthropic smoke completes | GATE-01 | Requires live API key + costs real tokens | `uv run python scripts/smoke_anthropic.py` — exit 0; stdout is valid JSON with `completion_text` (non-empty), `usage.input_tokens`, `usage.output_tokens`, `cost_usd` (float). `cost_usd` should be < $0.001 for the minimal prompt. |
| X OAuth smoke succeeds | GATE-02 | Requires live OAuth tokens | `uv run python scripts/smoke_x_auth.py` — exit 0; stdout JSON contains `"username": "ByteRelevant"`. If it fails with 401, the 4 tokens don't have Read+Write — regenerate in X Developer Portal AFTER toggling app to Read+Write. |
| X post-and-delete captures headers + cost | GATE-03 | Publishes a real tweet (costs money) | `uv run python scripts/smoke_x_post.py --arm-live-post` — exit 0; stdout JSON has `tweet_id` (numeric string), `posted_at` UTC ISO, `deleted_at` UTC ISO, `rate_limit_headers` (dict with `x-rate-limit-limit`, `x-rate-limit-remaining`, `x-rate-limit-reset` at minimum; `x-user-limit-24hour-*` if present). Visually confirm the tweet appeared + disappeared via https://x.com/ByteRelevant (should be gone within ~5s). |
| Unarmed smoke-post refuses to fire | D-03 (threat T-03-02) | Safety gate | `uv run python scripts/smoke_x_post.py` (no flag) — exits 2; stderr contains `REFUSING: pass --arm-live-post to actually post`. No tweet created. |
| Delete-failure cleanup message visible | D-05 (threat T-03-03) | Rare path | Only verified if it happens in practice; if delete fails, stderr `MANUAL CLEANUP REQUIRED: tweet_id=<id> — delete at https://x.com/ByteRelevant/status/<id>` appears. Operator manually deletes via X UI. |
| Intel doc filled | GATE-04 | Operator judgment (GO/NO-GO) | `.planning/intel/x-api-baseline.md` has: date, tweet_id from GATE-03 run, daily_cap from headers, observed USD/post from X billing dashboard, haiku_input_tokens + output_tokens + cost_usd from GATE-01 run, oauth_permissions = "Read+Write", GO/NO-GO decision line, commit hash. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` (argparse gate test) or `<manual>` steps
- [ ] No secret leaks in script output (grep-verified)
- [ ] Operator ran all three smoke scripts successfully and committed the intel doc
- [ ] No watch-mode flags
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
