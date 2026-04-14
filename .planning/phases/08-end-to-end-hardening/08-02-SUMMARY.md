---
phase: 08
plan: 02
subsystem: operator-tools + docs
tags: [ops, soak, cutover, runbook, observability]
status: awaiting-checkpoint
dependency_graph:
  requires: [08-01]
  provides: []
  affects: [scripts/, docs/, .planning/intel/]
tech_stack:
  added: []
  patterns:
    - stdlib argparse CLI scripts under `scripts/` (no new deps)
    - per-poll SessionLocal() context (no long-lived sessions in monitors)
    - append-only intel files with operator-fillable sign-off templates
    - Jaccard over JSONB keys for cross-cycle similarity (NOT cosine over per-cycle byte vectors)
    - render-from-dict (never from Settings) to prevent secret leakage
key_files:
  created:
    - scripts/soak_monitor.py
    - scripts/cutover_verify.py
    - docs/DEPLOY.md
    - .planning/intel/soak-log.md
    - .planning/intel/cutover-report.md
    - tests/integration/test_soak_monitor.py
    - tests/unit/test_cutover_verify.py
    - .planning/phases/08-end-to-end-hardening/deferred-items.md
  modified: []
decisions:
  - "D-07/D-08: soak_monitor.py uses --hours (default 48) + --poll-minutes (default 30). Soft red flag on stale cycle (>2.5h); hard red flag (exit 1) on >2 failed cycles in 48h. D-08 PASS computed from final check."
  - "D-10/SC-5: cutover_verify.py uses **Jaccard over `clusters.centroid_terms` JSONB keys**, not cosine over `posts.theme_centroid` bytes. Rationale: Phase 5 D-01 fits TF-IDF per cycle — byte vectors live in per-cycle feature spaces and are not comparable across cycles. Stemmed term names are stable."
  - "D-11: DEPLOY.md has 9 sections (Prerequisites, Secrets, Clone+Configure, Boot, First-Cycle Verification, Daily Operations, Soak+Cutover, Troubleshooting, References). 483 lines, all code blocks copy-paste-ready."
  - "T-08-08 / Pitfall 5: render_report reads ONLY from the verdict dict; never imports or references Settings. Unit-tested via forbidden-string scan for sk-ant-/POSTGRES_PASSWORD/SecretStr/etc."
  - "Zero new Python dependencies (plan must-have); all scripts use stdlib argparse/json/time + existing SA 2.0 + pydantic-settings."
metrics:
  duration_sec: 0  # awaiting-checkpoint; will backfill after Part A+B sign-off
  completed_at: null
requirements_completed: []  # OPS-05 + OPS-06 pending operator checkpoint sign-off
---

# Phase 8 Plan 02: Operator Tools + Docs Summary

**Status:** `awaiting-checkpoint`. Code, tests, and docs are landed; Task 4
(human-verify) is blocking on operator-run compose smoke (Part A), 48h DRY_RUN
soak (Part B), and — optionally for v1-ship — post-24h cutover verification
(Part C). See **Checkpoint Handoff** section at the bottom of this document.

## Deliverables

### 1. `scripts/soak_monitor.py` (OPS-06 automation)

48h DRY_RUN soak monitor. Polls `run_log` + `posts` every `--poll-minutes`
(default 30) for `--hours` (default 48), emits one JSON line per check to
stdout AND appends to `.planning/intel/soak-log.md`.

**CLI surface:**

```
uv run python scripts/soak_monitor.py \
    [--hours 48] [--poll-minutes 30] \
    [--intel-path .planning/intel/soak-log.md]
```

**Invariants captured per poll:** `last_cycle_age_min`, `cycles_last_24h`,
`cycles_last_48h`, `failed_last_48h`, `dry_run_posts_last_24h`.

**Red-flag policy:**
- Soft (stderr warn, continue): `last_cycle_age_min > 150` (no cycle in >2.5h).
- Hard (stderr error, exit 1): `failed_last_48h > 2`.

**D-08 PASS computed from final check:** `cycles_last_48h >= 24 AND failed_last_48h <= 2`.

**Final summary block** written on normal completion OR `KeyboardInterrupt`
(Ctrl+C) to both stdout (`event: "soak_final"` JSON) and the intel file
(`### Soak run ended ...` markdown block including `D-08 PASS: {bool}`).

**Tests (6 integration):** seeded `run_log` + `posts` rows; assert invariant
math, soft/hard red-flag classification, D-08 pass/fail logic.

