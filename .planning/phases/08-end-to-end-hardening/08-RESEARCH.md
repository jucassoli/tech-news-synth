# Phase 8: End-to-End + Hardening — Research

**Researched:** 2026-04-14
**Domain:** Operator CLIs, aggregated observability, dry-run soak, live-cutover protocol
**Confidence:** HIGH (no new libraries; pure composition + docs + operator tooling)

---

## Summary

Phase 8 is the **final phase** of v1. It ships **six OPS requirements** on top of an already-wired end-to-end pipeline (Phase 4-7 deliver the full `ingest → cluster → synth → publish` flow in `scheduler.run_cycle`). No new libraries, no new DB columns, no new compose services, no new architectural patterns — this phase is a **composition + operator-tooling phase**.

Four concrete deliverables:
1. **`cycle_summary` aggregated JSON log line** emitted inside `finish_cycle` after commit (OPS-01).
2. **Three operator CLIs** (`replay`, `post-now`, `source-health`) replacing the Phase 1 stub bodies (OPS-02/03/04).
3. **`docs/DEPLOY.md` runbook** walking a fresh Ubuntu VPS from `git clone` to healthy agent (OPS-05).
4. **48h DRY_RUN soak + live cutover protocol** with `scripts/soak_monitor.py` + `scripts/cutover_verify.py` (OPS-06 + SC-5).

**Primary recommendation:** Treat this phase as **three independent sub-scopes** that can parallelize in planning:
- **Sub-scope A — Observability** (D-04/05/06, `cycle_summary`): ~1 plan, single emit point inside `finish_cycle`, 1-line change to Phase 6 `counts_patch` to add `char_budget_used`.
- **Sub-scope B — Operator CLIs** (D-01/02/03/12/13): ~1 plan, three CLI modules + `run_synthesis(persist=False)` + 2 new `db/source_state.py` helpers.
- **Sub-scope C — Soak + Cutover + DEPLOY.md** (D-07..D-11): ~1 plan, 2 new scripts + `docs/DEPLOY.md` + 2 intel templates. Operator-driven; the scripts just automate the polling/verification.

**Scope creep guard:** NO new alerts (Discord/Telegram), NO health endpoint, NO metrics exporter, NO auto-rollback, NO new DB columns, NO new dependencies. All are explicitly deferred in CONTEXT.md `<deferred>` block.

---

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 `replay --cycle-id X`** re-runs synthesis ONLY; stdout only; no DB writes; no publish; real Anthropic call (~$0.0001/replay). Prints JSON: `{cycle_id, text, hashtags, cost_usd, input_tokens, output_tokens, final_method}`. Exits 1 with `cycle-id not found or has no resolvable input` when cluster/article missing.
- **D-02 `post-now`** inline `run_cycle()` invocation. Reuses every guardrail (kill-switch, DRY_RUN, cap, anti-repeat). Blocks ~30-90s. Prints same `cycle_summary` line the scheduler emits. Exit code tied to cycle status (`ok`→0, else non-zero). Safe to run while scheduler is up (session isolation + Phase 7 stale-pending guard).
- **D-03 `source-health`** has 3 modes: `source-health` (status table), `--enable NAME`, `--disable NAME`. Uses existing `db/source_state.py` helpers.
- **D-04** `cycle_summary` emitted inside `finish_cycle` AFTER the DB commit succeeds (durability invariant: log line ↔ DB row).
- **D-05** `cycle_summary` coexists with per-phase events; does not replace them.
- **D-06** 10 fields on the `cycle_summary` line (see §cycle_summary Schema).
- **D-07** `scripts/soak_monitor.py` polls `run_log` every 30 min for 48h; writes stdout + appends to `.planning/intel/soak-log.md`.
- **D-08** Soak pass criteria: ≥24 cycles, zero unhandled exceptions (all caught by INFRA-08), every cycle emits a `posts` row with `status='dry_run'` (empty-window allowed, documented), every cycle emits exactly one `cycle_summary`, ≤2 cycles with `status='failed'`.
- **D-09** Cutover operator-executed via `docs/DEPLOY.md` checklist; rollback = flip `DRY_RUN=1` in `.env` + `docker compose restart app`.
- **D-10** `scripts/cutover_verify.py` post-24h check: ≥12 posted tweets in 24h; centroid-based duplicate audit over 48h; cost sum within 2× Phase 3 baseline. Writes `.planning/intel/cutover-report.md`.
- **D-11** `docs/DEPLOY.md` structure: Prereqs → Secrets → Clone+Config → Boot → First-Cycle Verify → Daily Ops → Soak+Cutover → Troubleshooting.
- **D-12** `run_synthesis` gets `persist: bool = True` keyword-only parameter. When False: skip `insert_post`, return `SynthesisResult` with `post_id=None`. Enables `replay` CLI to reuse the orchestrator.
- **D-13** CLI argparse dispatch already exists in `__main__.py`. Phase 8 replaces the stub bodies in `src/tech_news_synth/cli/{replay,post_now,source_health}.py`.

### Claude's Discretion

- Exact soak monitoring cadence (30 min recommended).
- Whether `post-now` requires `--confirm` when `DRY_RUN=0` (recommend NO — CLI invocation is already an intentional operator action).
- Cost check tolerance multiplier for cutover_verify (2× recommended).
- Whether the 48h soak includes simulated failure injection (defer — passive monitoring is enough).
- Whether `DEPLOY.md` includes a "v1 graduation" section (defer to post-v1).
- `cycle_summary` destination: stdout only or also `/data/logs/app.jsonl` — **both** (inherits structlog dual-sink from Phase 1 D-07).
- Text-output formatting for `source-health` — recommend stdlib f-strings + manual padding (no `prettytable` dep).

### Deferred Ideas (OUT OF SCOPE)

- Prometheus / OpenTelemetry metrics export.
- HTTP `/health` endpoint.
- Automatic rollback on cutover (auto-flip `DRY_RUN=1` on N failures).
- Failure injection testing.
- Multi-account cutover staging.
- Web dashboard.
- Auto-tuning of `max_posts_per_day` from engagement.
- CI job for fresh-Ubuntu deploy validation.

---

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OPS-01 | Per-cycle `cycle_summary` JSON log line with 8 required fields (+ 2 locked via D-06) | §`cycle_summary` emit; §char_budget_used plumbing |
| OPS-02 | `replay --cycle-id` CLI (offline prompt iteration, no publish) | §`replay` implementation; §`persist=False` extension |
| OPS-03 | `post-now` CLI (off-cadence cycle, honors all guardrails) | §`post-now` implementation; §cycle-context helper |
| OPS-04 | `source-health` CLI (status + enable/disable) | §`source-health` implementation; §2 new DB helpers |
| OPS-05 | `docs/DEPLOY.md` walks fresh Ubuntu VPS to healthy agent | §DEPLOY.md structure; §Runbook cross-refs |
| OPS-06 | 48h DRY_RUN soak ≥24 cycles, zero unhandled exceptions | §soak_monitor.py pattern; §cutover_verify.py |

---

## Standard Stack

### Core (no new libraries)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `argparse` | stdlib | CLI subcommand flags (`--cycle-id`, `--enable`, `--disable`, `--json`) | [VERIFIED] Already used in `__main__.py`; zero new deps. |
| `json` | stdlib | `replay` stdout payload + `cycle_summary` structured log values | [VERIFIED] Already used in `synth/orchestrator.py` for `error_detail`. |
| `structlog` 25.x | existing | `cycle_summary` emit via `log.info("cycle_summary", **fields)` | [VERIFIED] Dual-sink stdout + `/data/logs/app.jsonl` already configured by Phase 1 D-07. |
| `sqlalchemy` 2.0 | existing | All CLI DB queries via existing `SessionLocal()` | [VERIFIED] Every repo module already uses this pattern. |
| `datetime.UTC` | stdlib | All timestamp handling (soak window, cutover window) | [VERIFIED] Project-wide invariant (INFRA-06). |

