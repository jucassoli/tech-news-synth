---
phase: 06
slug: synthesis
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-14
---

# Phase 06 — Validation Strategy

> Per-phase validation contract. Mix of unit (pure-function tests) + integration (full pipeline with mocked Anthropic) + manual fixture spot-check (10 synthesized posts ≤ 280 weighted chars).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (inherits Phase 1-5 config) |
| **Config file** | `pyproject.toml` — no new markers |
| **Quick run command** | `uv run pytest tests/unit/test_synth_* tests/unit/test_charcount.py tests/unit/test_truncate.py tests/unit/test_hashtags.py tests/unit/test_article_picker.py -q -x --ff` |
| **Full unit** | `uv run pytest tests/unit -q` |
| **Integration** | `uv run pytest tests/integration -q -x -m integration` |
| **Full suite** | `uv run pytest tests/ -v --cov=tech_news_synth` |
| **Estimated runtime** | ~3s unit, ~10s integration (with mocked Anthropic) |

---

## Sampling Rate

- **After every task commit:** quick run (synth-touched files only).
- **After Wave 1 (pure modules + hashtags):** full unit suite.
- **After Wave 2 (orchestrator + scheduler):** full unit + integration.
- **Before `/gsd-verify-work`:** full suite green + 10-post fixture spot-check (every synthesized post ≤ 280 weighted chars after final formatting) + one compose smoke cycle.
- **Max feedback latency:** ~3s unit, ~15s integration.

---

## Per-Requirement Verification Map

| Requirement | Test Type | Automated Command | Wave 0 Dep |
|-------------|-----------|-------------------|------------|
| SYNTH-01 (model="claude-haiku-4-5", max_tokens=150, input limited to titles+summaries) | unit | `pytest tests/unit/test_synth_client.py -q` (asserts model id literal, max_tokens, no full bodies in user content) | `tests/unit/test_synth_client.py` |
| SYNTH-02 (PT-BR jornalístico neutro + grounding guardrails verbatim) | unit | `pytest tests/unit/test_synth_prompt.py -q` (asserts system prompt contains "jornalístico", "neutro", "português", "APENAS", "NÃO invente"; user prompt has `Fonte:`/`Título:`/`Resumo:` framing) | `tests/unit/test_synth_prompt.py` |
| SYNTH-03 (grounding rules same as SYNTH-02) | unit | covered by `test_synth_prompt.py` | (same) |
| SYNTH-04 (≤280 weighted chars; 2 retries; word-boundary truncate + ellipsis) | unit + integration | `pytest tests/unit/test_charcount.py tests/unit/test_truncate.py tests/unit/test_synth_orchestrator.py -q` (charcount roundtrip, truncate edge cases, retry loop with mock LLM returning over-budget then under-budget) + `pytest tests/integration/test_synth_fixtures.py -q` (10 fixture posts, every weighted_len ≤ 280) | `tests/unit/test_charcount.py`, `tests/unit/test_truncate.py`, `tests/unit/test_synth_orchestrator.py`, `tests/integration/test_synth_fixtures.py`, `tests/fixtures/synth/{post_01..post_10}.json` |
| SYNTH-05 (1-2 hashtags from allowlist; LLM does not freestyle) | unit | `pytest tests/unit/test_hashtags.py -q` (cluster centroid_terms → matched topic tags; cap at 2; default `[#tech]` on no match; never freestyles a tag not in allowlist) | `tests/unit/test_hashtags.py`, `tests/fixtures/synth/hashtags.yaml` |
| SYNTH-06 (final format `<text> <url> <hashtag(s)>`; URL always present; 1-2 hashtags) | unit + integration | `pytest tests/unit/test_synth_format.py -q` + `pytest tests/integration/test_synth_fixtures.py -q` | `tests/unit/test_synth_format.py` |
| SYNTH-07 (input_tokens + output_tokens + cost_usd logged AND on posts row) | integration | `pytest tests/integration/test_synth_persist.py -q` (after run_synthesis, posts row has cost_usd populated; cycle log captured by structlog testing fixture has all three fields) | `tests/integration/test_synth_persist.py` |

**Cross-cutting — diverse-source picker (D-01):** `tests/unit/test_article_picker.py` covers: cluster of 2 → both returned; cluster of 8 across 3 sources → 1+1+1 + 2 fillers (5 total); cluster of 3 same source → all 3.

**Cross-cutting — URL choice (D-02):** `tests/unit/test_url_picker.py` asserts highest-weight + recency tiebreak deterministic.

**Cross-cutting — DRY_RUN (D-12):** `tests/integration/test_synth_dry_run.py` — posts row written with `status='dry_run'` AND `synthesized_text` populated AND `cost_usd > 0` (Anthropic still called).