### 2. `scripts/cutover_verify.py` (SC-5 / D-10)

Post-24h live-cutover acceptance check. Exit 0 on **GO**, 1 on **NO-GO**.

**CLI surface:**

```
uv run python scripts/cutover_verify.py \
    --since 2026-04-17T12:00:00Z \
    [--report-path .planning/intel/cutover-report.md] \
    [--jaccard-threshold 0.5] [--cost-multiplier 2.0]
```

**Three checks (all must pass for GO):**
1. **Post count (24h):** `COUNT(*) WHERE status='posted' AND posted_at IN [since, since+24h)` → pass `>= 12`.
2. **Jaccard dup audit (48h window anchored at since):** pairwise
   `len(set(terms_a) & set(terms_b)) / len(set(terms_a) | set(terms_b))` over
   `clusters.centroid_terms` JSONB keys. Pass = **zero pairs** with `jaccard >= 0.5`.
3. **Cost envelope (24h):** `SUM(cost_usd)` over 24h window ≤ `2.0 * $0.3612 = $0.7224` (Phase 3 baseline from `.planning/intel/x-api-baseline.md`).

**Explicit Jaccard callout (docstring + research):** we use **Jaccard over
`centroid_terms` keys**, NOT cosine over `posts.theme_centroid` bytes —
because Phase 5 D-01 fits TF-IDF per-cycle, so byte vectors live in
per-cycle feature spaces and are not comparable across cycles. Stemmed
term names in `centroid_terms` are stable across cycles.

**Security invariant (T-08-08 / Pitfall 5):** `render_report` reads
**only** from the verdict dict. It never imports `Settings`. Unit test
`test_render_report_no_settings_dump` scans output for
`sk-ant-`, `ANTHROPIC_API_KEY`, `X_CONSUMER_*`, `X_ACCESS_*`,
`POSTGRES_PASSWORD`, `postgresql+psycopg`, `SecretStr`, `database_url`.

**Tests (13 unit):**
- `term_jaccard`: identical / disjoint / half-overlap / empty.
- `compute_verdict`: GO clean / NO-GO low-count / NO-GO dup / NO-GO cost.
- Threshold boundary (2/3 = 0.667 flags; 0/4 does not).
- `render_report`: contains all sections; suspect table when dups present; NO-GO verdict rendered; **no secret-shaped strings leak**.

### 3. `docs/DEPLOY.md` (OPS-05 / D-11)

483-line operator runbook walking a fresh Ubuntu 22.04+/24.04 LTS VPS from
`git clone` to healthy `@ByteRelevant` agent.

**Section map:**

| §   | Title                        | Content                                                                  |
| --- | ---------------------------- | ------------------------------------------------------------------------ |
| 1   | Prerequisites                | Host spec; Docker Engine 26 + Compose v2 plugin install; egress allowlist. |
| 2   | Secrets Acquisition          | Anthropic key + 4 X OAuth 1.0a User Context tokens; Read+Write-before-token-gen gotcha. |
| 3   | Clone + Configure            | `git clone`, `.env` required vs optional table (INTERVAL_HOURS, caps, windows). |
| 4   | Boot                         | `docker compose up -d --build`; healthcheck wait; `logs -f`.             |
| 5   | First-Cycle Verification     | `cycle_summary` JSON example (10 D-06 fields); SQL sanity; source-health cross-check. |
| 6   | Daily Operations             | All Plan 08-01 CLIs (`source-health`/`post-now`/`replay`); kill switch; DRY_RUN toggle. |
| 7.1 | 48h DRY_RUN Soak             | `scripts/soak_monitor.py` background invocation; D-08 pass criteria.     |
| 7.2 | Live Cutover Checklist       | 9-step checklist incl. `CUTOVER_TS` capture + `cutover_verify.py` at +24h. |
| 7.3 | Rollback                     | Manual DRY_RUN=1 flip + stale-pending investigation; cross-links orphaned-pending runbook. |
| 8   | Troubleshooting              | 10-row symptom/cause/fix table (Anthropic, X 401/429, caps, migrations, unhealthy containers). |
| 9   | References                   | Cross-links intel + Phase 7 runbook + CLAUDE.md + PROJECT.md + smoke scripts. |

### 4. Intel templates