### Supporting (no new)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `numpy` | existing | `cutover_verify.py` centroid similarity (reuse `check_antirepeat` shape) | Only if reusing `bytes → ndarray` roundtrip; [ASSUMED] existing helper in `posts.py` or `antirepeat.py` will serve; if not, 5-line helper. |
| `scikit-learn` | existing | `cosine_similarity` for cutover audit | Imported only in `cutover_verify.py`. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff | Decision |
|------------|-----------|----------|----------|
| stdlib f-string text formatter for `source-health` | `prettytable`, `rich`, `tabulate` | Better alignment for ragged columns; adds a dep | **Use stdlib** — only 5 columns, operator-facing; `rich` adds 500KB to container; `--json` flag covers machine consumption anyway. |
| inline cycle_summary dict construction | Separate `cycle_summary` module | Cleaner seams for future changes | **Inline inside `finish_cycle`** — D-04 locks emit location; one-function encapsulation. |
| new `cli/_common.py` helper for settings + session bootstrapping | Inline in each CLI | DRY; three CLIs boot identically | **Recommend small `cli/_common.py`** — 20-line `bootstrap() -> tuple[Settings, Session, ...]` prevents drift. |
| re-fit TF-IDF in `cutover_verify.py` for centroid comparison | Jaccard over `clusters.centroid_terms` JSONB | Phase 5 D-01 fits per-cycle; vocab differs cross-cycle so raw stored centroids are NOT directly comparable | **Jaccard over stored `centroid_terms` keys** (top-20 terms per cluster); simpler, deterministic, no new fitting cost. See §cutover_verify. |

**Installation:** None. All deps already in `pyproject.toml`.

**Version verification:** N/A — no new packages.

---

## Architecture Patterns

### Recommended Layout (new files only)

```
src/tech_news_synth/
├── cli/
│   ├── _common.py         # NEW (optional helper) — bootstrap(settings_loader=None) → (Settings, SessionLocal)
│   ├── replay.py          # REWRITE — real impl (OPS-02)
│   ├── post_now.py        # REWRITE — real impl (OPS-03)
│   └── source_health.py   # REWRITE — real impl (OPS-04)
├── db/
│   └── source_state.py    # EXTEND — add enable_source, disable_source, get_all_source_states
├── db/run_log.py          # EXTEND — emit cycle_summary inside finish_cycle (post-commit)
└── synth/orchestrator.py  # EXTEND — add persist: bool = True keyword-only

scripts/
├── soak_monitor.py        # NEW — polls run_log every 30min for 48h
└── cutover_verify.py      # NEW — post-24h acceptance check

docs/
└── DEPLOY.md              # NEW — ~300-400 line runbook

.planning/intel/
├── soak-log.md            # NEW — operator-filled template
└── cutover-report.md      # NEW — operator-filled template
```

### Pattern 1: `cycle_summary` Emit After Commit (D-04)

**What:** One `log.info("cycle_summary", ...)` call emitted inside `finish_cycle` **after** `session.commit()`. Durability invariant: the log line's presence guarantees the DB row exists.

**Where:** NOT in `db/run_log.py::finish_cycle()` itself — that function is called in `scheduler.run_cycle`'s outer `finally` block, and commit happens in the scheduler (line 186). The natural emit point is **inside the scheduler's outer `finally` block, immediately after `session.commit()` succeeds** — or alternatively, restructure `finish_cycle` to commit internally and emit.

**Recommended approach:** Add emit to `scheduler.run_cycle`'s `finally` block (not `db/run_log.py`):

```python
# scheduler.py — amended finally block
finally:
    if session is not None:
        try:
            finish_cycle(session, cycle_id, status=status, counts=counts)
            session.commit()
            # D-04: emit AFTER commit succeeds (durability invariant)
            _emit_cycle_summary(cycle_id, status, counts, settings, cycle_started_at)
        except Exception:
            log.exception("run_log_finish_failed")
            session.rollback()
            # No cycle_summary emit on commit failure.
        finally:
            session.close()
    clear_contextvars()
```

**Rationale:** `finish_cycle` in `db/run_log.py` uses `session.flush()` not `commit()` (caller owns txn — Phase 2 convention). Moving commit responsibility would break that convention. Keeping emit at the scheduler level also keeps `duration_ms` computation trivial (the scheduler already has `cycle_started_at` in scope if we capture it at `start_cycle`).

**Tradeoff:** Slightly duplicates emit logic between `run_cycle` and `post-now` — mitigated because `post-now` calls `run_cycle` directly (D-02), so the emit fires once per invocation regardless of entry point.

### Pattern 2: `persist: bool = True` Extension on `run_synthesis`

**What:** Add keyword-only parameter. When False: skip `insert_post` call; return `SynthesisResult(..., post_id=None)`.

**Diff to `src/tech_news_synth/synth/orchestrator.py`:**

```python
def run_synthesis(
    session: Session,
    cycle_id: str,
    selection: SelectionResult,
    settings: Settings,
    sources_config: SourcesConfig,
    anthropic_client: anthropic.Anthropic,
    hashtag_allowlist: HashtagAllowlist,
    *,
    persist: bool = True,  # D-12
) -> SynthesisResult:
    ...
    # --- Step 6: persist ---
    if persist:
        post = insert_post(
            session, cycle_id=cycle_id, cluster_id=cluster_id, status=status,
            theme_centroid=theme_centroid, synthesized_text=final_text,
            hashtags=hashtags, cost_usd=cost_usd, error_detail=error_detail,
        )
        session.flush()
        post_id = post.id
    else:
        post_id = None

    log.info("synth_done", attempts=attempts_count, final_method=final_method,
             input_tokens=total_input_tokens, output_tokens=total_output_tokens,
             cost_usd=cost_usd, post_id=post_id, persist=persist)

    return SynthesisResult(..., post_id=post_id, status=status,
                           counts_patch={
                               "synth_attempts": attempts_count,
                               # ... (existing keys; post_id can be None in counts_patch)
                               "post_id": post_id,
                           })
```

**Existing test impact:** [VERIFIED via code read] `SynthesisResult.post_id` is already used as `int` in `tests/unit/test_synth_orchestrator.py` and `tests/integration/test_synth_persist.py`. Phase 8 must either (a) type as `int | None` (breaking change — audit all test assertions) or (b) verify the existing tests always call with `persist=True` default and so receive `int`. **Recommend (b): default stays `True`, existing call sites unchanged, tests untouched.** One new unit test `test_run_synthesis_persist_false_skips_insert` covers the new branch.

**Caller — `replay` CLI:**

```python
synthesis = run_synthesis(
    session, cycle_id=target_cycle_id, selection=reconstructed_selection,
    settings=settings, sources_config=sources_config,
    anthropic_client=anthropic_client, hashtag_allowlist=hashtag_allowlist,
    persist=False,  # D-01
)
```

### Pattern 3: `replay` CLI — Reconstructing `SelectionResult` from DB

**What:** Given a past `cycle_id`, rebuild a `SelectionResult` from the persisted `clusters` + `posts` rows so `run_synthesis` can replay.

**Query path (D-01):**

1. Look up the cycle's `posts` row: `SELECT cluster_id, synthesized_text FROM posts WHERE cycle_id = :cid LIMIT 1`. If no row: cycle had empty-window or capped → exit 1 with "cycle-id has no resolvable input".
2. If `cluster_id IS NOT NULL`: winner path. Query the cluster row:
   ```python
   cluster = session.execute(
       select(Cluster).where(Cluster.id == post.cluster_id, Cluster.chosen == True)
   ).scalar_one_or_none()
   ```
   `cluster.member_article_ids` (JSONB list) → `selection.winner_article_ids`.
   `selection.winner_cluster_id = cluster.id`.
   `selection.winner_centroid = post.theme_centroid` (preserves 06-01 vector).
