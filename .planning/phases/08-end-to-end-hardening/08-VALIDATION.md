---
phase: 08
slug: end-to-end-hardening
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-14
---

# Phase 08 — Validation Strategy

> Final phase. Mix of unit/integration tests for CLIs + cycle_summary emission, plus operator-driven manual verification for soak and cutover.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (inherits Phase 1-7 config) |
| **Config file** | `pyproject.toml` — no new markers |
| **New deps** | **NONE** (Phase 8 is pure composition) |
| **Quick run command** | `uv run pytest tests/unit/test_cli_* tests/unit/test_cycle_summary.py -q -x --ff` |
| **Full unit** | `uv run pytest tests/unit -q` |
| **Integration** | `uv run pytest tests/integration -q -x -m integration` |
| **Full suite** | `uv run pytest tests/ -v --cov=tech_news_synth` |
| **Estimated runtime** | ~3s unit, ~10s integration |

---

## Sampling Rate

- **After every task commit:** quick run of Phase-8-touched tests.
- **After CLI tasks:** full unit + integration.
- **After scheduler cycle_summary task:** full unit + integration (scheduler is exercised by many tests).
- **Before `/gsd-verify-work`:** full suite green + operator starts 48h soak monitoring + compose smoke proves cycle_summary emits one line per cycle.
- **Max feedback latency:** ~3s unit, ~15s integration.

---

## Per-Requirement Verification Map

| Requirement | Test Type | Automated Command | Wave 0 Dep |
|-------------|-----------|-------------------|------------|
| OPS-01 (cycle_summary emitted per cycle with 10 fields) | unit + integration | `pytest tests/unit/test_cycle_summary.py -q` (scheduler mocked end-to-end; structlog capture asserts single "cycle_summary" event with all 10 fields present + correct types) + `pytest tests/integration/test_cycle_summary_e2e.py -q` (real DB cycle, `grep cycle_summary` in stdout capture) | `tests/unit/test_cycle_summary.py`, `tests/integration/test_cycle_summary_e2e.py` |
| OPS-02 (`replay --cycle-id X` re-runs synthesis without publishing) | integration | `pytest tests/integration/test_cli_replay.py -q` (seed a completed cycle with clusters+articles+post; subprocess-invoke `python -m tech_news_synth replay --cycle-id <id>`; assert stdout is valid JSON with `text`, `hashtags`, `cost_usd`; assert NO new posts row created; assert Anthropic called once via mock) | `tests/integration/test_cli_replay.py` |
| OPS-03 (`post-now` forces off-cadence cycle respecting guardrails) | integration | `pytest tests/integration/test_cli_post_now.py -q` (subprocess-invoke `python -m tech_news_synth post-now`; assert run_log row written; assert scheduled tick not affected; assert PAUSED=1 causes early exit; assert DRY_RUN=1 writes status='dry_run' posts row) | `tests/integration/test_cli_post_now.py` |
| OPS-04 (`source-health` prints status + `--enable`/`--disable`) | integration | `pytest tests/integration/test_cli_source_health.py -q` (seed source_state rows; subprocess-invoke with no args assert tabular output; invoke `--enable NAME` assert row updated; invoke `--disable NAME` assert row updated; invoke `--enable UNKNOWN` assert exit 1) | `tests/integration/test_cli_source_health.py` |
| OPS-05 (DEPLOY.md walks VPS from clone to healthy agent) | manual | operator reads `docs/DEPLOY.md` on a fresh Ubuntu VPS and follows steps — no automated check | `docs/DEPLOY.md` |
| OPS-06 (48h DRY_RUN soak, ≥24 cycles, zero unhandled exceptions) | manual + script | operator runs `scripts/soak_monitor.py` which polls every 30 min for 48h and writes to `.planning/intel/soak-log.md`; pass criteria per CONTEXT D-08 | `scripts/soak_monitor.py`, `.planning/intel/soak-log.md` template |

**Cross-cutting — `run_synthesis(persist=False)`:** `tests/unit/test_synth_orchestrator.py` extended with `test_persist_false_skips_insert_post` — mocks insert_post; calls run_synthesis(persist=False); asserts insert_post NOT called; SynthesisResult returned with `post_id=None` and `status='replay'`. Phase 6 tests pass `persist=True` explicitly (or use default) and stay green.