- `.planning/intel/soak-log.md` — header (D-08 pass criteria checklist) + operator sign-off table (start/end ts, cycle count, failures, decision, operator) + "Raw poll log" append point. `soak_monitor.py` appends `## Soak run started ...` headers + per-poll JSON lines + `### Soak run ended ...` blocks.
- `.planning/intel/cutover-report.md` — header (SC-5 acceptance criteria checklist) + operator sign-off table (cutover ts, verdict, spot-check, decision, operator) + "Automated reports" append point. `cutover_verify.py` appends `## Cutover verification — <ts>` blocks.

## Test Inventory

| File                                       | Tests | Type        |
| ------------------------------------------ | ----- | ----------- |
| `tests/integration/test_soak_monitor.py`   | 6     | integration |
| `tests/unit/test_cutover_verify.py`        | 13    | unit        |

**Full-suite totals after Plan 08-02:**
- Unit: **394 passed** (Phase 1-7 baseline 363 + Plan 08-01 18 + Plan 08-02 13).
- Integration (minus pre-existing migration_roundtrip isolation issue): **119 passed** (Phase 1-7 baseline 99 + Plan 08-01 14 + Plan 08-02 6).
- Ruff: clean on all Plan 08-02 files (2 pre-existing errors in `synth/hashtags.py` and `synth/orchestrator.py` line 129 are outside Phase 8 scope).

## Deviations from Plan

**Rule 1 (auto-fix bug): ruff RUF001/RUF002/RUF003 unicode `×` warnings.**
Found during post-commit ruff run on new files. Replaced unicode
MULTIPLICATION SIGN with ASCII `x` in `cutover_verify.py` docstring /
comment / `render_report` markdown + `test_cutover_verify.py` comment.
No behavior change; markdown report now reads `Cap (x2.0)` instead of
`Cap (×2.0)`. Committed separately as `chore(08-02): replace unicode
MULTIPLICATION SIGN`.

**Out-of-scope: pre-existing `test_migration_roundtrip.py` isolation issue.**
Full integration suite with `-x` stops at `test_migration_roundtrip` —
root cause is the conftest's `Base.metadata.create_all` racing alembic's
`upgrade head`. Confirmed pre-existing (noted in conftest docstring
itself); passes in isolation. Recorded in
`.planning/phases/08-end-to-end-hardening/deferred-items.md` per GSD
scope-boundary rule.

Otherwise — **plan executed exactly as written.**

## Authentication Gates

None. All automation is DB-only; no external API calls from soak_monitor or
cutover_verify. The Anthropic + X secrets referenced in `DEPLOY.md §2` are
operator-acquired out-of-band (as intended).

## Commits

| Hash      | Message                                                                                          |
| --------- | ------------------------------------------------------------------------------------------------ |
| `6df4ae9` | feat(08-02): soak_monitor.py polling script + invariant checks (OPS-06)                          |
| `a81661c` | feat(08-02): cutover_verify.py post-24h acceptance check (SC-5 / D-10)                           |
| `56c10e0` | docs(08-02): DEPLOY.md VPS deployment runbook (OPS-05 / D-11)                                    |
| `a8c204a` | chore(08-02): replace unicode MULTIPLICATION SIGN (x) in docstrings/comments                     |
| `cd21d94` | docs(08-02): record pre-existing migration_roundtrip test-isolation issue                        |

## Known Stubs

None. Every deliverable is a complete implementation, template, or documentation
artifact. The `cutover_verify.py` report template header says "cutover_verify.py
appends blocks below" — this is a live append point, not a stub.

## Phase 8 Retrospective (brief — detailed retro in `/gsd-complete-phase`)

**All 13 locked decisions honored (D-01..D-13):**
- Plan 08-01: D-01 (replay), D-02 (post-now), D-03 (source-health), D-04/05/06 (cycle_summary), D-12 (persist kwarg), D-13 (argparse dispatch).
- Plan 08-02: D-07 (soak poll cadence), D-08 (soak pass criteria), D-09 (operator cutover), D-10 (cutover_verify post-24h), D-11 (DEPLOY.md structure).

**Deferred (per CONTEXT.md `<deferred>`; revisit in v2):**
- Prometheus / OpenTelemetry metrics export
- HTTP `/health` endpoint
- Automatic rollback watchdog
- Failure injection / chaos testing
- Multi-account staging
- Web dashboard
- Auto-tuning `max_posts_per_day` on engagement
- CI "fresh Ubuntu" deploy-validation job

**Zero new Python dependencies across both plans** (plan must-have).
**Zero schema changes, zero compose changes** across both plans.