3. If `cluster_id IS NULL`: fallback path. `posts` doesn't directly store `fallback_article_id`, but the Phase 5 orchestrator's `counts_patch` in `run_log.counts` has the data:
   ```sql
   SELECT counts FROM run_log WHERE cycle_id = :cid;
   -- counts JSON contains 'fallback_article_id' (or similar — verify at implementation time)
   ```
   **[ASSUMED]** — Phase 5 Plan 02 summary says "SelectionResult is returned" but doesn't document whether `fallback_article_id` lands in `counts_patch`. Implementer must verify by reading `src/tech_news_synth/cluster/orchestrator.py::run_clustering`; if not, fall back to: re-run Phase 5 window query against articles older than 6h → `fallback_article_id = single best-ranked article in that window`. Simpler alternative: **add `posts.fallback_article_id: int | None` column** — but that breaks Phase 8's "no new DB columns" rule. **Recommend: store `fallback_article_id` in `run_log.counts` dict (operator discretion under D-07, Phase 5 key-naming).**

**Key data model references** (verified via code read):
- `clusters.member_article_ids: JSONB` list
- `clusters.chosen: bool`
- `clusters.centroid_terms: JSONB` dict
- `posts.cluster_id: int | None` (NULL on fallback path)
- `posts.theme_centroid: bytes | None` (BYTEA)
- `posts.cycle_id: str` (ULID)

**Edge cases:**
- Cycle was capped (no synth happened, no posts row) → exit 1.
- Cycle had empty window (no posts row) → exit 1.
- Cycle succeeded but `posts` row later purged by retention → exit 1 (same error path).

**Stdout JSON payload:**

```json
{
  "cycle_id": "01KP...",
  "text": "<re-synthesized body>",
  "hashtags": ["#IA", "#Tecnologia"],
  "source_url": "https://example.com/article",
  "cost_usd": 0.000141,
  "input_tokens": 823,
  "output_tokens": 76,
  "final_method": "completed"
}
```

### Pattern 4: `post-now` CLI — Direct `run_cycle()` Invocation

**What:** CLI process loads the same collaborators as `__main__._dispatch_scheduler` does, then calls `scheduler.run_cycle(settings, sources_config=..., hashtag_allowlist=...)` exactly once. Does NOT register with APScheduler.

**Sketch:**

```python
# cli/post_now.py
def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="post-now", ...)
    # No args required in v1 (D-02 no --confirm flag).
    parser.parse_args(argv)

    from tech_news_synth.config import load_settings
    from tech_news_synth.logging import configure_logging
    from tech_news_synth.db.session import init_engine
    from tech_news_synth.ingest.sources_config import load_sources_config
    from tech_news_synth.synth.hashtags import load_hashtag_allowlist
    from tech_news_synth.scheduler import run_cycle

    settings = load_settings()
    configure_logging(settings)
    init_engine(settings)
    sources_config = load_sources_config(Path(settings.sources_config_path))
    hashtag_allowlist = load_hashtag_allowlist(Path(settings.hashtags_config_path))

    # Direct invocation — blocks ~30-90s. run_cycle never raises (INFRA-08).
    # run_cycle emits cycle_summary on its own (Pattern 1).
    run_cycle(settings, sources_config=sources_config, hashtag_allowlist=hashtag_allowlist)

    # Exit code: look up the run_log row just written
    from tech_news_synth.db.session import SessionLocal
    from tech_news_synth.db.models import RunLog
    from sqlalchemy import select, desc
    with SessionLocal() as s:
        latest = s.execute(
            select(RunLog).order_by(desc(RunLog.started_at)).limit(1)
        ).scalar_one()
    return 0 if latest.status == "ok" else 1
```

**Why safe to run alongside scheduler:** Phase 7 `cleanup_stale_pending` + `check_caps` + idempotent `posts` write guarantees no double-publish even if the scheduler tick and `post-now` race. The pessimistic worst case is one extra cycle against the daily cap — the cap check catches it.

**Cycle-id generation:** `run_cycle` already calls `new_cycle_id()` internally — CLI doesn't need to pass one.

### Pattern 5: `source-health` CLI

**Subparser shape:**

```python
parser.add_argument("--enable", metavar="NAME", help="Re-enable a disabled source")
parser.add_argument("--disable", metavar="NAME", help="Disable a source")
parser.add_argument("--json", action="store_true", help="Machine-readable output")
# Mutually exclusive: --enable and --disable; neither = status mode.
```

**Status mode output (stdlib f-strings + manual padding):**

```python
rows = get_all_source_states(session)  # NEW helper
# Column widths: auto-computed from max(len(name) for row in rows)
print(f"{'name':<20} {'last_fetched_at':<28} {'last_status':<18} {'failures':>8} {'disabled':<8}")
for r in rows:
    dis = "YES" if r.disabled_at else "NO"
    lf = r.last_fetched_at.isoformat() if r.last_fetched_at else "—"
    print(f"{r.name:<20} {lf:<28} {(r.last_status or '—'):<18} {r.consecutive_failures:>8} {dis:<8}")
```

With `--json`: dump list of `{name, last_fetched_at, last_status, consecutive_failures, disabled}`.

**New DB helpers needed** in `src/tech_news_synth/db/source_state.py`:

```python
def get_all_source_states(session: Session) -> list[SourceState]:
    """Return all source_state rows ordered by name."""
    return list(session.execute(
        select(SourceState).order_by(SourceState.name)
    ).scalars())

def enable_source(session: Session, name: str) -> bool:
    """Clear disabled_at + reset failure counter. Returns True if row updated, False if name unknown."""
    row = get_state(session, name)
    if row is None:
        return False
    row.disabled_at = None
    row.consecutive_failures = 0
    session.flush()
    return True

def disable_source(session: Session, name: str) -> bool:
    """Set disabled_at if not already disabled. Returns True if row updated, False if name unknown."""
    row = get_state(session, name)
    if row is None:
        return False
    if row.disabled_at is None:
        row.disabled_at = datetime.now(UTC)
        session.flush()
    return True
```

Both helpers commit at caller (CLI `main` calls `session.commit()`). Audit event: `log.info("source_toggled", name=..., action="enable"|"disable")`.

### Pattern 6: `soak_monitor.py` — Polling Script

**Structure:**

```python
#!/usr/bin/env python3
"""48h DRY_RUN soak monitor (D-07). Polls run_log every 30min."""
from __future__ import annotations
import sys, time, json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from sqlalchemy import select, func

from tech_news_synth.config import load_settings
from tech_news_synth.db.session import init_engine, SessionLocal
from tech_news_synth.db.models import RunLog, Post

POLL_INTERVAL_SEC = 1800  # 30 min
SOAK_DURATION_HOURS = 48
INTEL_PATH = Path(".planning/intel/soak-log.md")


def check_invariants(session) -> dict:
    now = datetime.now(UTC)
    last_cycle = session.execute(
        select(RunLog).order_by(RunLog.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    last_age_min = (now - last_cycle.started_at).total_seconds() / 60 if last_cycle else None
    last24_count = session.execute(
        select(func.count(RunLog.cycle_id)).where(RunLog.started_at > now - timedelta(hours=24))
    ).scalar_one()
    failed_count = session.execute(
        select(func.count(RunLog.cycle_id))
        .where(RunLog.status == "failed", RunLog.started_at > now - timedelta(hours=48))
    ).scalar_one()
    dry_run_posts = session.execute(
        select(func.count(Post.id))
        .where(Post.status == "dry_run", Post.created_at > now - timedelta(hours=24))
    ).scalar_one()
    return {
        "ts": now.isoformat(),
        "last_cycle_age_min": last_age_min,
        "cycles_last_24h": last24_count,
        "failed_last_48h": failed_count,
        "dry_run_posts_last_24h": dry_run_posts,
    }


def main() -> int:
    settings = load_settings()
    init_engine(settings)
    end_ts = datetime.now(UTC) + timedelta(hours=SOAK_DURATION_HOURS)
    INTEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with INTEL_PATH.open("a") as f:
        f.write(f"\n## Soak run started {datetime.now(UTC).isoformat()}\n")

    try:
        while datetime.now(UTC) < end_ts:
            with SessionLocal() as s:
                status = check_invariants(s)
            line = json.dumps(status)
            print(line, flush=True)
            with INTEL_PATH.open("a") as f:
                f.write(line + "\n")
            # Red flags:
            if status["last_cycle_age_min"] is not None and status["last_cycle_age_min"] > 150:
                print("RED FLAG: no cycle in >2.5h", file=sys.stderr)
            if status["failed_last_48h"] > 2:
                print(f"RED FLAG: {status['failed_last_48h']} failed cycles in 48h (threshold 2)", file=sys.stderr)
                return 1
            time.sleep(POLL_INTERVAL_SEC)
    except KeyboardInterrupt:
        print("soak monitor interrupted — writing final summary", file=sys.stderr)
    # Final summary
    with SessionLocal() as s:
        summary = check_invariants(s)
    print(json.dumps({"event": "soak_final", **summary}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Invocation:** `uv run python scripts/soak_monitor.py &> soak.log &` — runs 48h in background on operator's host (not inside container — the script needs DB access via Postgres port-forward or compose exec).

### Pattern 7: `cutover_verify.py` — Post-24h Audit

**Critical insight (this phase's subtle gotcha):** Phase 5 D-01 fits TF-IDF **per-cycle** on a combined corpus. The stored `posts.theme_centroid` (BYTEA) is a vector in **that cycle's feature space** — its dimensions don't align with vectors from other cycles. Pairwise cosine across stored centroids is **not semantically valid** for cutover audit.

**Recommended approach (VERIFIED against Phase 5 D-01):** use **Jaccard similarity over `clusters.centroid_terms` JSONB keys** (the top-K terms per cluster are stable across cycles since they're stemmed strings, not vector indices).

```python
def term_jaccard(a: dict, b: dict) -> float:
    set_a, set_b = set(a.keys()), set(b.keys())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)