**Cross-cutting — scheduler cycle_summary emit:** `scheduler.run_cycle` extended to emit `cycle_summary` in the `finally` block AFTER `session.commit()` succeeds. Paused cycles skip (no session). Failed cycles still emit with `status='failed'` and partial counts. Unit test asserts emit ordering via structlog capture.

**Cross-cutting — Phase 5 `fallback_article_id` in counts_patch:** Research §A1 flagged that `run_clustering` may not persist this field. Plan Task (Sub-scope A) confirms/amends `cluster/orchestrator.py` to include `fallback_article_id` in `counts_patch` so `replay` CLI can reconstruct fallback-cycle selections.

**Cross-cutting — cutover_verify Jaccard audit:** `scripts/cutover_verify.py` uses Jaccard similarity over `clusters.centroid_terms` JSONB keys (NOT cosine over theme_centroid bytes — per-cycle vocab mismatch). Unit test `tests/unit/test_cutover_verify.py` covers: 0 dups clean pass; 1 pair > 0.5 Jaccard flagged.

---

## Wave 0 Requirements

- [ ] `src/tech_news_synth/cli/{replay,post_now,source_health}.py` — replace Phase 1 stub bodies (package tree already exists)
- [ ] `scripts/soak_monitor.py` — new file
- [ ] `scripts/cutover_verify.py` — new file
- [ ] `docs/DEPLOY.md` — new file (structure per CONTEXT D-11)
- [ ] `.planning/intel/soak-log.md` — template file (filled during soak)
- [ ] `.planning/intel/cutover-report.md` — template file (filled after cutover)
- [ ] `src/tech_news_synth/db/source_state.py` — verify/add `enable_source(session, name)` + `disable_source(session, name)` + `get_all_source_states(session)` helpers
- [ ] `src/tech_news_synth/synth/orchestrator.py::run_synthesis` — extend with `persist: bool = True` keyword-only arg
- [ ] Phase 5 `cluster/orchestrator.py` — verify `fallback_article_id` in `counts_patch`; amend if missing
- [ ] Red-stub test files for every per-requirement row above (pytest.skip until code lands)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `cycle_summary` appears in live logs | OPS-01 | Requires live compose + cycle observation | `docker compose up -d --build && sleep 90 && docker compose logs app | grep cycle_summary | head -3` — at least 1 line with all 10 fields populated (parse with `jq` if available). |
| `docker compose exec app python -m tech_news_synth source-health` prints real state | OPS-04 | Requires live DB | After one cycle: run command, observe 5 rows (techcrunch, verge, ars_technica, hacker_news, reddit_technology) with last_fetched_at populated. |
| `python -m tech_news_synth post-now` triggers a cycle immediately | OPS-03 | Requires live compose | `docker compose exec app python -m tech_news_synth post-now` — blocks ~60s, prints cycle_summary line with new cycle_id, exits 0. |
| DEPLOY.md walks fresh VPS to healthy agent | OPS-05 | Validated by human reading on a fresh Ubuntu box | Operator provisions a fresh Ubuntu 22.04+ VPS, runs through DEPLOY.md step-by-step, confirms agent is healthy + first cycle emits cycle_summary. No automated check. |
| 48h DRY_RUN soak passes D-08 criteria | OPS-06 | 48h wall-clock | Operator runs `nohup python scripts/soak_monitor.py --hours 48 &` on host (needs Settings + DB access), periodically checks stdout + `.planning/intel/soak-log.md`. Pass: ≥24 cycles, zero unhandled exceptions, ≤2 transient failures. |
| Post-cutover: ≥12 tweets/24h, 0 dupes, cost within 2× baseline | SC-5 | Requires 24h live | Operator flips DRY_RUN=0 per DEPLOY.md checklist, monitors first 3 cycles manually, waits 24h, runs `python scripts/cutover_verify.py` — outputs report to `.planning/intel/cutover-report.md` with GO/NO-GO verdict. |

---

## Validation Sign-Off

- [ ] All code tasks have `<automated>` verify (unit or integration)
- [ ] All operator tasks have `<manual>` steps with clear pass criteria
- [ ] Wave 0 fixtures + stubs created before Wave 1 implementation
- [ ] Phase 1-7 baseline preserved (363 unit + 99 integration)
- [ ] No new deps; no schema changes
- [ ] Soak + cutover runbook + scripts ready for operator execution
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