## Self-Check: PASSED

- `scripts/soak_monitor.py`: FOUND
- `scripts/cutover_verify.py`: FOUND
- `docs/DEPLOY.md`: FOUND (483 lines; all 9 required section markers present)
- `.planning/intel/soak-log.md`: FOUND
- `.planning/intel/cutover-report.md`: FOUND
- `tests/integration/test_soak_monitor.py`: FOUND (6 tests)
- `tests/unit/test_cutover_verify.py`: FOUND (13 tests)
- `.planning/phases/08-end-to-end-hardening/deferred-items.md`: FOUND
- Commit 6df4ae9: FOUND
- Commit a81661c: FOUND
- Commit 56c10e0: FOUND
- Commit a8c204a: FOUND
- Commit cd21d94: FOUND
- Unit: 394 passed; Integration: 119 passed (minus pre-existing isolation issue).
- Ruff clean on all Plan 08-02 files.

---

## Checkpoint Handoff (Task 4 — human-verify, blocking)

**Operator:** please execute the following. Claude pauses here; resume with
one of the signals in `<resume-signal>` at the bottom of `08-02-PLAN.md`
(`approved`, `approved post-v1-cutover`, or `failing: <description>`).

### Part A — Compose Smoke (required, ~15 min)

On a machine with Docker + the repo checked out + a valid `.env`:

1. `docker compose up -d --build && sleep 90` — both containers healthy; one `cycle_summary` JSON line in stdout.
2. `docker compose exec app python -m tech_news_synth source-health` — aligned 5-column table for all sources in `sources.yaml`; `last_fetched_at` populated.
3. `docker compose exec app python -m tech_news_synth source-health --json | jq '.'` — JSON array of source objects; parses cleanly.
4. `docker compose exec app python -m tech_news_synth post-now` — blocks ~30–90s; one new `run_log` row; one new `cycle_summary` line with a fresh `cycle_id`; exit 0.
5. Pick a recent `cycle_id` then `docker compose exec app python -m tech_news_synth replay --cycle-id <cycle_id>` — JSON payload with `text`, `hashtags`, `cost_usd`; NO new `posts` row (verify `SELECT COUNT(*) FROM posts` before & after are equal).
6. `docker compose logs app | grep cycle_summary | head -3 | jq '.'` — at least one line is parseable JSON with all 10 D-06 fields.

### Part B — 48h DRY_RUN Soak (required for v1 ship)

7. Ensure `DRY_RUN=1` in `.env`. `docker compose restart app`.
8. Start soak monitor (backgrounded):

   ```bash
   nohup docker compose run --rm app \
       uv run python scripts/soak_monitor.py --hours 48 --poll-minutes 30 \
       > soak.out 2>&1 &
   ```

9. Return after 48h. Check `.planning/intel/soak-log.md` for the run.
   Pass criteria (D-08):
   - `cycles_last_48h >= 24`
   - `failed_last_48h <= 2`
   - Every cycle has a `cycle_summary` line (spot-check `docker compose logs app | grep cycle_summary | wc -l`)
   - Every non-empty cycle has a `posts` row with `status='dry_run'`

10. Fill **Operator Sign-Off** in `.planning/intel/soak-log.md`. If PASS → proceed to Part C (may be post-ship). If FAIL → investigate and re-run soak before cutover.

### Part C — Live Cutover + Post-24h Verify (optional for phase sign-off; required for SC-5 acceptance)

Per `docs/DEPLOY.md §7.2`:

11. Confirm soak PASSED. Flip `DRY_RUN=0` in `.env`. `docker compose restart app`.
12. `CUTOVER_TS=$(date -u --iso-8601=seconds)` — record this.
13. Monitor first 3 cycles: `docker compose logs -f app | grep cycle_summary`. Spot-check `https://x.com/ByteRelevant`.
14. After 24h: `docker compose run --rm app uv run python scripts/cutover_verify.py --since "$CUTOVER_TS"` — expect exit 0, verdict GO appended to `.planning/intel/cutover-report.md`.
15. Fill **Operator Sign-Off** in `.planning/intel/cutover-report.md`.

### Resume signals (reply with one)

- `approved` — Part A + Part B PASSED; Part C pending/complete.
- `approved post-v1-cutover` — Part A + Part B PASSED; Part C will run post-ship.
- `failing: <description>` — one of the smoke/soak/cutover steps failed; describe which.