```

Audit query:

```python
# Fetch all posted posts in 48h window, joined to their cluster's centroid_terms
rows = session.execute(
    select(Post.id, Post.posted_at, Post.cluster_id, Cluster.centroid_terms)
    .join(Cluster, Post.cluster_id == Cluster.id, isouter=True)
    .where(Post.status == "posted", Post.posted_at > cutover_ts - timedelta(hours=48))
).all()

suspects = []
for i, (id_a, ts_a, cid_a, terms_a) in enumerate(rows):
    for id_b, ts_b, cid_b, terms_b in rows[i+1:]:
        if terms_a and terms_b:
            sim = term_jaccard(terms_a, terms_b)
            if sim >= 0.5:
                suspects.append({"post_a": id_a, "post_b": id_b, "sim": sim})
```

**Additional checks:**
- `SELECT COUNT(*) FROM posts WHERE status='posted' AND posted_at > :cutover_ts` ≥ 12.
- `SELECT SUM(cost_usd) FROM posts WHERE posted_at > :cutover_ts AND posted_at < :cutover_ts + '24h'` ≤ 2 × baseline ($0.36 from Phase 3 `x-api-baseline.md`).

**Output:** appends markdown to `.planning/intel/cutover-report.md` with findings + PASS/FAIL verdict.

### Anti-Patterns to Avoid

- **Adding a new `posts.cycle_summary_json` column:** Don't. `run_log.counts` already carries all data; `cycle_summary` is a log-only view.
- **Emitting `cycle_summary` inside `db/run_log.py::finish_cycle`:** Breaks Phase 2 "caller owns transaction" convention. Emit at scheduler level after commit.
- **Pairwise cosine across stored `theme_centroid` bytes in `cutover_verify`:** [CITED: Phase 5 Plan 02 SUMMARY §D-01] vector spaces differ per cycle. Use Jaccard over `centroid_terms`.
- **Running `soak_monitor.py` inside the app container:** It would be killed by container restarts. Run from operator's host.
- **`post-now --force` or `--skip-caps`:** Would defeat PUBLISH-04/05 guardrails. D-02 locks that all guardrails fire.
- **Adding per-source config to CLI flags:** `source-health --enable NAME` is enough — no `--disable-all`, no regex matchers (scope creep).
- **Printing secrets in `cycle_summary`:** The settings object includes `SecretStr` fields. Never log `settings` directly; only pull plain-value fields (`dry_run`, `interval_hours`). [VERIFIED pattern in Phase 6 T-06-11.]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Text table alignment for `source-health` | Custom column-width calc | stdlib f-strings with fixed widths OR `--json` flag for machine read | 5-column table; manual padding is 3 lines of code. `rich`/`tabulate` adds a dep for a one-time operator view. |
| Centroid similarity comparison cross-cycle | Custom numpy+TF-IDF re-fit | Jaccard over `centroid_terms` JSONB keys | Phase 5 centroids are per-cycle — not comparable as vectors. Jaccard on term-names is deterministic and cheap. |
| Structured JSON log emission | Hand-rolled JSON formatter | `log.info("cycle_summary", **fields)` | structlog already renders via orjson (Phase 1 D-07). |
| VPS health polling | Custom systemd timer | `scripts/soak_monitor.py` as a foreground process; operator Ctrl+C | One-shot 48h monitor; no need for persistent service. |
| Cutover rollback automation | Watchdog service | Documented manual flip of `DRY_RUN=1` in `.env` + `docker compose restart` (D-09) | Solo operator; D-09 locks manual. |
| Cycle duration measurement | Custom timer | `(finished_at - started_at).total_seconds() * 1000` from `RunLog` columns | Already persisted. |

**Key insight:** Phase 8 is the **anti-library phase**. Every temptation to add a dep (alerting, dashboards, rich tables, metrics SDKs) is already deferred. The right answer is always "use what's already there + a thin operator script + a doc."

---

## Common Pitfalls

### Pitfall 1: `cycle_summary` Emit Fires Even on Paused Cycles

**What goes wrong:** Phase 1 D-08 kill-switch exits early with zero I/O and **no** `run_log` row. If `cycle_summary` emit is placed unconditionally in scheduler `finally`, a paused cycle emits a summary with `cycle_id` but no corresponding DB row — contradicting D-04's durability invariant.

**Why:** `cycle_skipped` at `scheduler.py:92` returns before `session = SessionLocal()` (line 96). The existing `finally` block already guards `if session is not None` — safe if we gate the emit inside that same guard.

**How to avoid:** Place `_emit_cycle_summary(...)` inside `if session is not None:` AND after `session.commit()` succeeds. The paused-path exit through `finally` hits `session is None` and skips both persist + emit. [VERIFIED by code read of scheduler.py:85-192.]

### Pitfall 2: `replay` Accidentally Publishes

**What goes wrong:** If `persist=False` is forgotten in the `replay` CLI, `run_synthesis` writes a `posts` row, and the next scheduler cycle's `cleanup_stale_pending` finds a stale pending row and may trigger publication (actually: `cleanup_stale_pending` marks stale as `failed`, not `posted` — but the invariant is still violated: a row exists that shouldn't).

**Why:** `run_synthesis` default `persist=True`. Easy to miss in review.

**How to avoid:**
1. Explicit keyword-only parameter (`*, persist: bool = True`) — Python raises `TypeError` if positional.
2. `replay` CLI unit test asserts `post_id is None` in the returned `SynthesisResult`.
3. `replay` CLI integration test asserts no new `posts` row after invocation.
4. Threat tag T-08-02 in plan.

### Pitfall 3: `post-now` Runs While Scheduler Is Booting

**What goes wrong:** Two cycles land within seconds: the scheduler's first-tick-on-boot (D-07) plus an operator `docker compose exec app python -m tech_news_synth post-now`. Both call `start_cycle(session, cycle_id)` with different ULIDs → two `run_log` rows, but both try to clustering the same article window → second cycle has empty results (all articles already clustered and winner posted).

**Why:** Articles aren't consumed by clustering — they stay in `articles` table. The second cycle clusters the same window and hits anti-repeat because the first cycle just posted.

**How to avoid:**
- Anti-repeat correctly kicks in (Phase 5 CLUSTER-05) → second cycle falls back or exits `empty`.
- Cap check correctly detects 1/12 → allows second cycle but operator sees double-post attempt.
- **Acceptable residual risk** — solo operator won't accidentally double-invoke; document in DEPLOY.md.

### Pitfall 4: `soak_monitor.py` Can't Reach Postgres

**What goes wrong:** Soak monitor runs from operator's host but Postgres is only exposed inside the compose network.

**Why:** Compose default doesn't expose Postgres port to host.

**How to avoid:**
- Option A: Run monitor inside app container: `docker compose exec app uv run python scripts/soak_monitor.py`. Survives 48h only if the exec session stays open — fragile.
- Option B (recommended): Document `ports: ["127.0.0.1:5432:5432"]` in compose override OR use `docker compose exec postgres psql` for ad-hoc queries + run the monitor as a short-lived polling script from inside a sidecar container.
- Option C: Run monitor via `docker compose run --rm app uv run python scripts/soak_monitor.py` — uses compose network, survives app container restarts. **[Recommended]**

### Pitfall 5: `cutover_verify.py` Loads Settings with `.env` Secrets and Echoes Them

**What goes wrong:** Script loads `Settings` (SecretStr fields) and dumps it somewhere during debug → secrets leak into `.planning/intel/cutover-report.md`.

**Why:** Easy to `print(settings.model_dump())` during dev.

**How to avoid:**
- Never `print(settings)` or `model_dump()` without `exclude` for SecretStr fields.
- Pre-commit grep hook (project has one per INFRA-04): scan `.planning/intel/*.md` for secret patterns before commit.
- Plan task explicitly asserts "no settings dump".

### Pitfall 6: `cycle_summary` Misses `char_budget_used` for Empty/Capped Cycles

**What goes wrong:** D-06 field #6 is `char_budget_used (int | null)`. On empty-window / capped / paused, there's no synthesized_text → needs to be explicit null, not 0 (0 means "synthesized a zero-char post").

**Why:** Easy to default missing counts_patch keys to 0.

**How to avoid:** Explicit `counts.get("char_budget_used")` returns None if key absent. Add `char_budget_used` to Phase 6 `counts_patch` computation:

```python
# synth/orchestrator.py — add one field to counts_patch
counts_patch={
    ...existing...,
    "char_budget_used": weighted_len(final_text),  # NEW for Phase 8 OPS-01
}
```

### Pitfall 7: Test Uses Real Anthropic API and Charges Money

**What goes wrong:** `replay` integration test calls `run_synthesis(persist=False)` which calls real `anthropic.Anthropic` → each test run costs real cents and requires live API key.

**How to avoid:** Integration test mocks `call_haiku` (Phase 6 pattern). Real Anthropic call only happens when operator runs the CLI manually (D-01 explicitly allows ~$0.0001/replay).

---

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — Phase 8 adds no new data; reuses existing `posts`, `run_log`, `clusters`, `source_state` tables. | None |
| Live service config | None — no new compose services, no new env vars (DRY_RUN already exists). | None |
| OS-registered state | None — no new systemd units, no cron jobs (APScheduler still PID 1). `soak_monitor.py` is operator-launched foreground. | None |
| Secrets / env vars | No new secrets. Existing `ANTHROPIC_API_KEY`, `X_*`, `DRY_RUN`, `PAUSED` read unchanged. Cutover toggle = `DRY_RUN=0` in existing `.env`. | None — document in DEPLOY.md |
| Build artifacts | None — no new Python package installed, no compiled assets, no new Dockerfile layers. | None |

**Nothing found in any category:** Verified by reading every locked decision D-01..D-13 and scanning CONTEXT.md `<deferred>` block. Phase 8 is pure composition + docs + operator scripts.

---

## Environment Availability

Phase 8 CLIs + scripts depend on the already-audited Phase 1-7 environment. No new dependencies.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | All CLIs + scripts | ✓ (existing Dockerfile stage) | 3.12 | — |
| Postgres 16 (via compose) | All CLIs (read) + soak_monitor + cutover_verify | ✓ (compose service) | 16 | — |
| `docker compose` on VPS | DEPLOY.md runbook | ✗ operator-installed | ≥26 engine + compose v2 | Document install in DEPLOY.md Prerequisites |
| Git on VPS | DEPLOY.md runbook (clone) | ✗ operator-installed | any | Document install |
| `.env` file with 5 secrets | All CLIs + scripts | operator-owned | — | DEPLOY.md Secrets section |

**Missing dependencies with no fallback:** None — operator installs Docker/Git per DEPLOY.md.

**Missing dependencies with fallback:** None.

---

## `cycle_summary` Schema (D-06 Locked)

```python
{
    "event": "cycle_summary",             # structlog adds automatically
    "timestamp": "<iso>",                 # structlog adds automatically
    "cycle_id": "01KP...",                # field 1 — ULID string
    "duration_ms": 3421,                  # field 2 — int (finished_at - started_at).total_seconds() * 1000
    "articles_fetched_per_source": {...}, # field 3 — dict[str, int] from run_log.counts["articles_fetched"]
    "cluster_count": 4,                   # field 4 — int from counts["cluster_count"]
    "chosen_cluster_id": 42,              # field 5 — int | None
    "char_budget_used": 223,              # field 6 — int | None (None if no synth; see Pitfall 6)
    "token_cost_usd": 0.000141,           # field 7 — float | None; from counts["synth_cost_usd"]
    "post_status": "posted",              # field 8 — str: posted|failed|dry_run|capped|empty|paused
    "status": "ok",                       # field 9 — str: run_log.status (ok|failed|paused|cost_capped)
    "dry_run": false,                     # field 10 — bool from settings.dry_run at cycle start
}
```

**Source of each field:**
- `cycle_id`, `status`, `duration_ms`: from the `RunLog` row just committed.
- `articles_fetched_per_source`, `cluster_count`, `chosen_cluster_id`, `char_budget_used`, `token_cost_usd`, `post_status`: from `counts` dict (the merged `run_log.counts` built in `scheduler.run_cycle`).
- `dry_run`: from `settings.dry_run` captured at cycle start.

**New `counts_patch` key** (Phase 6 amendment): `char_budget_used`. Everything else already present per Phase 4-7 SUMMARIES.

**`post_status` mapping** — derived at emit time from merged counts:
```python
post_status = (
    counts.get("publish_status")  # 'posted'|'failed'|'dry_run'|'capped'|'empty' (Phase 7)
    or ("paused" if paused else "empty")
)
```

---

## Code Examples

### 1. `cycle_summary` Emit Helper

```python
# scheduler.py (new function)
def _emit_cycle_summary(
    cycle_id: str,
    status: str,
    counts: dict,
    settings: Settings,
    started_at: datetime,
) -> None:
    """D-04: emit exactly one cycle_summary line after commit succeeds."""
    duration_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)
    post_status = counts.get("publish_status") or "empty"
    log.info(
        "cycle_summary",
        cycle_id=cycle_id,
        duration_ms=duration_ms,
        articles_fetched_per_source=counts.get("articles_fetched", {}),
        cluster_count=counts.get("cluster_count"),
        chosen_cluster_id=counts.get("chosen_cluster_id"),
        char_budget_used=counts.get("char_budget_used"),
        token_cost_usd=counts.get("synth_cost_usd"),
        post_status=post_status,
        status=status,
        dry_run=bool(settings.dry_run),
    )
```

**Call site** (inside existing scheduler `finally` after `session.commit()`):

```python
finish_cycle(session, cycle_id, status=status, counts=counts)
session.commit()
_emit_cycle_summary(cycle_id, status, counts, settings, cycle_started_at)
```

Requires capturing `cycle_started_at = datetime.now(UTC)` near the top of `run_cycle` (right before `start_cycle`).

### 2. `replay` CLI Skeleton

```python
# cli/replay.py
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from sqlalchemy import select
from tech_news_synth.cluster.models import SelectionResult
from tech_news_synth.config import load_settings
from tech_news_synth.db.models import Post, Cluster
from tech_news_synth.db.session import init_engine, SessionLocal
from tech_news_synth.ingest.sources_config import load_sources_config
from tech_news_synth.logging import configure_logging
from tech_news_synth.synth.hashtags import load_hashtag_allowlist
from tech_news_synth.synth.orchestrator import run_synthesis
import anthropic


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="replay")
    parser.add_argument("--cycle-id", required=True)
    args = parser.parse_args(argv)

    settings = load_settings()
    configure_logging(settings)
    init_engine(settings)
    sources_config = load_sources_config(Path(settings.sources_config_path))
    hashtag_allowlist = load_hashtag_allowlist(Path(settings.hashtags_config_path))

    with SessionLocal() as session:
        # Resolve the historical post
        post = session.execute(
            select(Post).where(Post.cycle_id == args.cycle_id).limit(1)
        ).scalar_one_or_none()
        if post is None:
            print(f"cycle-id {args.cycle_id} not found or has no resolvable input",
                  file=sys.stderr)
            return 1

        # Build SelectionResult
        if post.cluster_id is not None:
            cluster = session.get(Cluster, post.cluster_id)
            selection = SelectionResult(
                winner_cluster_id=cluster.id,
                winner_article_ids=cluster.member_article_ids,
                fallback_article_id=None,
                counts_patch={},
                winner_centroid=post.theme_centroid,
            )
        else:
            # Fallback path — fallback_article_id from run_log.counts (assumed)
            # Implementer: verify Phase 5 stores it; see RESEARCH §Pattern 3.
            print("fallback-cycle replay: fallback_article_id lookup not yet wired",
                  file=sys.stderr)
            return 1

        anthropic_client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        synthesis = run_synthesis(
            session, args.cycle_id, selection, settings, sources_config,
            anthropic_client, hashtag_allowlist,
            persist=False,
        )

    print(json.dumps({
        "cycle_id": args.cycle_id,
        "text": synthesis.text,
        "hashtags": synthesis.hashtags,
        "source_url": synthesis.source_url,
        "cost_usd": synthesis.cost_usd,
        "input_tokens": synthesis.input_tokens,
        "output_tokens": synthesis.output_tokens,
        "final_method": synthesis.final_method,
    }, ensure_ascii=False))
    return 0
```

### 3. `docs/DEPLOY.md` Outline (D-11 Structure)

```markdown
# tech-news-synth — Deploy Runbook (v1)

This runbook walks a fresh Ubuntu VPS from `git clone` to a healthy running
agent on @ByteRelevant via `docker compose up -d`. Estimated time: 30-45 min
for a first-time operator.

## 1. Prerequisites
- Ubuntu 22.04+ (or 24.04 LTS)
- 2 GB RAM, 5 GB free disk, x86_64 CPU
- Docker Engine ≥26 + Compose v2 plugin (`docker compose` not `docker-compose`)
- Git
- Outbound HTTPS to: api.anthropic.com, api.x.com, all 5 source domains

Verification: `docker --version && docker compose version && git --version`

## 2. Secrets Acquisition
1. Anthropic API key — console.anthropic.com → Settings → API Keys
2. X Developer Portal (for @ByteRelevant):
   - App must have Read AND Write permissions BEFORE token generation
   - Generate 4 OAuth 1.0a User Context tokens: consumer_key, consumer_secret,
     access_token, access_token_secret
3. Validate via `scripts/smoke_anthropic.py` + `scripts/smoke_x_auth.py` (see §5)

## 3. Clone + Configure
```bash
git clone https://github.com/<user>/tech-news-synth.git
cd tech-news-synth
cp .env.example .env
$EDITOR .env   # fill in 5 secrets; leave DRY_RUN=1 for first boot
```

## 4. Boot
```bash
docker compose up -d --build
docker compose ps       # both services should be healthy within 60s
docker compose logs -f app
```

## 5. First-Cycle Verification
- Scheduler fires immediately on boot (D-07). Watch for:
  - `cycle_start` log event
  - `source_fetch_*` events (one per source)
  - `cluster_winner` or `cluster_fallback` or `publish_skipped_empty_selection`
  - `synth_done` (if non-empty window)
  - `publish_skipped_dry_run` (since DRY_RUN=1)
  - `cycle_summary` — the single aggregated line
- Sanity SQL: `docker compose exec postgres psql -U app -d tech_news_synth -c "SELECT * FROM run_log ORDER BY started_at DESC LIMIT 1;"`
- GATE smoke scripts (optional, costs real money on the X side):
  - `docker compose exec app uv run python scripts/smoke_anthropic.py`
  - `docker compose exec app uv run python scripts/smoke_x_auth.py`

## 6. Daily Operations
- Logs: `docker compose logs -f app` or tail `/data/logs/app.jsonl` via volume mount
- Source health: `docker compose exec app python -m tech_news_synth source-health`
- Force off-cadence: `docker compose exec app python -m tech_news_synth post-now`
- Replay past cycle: `docker compose exec app python -m tech_news_synth replay --cycle-id 01KP...`
- Kill switch: `docker compose exec app touch /data/paused` (live toggle, no restart)
- Dry-run toggle: edit `.env` DRY_RUN=1, then `docker compose restart app`

## 7. Soak + Cutover
### 7.1 48h DRY_RUN Soak (required before live cutover)
```bash
# Ensure DRY_RUN=1 in .env
docker compose up -d
# In another terminal on the host:
docker compose run --rm app uv run python scripts/soak_monitor.py
# Monitor runs for 48h; Ctrl+C prints final summary.
# Pass criteria: ≥24 cycles, 0 unhandled, ≤2 failed, every cycle has cycle_summary.
```

### 7.2 Live Cutover
1. Confirm soak PASSED (see `.planning/intel/soak-log.md`)
2. Edit `.env`: set `DRY_RUN=0`
3. `docker compose restart app`
4. Monitor first 3 cycles live: `docker compose logs -f app | grep cycle_summary`
5. Visual check: visit https://x.com/ByteRelevant — real tweets should appear
6. After 24h: `docker compose run --rm app uv run python scripts/cutover_verify.py`
7. If all green: commit `.planning/intel/cutover-report.md` to git.

### 7.3 Rollback
```bash
$EDITOR .env  # DRY_RUN=0 → DRY_RUN=1
docker compose restart app
# Investigate pending rows from the cutover window:
docker compose exec postgres psql -U app -d tech_news_synth -c \
  "SELECT * FROM posts WHERE status='pending' AND created_at > '<cutover_ts>';"
# Manually delete rows / X tweets as needed.
```

## 8. Troubleshooting
- **Orphaned pending posts:** see `docs/runbook-orphaned-pending.md`
- **Source disabled:** `python -m tech_news_synth source-health --enable NAME`
- **Anthropic errors:** check `ANTHROPIC_API_KEY` and quota at console.anthropic.com
- **X 429 rate limit:** Phase 7 handles automatically (logs + skips rest of cycle)
- **Daily cap reached:** check `publish_status=capped` in logs; next cycle at UTC midnight
- **Monthly cost cap:** hard kill-switch; raise `MAX_MONTHLY_COST_USD` in `.env` + restart
- **Container unhealthy:** `docker compose logs --tail=100 app` and `docker compose logs postgres`

## 9. References
- `.planning/intel/x-api-baseline.md` — Phase 3 GO decision + cost baseline
- `docs/runbook-orphaned-pending.md` — stale-pending recovery
- `.planning/PROJECT.md` — vision, constraints
- `CLAUDE.md` — tech stack rationale
```

### 4. Two New `source_state.py` Helpers (Full Listing)

See Pattern 5. Adds `enable_source`, `disable_source`, `get_all_source_states` — ~20 lines total.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Emit per-phase log events only | Per-phase events + one aggregated `cycle_summary` | This phase | Operator gets one-line cycle view; per-phase stays for debug |
| Pairwise cosine across stored centroids | Jaccard over `centroid_terms` (per-cycle TF-IDF has differing vocabs) | This phase | Simpler audit; deterministic; no new fitting |
| Cron inside container | APScheduler PID 1 | Phase 1 (inherited) | Not changed here |
| Alerts to Discord/PagerDuty | structlog JSON + grep | Deferred to v2 | Operator reads logs; no new deps |

**Deprecated/outdated:** None — no libraries to upgrade in this phase.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Phase 5 `run_clustering` stores `fallback_article_id` in its `counts_patch` dict | §Pattern 3 `replay` | If absent, `replay` can't reconstruct fallback selections — either add it to Phase 5 (one-line change), or require implementer to look up via window re-query. [VERIFY at implementation time by reading `src/tech_news_synth/cluster/orchestrator.py`.] |
| A2 | `clusters.member_article_ids` column exists on the `Cluster` model | §Pattern 3 | If the column is named differently (e.g., `article_ids`), adjust query. [VERIFY by reading `db/models.py::Cluster`.] — code grep shows `clusters.chosen` + `centroid_terms` exist; `member_article_ids` is referenced in Phase 5 SUMMARY but needs column-name confirmation. |
| A3 | `posts.cycle_id` is indexed / queryable | §Pattern 3 | Replay's `SELECT * FROM posts WHERE cycle_id=:cid` must be fast; at 12 posts/day × 14-day retention = 168 rows, even sequential scan is fine — no risk. |
| A4 | `docker compose run --rm app` works for `soak_monitor.py` invocation from host | §Pitfall 4 | If compose config doesn't allow side-car runs with DB access, fall back to `docker compose exec app` with a `nohup` wrapper. Low risk — standard compose pattern. |
| A5 | Cutover cost baseline is $0.03/post × 12 = $0.36/24h (from Phase 3 `x-api-baseline.md`) | §`cutover_verify.py` | Number quoted in CONTEXT D-10 matches Phase 3 intel; if actual baseline differs, update the 2× multiplier reference. |
| A6 | `run_log.counts` is JSONB (not TEXT) | §soak_monitor + cutover_verify | [VERIFIED] Phase 4-7 SUMMARIES all reference `counts JSONB`. |
| A7 | Operator has `psql` or `docker compose exec postgres psql` available for SQL verification steps in DEPLOY.md | §DEPLOY.md | If not, wrap queries in `scripts/` helpers. Low risk — psql ships in the `postgres:16-bookworm` image. |
| A8 | `cycle_started_at` can be captured at top of `run_cycle` without breaking existing tests | §Pattern 1 emit | Phase 1-7 tests patch `run_cycle` components (ingest, cluster, synth, publish) but not the top-level entry. Low risk — adding a local variable is additive. |

**User confirmation needed before planning:**
- **A1 (fallback_article_id storage):** planner should decide upfront — either (a) amend Phase 5 `counts_patch` to include it (clean, one-line), or (b) document that `replay` doesn't support fallback-cycle replay in v1 and exits 1 with a clear message. **Recommend (a).**

---

## Open Questions

1. **Does Phase 5 `run_clustering` already populate `fallback_article_id` in `counts_patch`?**
   - What we know: Phase 5 SUMMARY lists `counts_patch` keys but doesn't enumerate them fully.
   - What's unclear: The exact key name and presence.
   - Recommendation: Implementer reads `src/tech_news_synth/cluster/orchestrator.py` in Task 1 of Sub-scope B. If absent, file a one-line amendment: `counts_patch["fallback_article_id"] = article.id if fallback else None`. Treat as in-scope for Phase 8.

2. **Should `cycle_summary` include a `phase_durations` breakdown** (ingest_ms, cluster_ms, synth_ms, publish_ms)?
   - What we know: D-06 locks 10 fields; phase durations are NOT on the list.
   - What's unclear: Whether to add as bonus for debugging.
   - Recommendation: **Don't add in Phase 8.** D-06 is explicit. Per-phase events already carry enough context for debugging.

3. **Should `post-now` block on another `post-now` / scheduler tick running?**
   - What we know: D-02 says "safe to run while scheduler is up".
   - What's unclear: Whether to add a lightweight advisory lock (Postgres `pg_try_advisory_lock`) to prevent concurrent cycles.
   - Recommendation: **Don't add.** Concurrent cycles are self-limiting (cap check, anti-repeat); advisory lock adds complexity and new failure mode. Document "don't run post-now twice in quick succession" in DEPLOY.md §Daily Ops.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x (+ pytest-mock, respx, freezegun/time-machine) — existing |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/unit -q` |
| Full suite command | `POSTGRES_HOST=<test-host> uv run pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OPS-01 | Each cycle emits one `cycle_summary` log line with 10 fields | integration | `pytest tests/integration/test_cycle_summary.py -x` | ❌ Wave 0 |
| OPS-01 | `cycle_summary` NOT emitted on paused cycle (no DB row) | unit | `pytest tests/unit/test_scheduler.py::test_paused_cycle_emits_no_summary -x` | ❌ Wave 0 |
| OPS-02 | `replay --cycle-id X` prints JSON to stdout, no new posts row | integration | `pytest tests/integration/test_cli_replay.py -x` | ❌ Wave 0 |
| OPS-02 | `replay --cycle-id UNKNOWN` exits 1 with error to stderr | unit | `pytest tests/unit/test_cli_replay.py::test_replay_unknown_cycle_exits_1 -x` | ❌ Wave 0 |
| OPS-02 | `run_synthesis(persist=False)` returns `post_id=None` and writes no row | unit | `pytest tests/unit/test_synth_orchestrator.py::test_persist_false_skips_insert -x` | ❌ Wave 0 |
| OPS-03 | `post-now` invokes `run_cycle` once and writes a `run_log` row | integration | `pytest tests/integration/test_cli_post_now.py::test_writes_run_log -x` | ❌ Wave 0 |
| OPS-03 | `post-now` honors DRY_RUN=1 (no X API call) | integration | `pytest tests/integration/test_cli_post_now.py::test_respects_dry_run -x` | ❌ Wave 0 |
| OPS-03 | `post-now` respects daily cap (exits with `publish_status=capped` in counts) | integration | `pytest tests/integration/test_cli_post_now.py::test_respects_cap -x` | ❌ Wave 0 |
| OPS-04 | `source-health` no-args prints 5-col table with all sources | integration | `pytest tests/integration/test_cli_source_health.py::test_status_mode -x` | ❌ Wave 0 |
| OPS-04 | `source-health --enable NAME` clears `disabled_at` | integration | `pytest tests/integration/test_cli_source_health.py::test_enable_persists -x` | ❌ Wave 0 |
| OPS-04 | `source-health --disable NAME` sets `disabled_at` | integration | `pytest tests/integration/test_cli_source_health.py::test_disable_persists -x` | ❌ Wave 0 |
| OPS-04 | `source-health --enable UNKNOWN` exits 1 | unit | `pytest tests/unit/test_cli_source_health.py::test_enable_unknown_exits_1 -x` | ❌ Wave 0 |
| OPS-05 | DEPLOY.md runbook walks fresh VPS to healthy agent | **manual** | Operator executes on clean Ubuntu VPS; documents outcome in `.planning/intel/deploy-validation.md` | N/A (doc) |
| OPS-06 | 48h soak passes (D-08 criteria) | **manual** | `scripts/soak_monitor.py` runs 48h; operator verifies `.planning/intel/soak-log.md` | N/A (live run) |
| SC-5 | Cutover: ≥12 posts/24h, zero 48h dupes, cost within 2× baseline | **manual** | `scripts/cutover_verify.py` runs post-24h; operator verifies `.planning/intel/cutover-report.md` | N/A (live run) |
| `cutover_verify.py` Jaccard logic | Unit test with fixture dict pairs | unit | `pytest tests/unit/test_cutover_verify.py::test_jaccard_flags_ge_0_5 -x` | ❌ Wave 0 |
| `soak_monitor.py` invariant checks | Unit test with seeded run_log rows | integration | `pytest tests/integration/test_soak_monitor.py -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/unit -q` (existing ~320 unit tests + Phase 8 adds ~15)
- **Per wave merge:** `POSTGRES_HOST=<test-host> uv run pytest tests/ -q` (~462 existing + ~15 Phase 8 = ~477)
- **Phase gate:** Full suite green + operator signs off on OPS-05 + OPS-06 + SC-5 manual criteria before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/integration/test_cycle_summary.py` — covers OPS-01 happy path + all 10 fields
- [ ] `tests/unit/test_cli_replay.py` — covers OPS-02 error paths
- [ ] `tests/integration/test_cli_replay.py` — covers OPS-02 happy path (mocked Anthropic)
- [ ] `tests/integration/test_cli_post_now.py` — covers OPS-03 (3 scenarios)
- [ ] `tests/unit/test_cli_source_health.py` — covers OPS-04 error paths
- [ ] `tests/integration/test_cli_source_health.py` — covers OPS-04 happy paths
- [ ] `tests/unit/test_cutover_verify.py` — covers Jaccard logic
- [ ] `tests/integration/test_soak_monitor.py` — covers invariant checks against seeded DB
- [ ] `scripts/soak_monitor.py` — stub skeleton
- [ ] `scripts/cutover_verify.py` — stub skeleton
- [ ] `docs/DEPLOY.md` — stub outline
- [ ] `.planning/intel/soak-log.md` — operator-filled template
- [ ] `.planning/intel/cutover-report.md` — operator-filled template

No framework install needed — pytest + pytest-mock already in Phase 1-7 dev deps.

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | X OAuth 1.0a User Context (Phase 3 inherited); Anthropic API key (inherited); `cutover_verify.py` + CLIs reuse existing `Settings.SecretStr` loader |
| V3 Session Management | no | No HTTP endpoints added in this phase |
| V4 Access Control | partial | CLIs are operator-only (container exec); no HTTP exposure. `source-health --enable/--disable` is an audit-logged state mutation. |
| V5 Input Validation | yes | `argparse` provides basic validation; `--cycle-id` format check (ULID 26-char); `--enable/--disable NAME` validates against existing source_state rows (returns False on unknown) |
| V6 Cryptography | no | No new crypto operations; existing SecretStr loading unchanged |
| V7 Error Handling | yes | `replay`/`post-now` never echo API keys in error output; structlog already redacts SecretStr fields (Phase 1 pattern) |
| V9 Communications | yes | All HTTPS outbound via existing httpx + Anthropic SDK + tweepy; inherited from Phase 3/4/6/7 |
| V10 Malicious Code | no | No new code execution paths (no eval, no plugin loading) |

### Known Threat Patterns for Phase 8

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| T-08-01 `post-now` bypasses daily cap | Elevation | D-02 locks all guardrails reuse via `run_cycle()` path; cap check runs unconditionally |
| T-08-02 `replay` accidentally writes a `posts` row | Tampering | Keyword-only `persist` parameter + unit test asserting `post_id is None` + integration test asserting no new row |
| T-08-03 `source-health --enable` race with cycle auto-disable | Tampering | Accepted — last-write-wins; operator workflow; documented in DEPLOY.md |
| T-08-04 `cutover_verify.py` leaks secrets into `.planning/intel/cutover-report.md` | Info Disclosure | Never `print(settings)`; SecretStr is redacted by default; pre-commit hook scans intel files (INFRA-04) |
| T-08-05 `soak_monitor.py` crashes silently, operator thinks soak is passing | Denial | stderr logging on every red flag; final summary on Ctrl+C; non-zero exit on threshold breach |
| T-08-06 `cycle_summary` leaks sensitive data (secrets, PII) | Info Disclosure | Only whitelisted scalar fields from `counts` dict; no `settings` object dump; review all 10 fields against D-06 |
| T-08-07 Cutover rollback leaves pending posts that publish on next cycle | Tampering | D-09 rollback = `DRY_RUN=1` which short-circuits publish; Phase 7 `cleanup_stale_pending` marks stragglers as `failed`, not re-posted |
| T-08-08 `post-now` invoked with production secrets in a dev container | Info Disclosure / Elevation | Operator responsibility; documented in DEPLOY.md; out-of-band enforcement (separate `.env` per environment) |

---

## Sources

### Primary (HIGH confidence)

- [VERIFIED] `.planning/phases/08-end-to-end-hardening/08-CONTEXT.md` — D-01..D-13 locked decisions
- [VERIFIED] `.planning/REQUIREMENTS.md` §OPS-01..OPS-06
- [VERIFIED] `.planning/ROADMAP.md` §"Phase 8: End-to-End + Hardening"
- [VERIFIED] `.planning/phases/01-foundations/01-CONTEXT.md` — D-06 subcommand dispatcher contract
- [VERIFIED] `.planning/phases/04-ingestion/04-02-SUMMARY.md` — counts schema, source_state helpers
- [VERIFIED] `.planning/phases/05-cluster-rank/05-02-SUMMARY.md` — SelectionResult shape, counts_patch keys, D-01 per-cycle TF-IDF insight
- [VERIFIED] `.planning/phases/06-synthesis/06-02-SUMMARY.md` — `run_synthesis` signature, `post_id` in SynthesisResult
- [VERIFIED] `.planning/phases/07-publish/07-02-SUMMARY.md` — D-12 scheduler order, `publish_status` in counts, stale-pending guard
- [VERIFIED via code read] `src/tech_news_synth/__main__.py` — existing argparse dispatcher + boot order
- [VERIFIED via code read] `src/tech_news_synth/cli/{replay,post_now,source_health}.py` — stub files with `NotImplementedError`
- [VERIFIED via code read] `src/tech_news_synth/scheduler.py::run_cycle` — finally block, session lifecycle
- [VERIFIED via code read] `src/tech_news_synth/db/run_log.py` — `finish_cycle` uses `flush()`, caller commits
- [VERIFIED via code read] `src/tech_news_synth/db/source_state.py` — existing helpers (no `enable_source`/`disable_source`/`get_all_source_states` yet)
- [VERIFIED via code read] `src/tech_news_synth/synth/orchestrator.py::run_synthesis` — signature, persistence flow
- [VERIFIED via code read] `src/tech_news_synth/cluster/antirepeat.py::check_antirepeat` — Phase 5 FittedCorpus pattern (confirms per-cycle feature space)
- [VERIFIED via code read] `src/tech_news_synth/db/models.py` — `clusters.chosen`, `clusters.centroid_terms` (JSONB), `posts.theme_centroid` (BYTEA)
- [VERIFIED via code read] `src/tech_news_synth/cluster/models.py::SelectionResult` — fields
- [VERIFIED via code read] `scripts/smoke_anthropic.py` + `scripts/smoke_x_post.py` — established CLI patterns (argparse, SecretStr inline, JSON stdout, stderr banner)
- [VERIFIED via code read] `docs/runbook-orphaned-pending.md` — existing runbook style to cross-reference in DEPLOY.md

### Secondary (MEDIUM confidence)

- [CITED: `CLAUDE.md`] — tech stack authoritative (Python 3.12, no new deps, structlog, SQLAlchemy 2.0, APScheduler 3.10)

### Tertiary (LOW confidence) — None

All claims in this phase's research are backed by direct code inspection or locked CONTEXT decisions. No external library docs needed (no new dependencies).

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; every dep already in pyproject.toml and verified via Phase 1-7 SUMMARIES
- Architecture: HIGH — emit point locked by D-04, CLI structure locked by D-01/02/03, scripts pattern established by Phase 3 smoke scripts
- Pitfalls: HIGH — all pitfalls derived from reading actual scheduler/orchestrator code + locked decisions
- Assumptions: MEDIUM — A1 (fallback_article_id storage in Phase 5 counts_patch) requires implementation-time verification; all others low-risk

**Research date:** 2026-04-14
**Valid until:** 2026-05-14 (30 days — stable, no moving external deps)