**Cross-cutting — Centroid plumbing:** `tests/unit/test_selection_result.py` asserts SelectionResult accepts `winner_centroid: bytes | None` (default None for backward compat); cluster orchestrator unit test still green after extension.

**Cross-cutting — scheduler wiring:** `tests/unit/test_scheduler.py` extended — mock `run_synthesis` returning canned counts; assert call ordering `run_ingest → run_clustering → run_synthesis → finish_cycle`; assert `synthesis.counts_patch` merged into final counts.

**Cross-cutting — empty-window short-circuit:** `tests/unit/test_synth_skipped.py` — when SelectionResult has both winner=None AND fallback_article_id=None, run_synthesis is NOT called (orchestrator early-exits).

**Cross-cutting — anthropic API error propagation:** `tests/unit/test_synth_error.py` — mock `client.messages.create` raises `anthropic.APIError`; assert exception propagates (no swallowing); cycle marked failed by Phase 1's existing INFRA-08 isolation.

---

## Wave 0 Requirements

- [ ] `twitter-text-parser>=3,<4` added to `pyproject.toml` → `uv sync` → `uv.lock` regenerated
- [ ] `src/tech_news_synth/synth/` package tree (`__init__.py`, `prompt.py`, `client.py`, `charcount.py`, `truncate.py`, `hashtags.py`, `article_picker.py`, `url_picker.py`, `pricing.py`, `orchestrator.py`, `models.py`)
- [ ] `config/hashtags.yaml` committed with starter topic→tag map (per CONTEXT specifics)
- [ ] `src/tech_news_synth/cluster/models.py::SelectionResult` extended with `winner_centroid: bytes | None = None` (backward-compat default)
- [ ] `src/tech_news_synth/db/posts.py` extended with `insert_post(...)` accepting all fields per CONTEXT D-08/09/10 (status, theme_centroid, synthesized_text, hashtags, cost_usd, error_detail, cluster_id nullable, cycle_id, created_at server_default). Existing helpers untouched.
- [ ] `src/tech_news_synth/db/articles.py::get_articles_by_ids(session, ids)` helper (preserves input order)
- [ ] Settings extended with 4 new fields per CONTEXT D-13 + `.env.example` + `tests/unit/test_config.py`
- [ ] Fixture pack `tests/fixtures/synth/post_01..post_10.json` — 10 cluster fixtures covering: hot-topic 5-source, 2-article cluster, fallback solo article, very-long titles, accented PT chars (proves twitter-text-parser handles them as 1 weighted char), tech-jargon-heavy, mixed PT+EN — used by `test_synth_fixtures.py` integration spot-check
- [ ] `tests/fixtures/synth/hashtags.yaml` — minimal allowlist for tests
- [ ] Red-stub test files for everything in the per-requirement table

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real cycle synthesizes a real Haiku 4.5 post under the budget | SYNTH-01..06 | Live API call (real cost) | After Phase 6 compose smoke: `docker compose exec postgres psql -U app -d tech_news_synth -c "SELECT id, status, length(synthesized_text), substring(synthesized_text from 1 for 200) FROM posts ORDER BY created_at DESC LIMIT 3;"` — synthesized_text is PT-BR, ≤ 280 visible chars (visual check; weighted may differ slightly), ends with URL + hashtag(s). |
| posts row has cost_usd populated | SYNTH-07 | Live call | Same query: cost_usd > 0 and < 0.001. |
| 10-fixture spot-check passes (operator visually reviews PT-BR quality) | SYNTH-04 | Quality judgment | `uv run pytest tests/integration/test_synth_fixtures.py -v` — operator skims the 10 generated post strings for: PT-BR fluent, no hallucinated facts (cross-check against fixture article inputs), no weird truncation mid-word, hashtags from allowlist. |
| DRY_RUN cycle writes posts row with status='dry_run' | SYNTH-04 + D-12 | Live (with DRY_RUN=1) | Set `DRY_RUN=1` in `.env`, restart compose, wait one cycle, query: `SELECT status, cost_usd FROM posts ORDER BY created_at DESC LIMIT 1;` — status='dry_run', cost_usd>0. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` (unit/integration) or `<manual>` verify
- [ ] twitter-text-parser added; charcount roundtrip verified for accented PT, emoji, t.co URLs
- [ ] 10-fixture spot-check passes (every synthesized post ≤ 280 weighted)
- [ ] Phase 1-5 baseline preserved (226 unit + 61 integration)
- [ ] Anthropic API errors propagate (not swallowed)
- [ ] DRY_RUN writes posts row with correct status
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
