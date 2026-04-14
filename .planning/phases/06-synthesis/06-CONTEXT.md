# Phase 6: Synthesis - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Take the Phase 5 `SelectionResult` (winning cluster OR fallback article) and synthesize a grounded PT-BR jornalístico-neutro post that fits inside X's 280-char weighted budget, then write a `posts` row with `status='pending'`, the synthesized text, the chosen hashtags, the source URL, and the cost/token telemetry. Scope includes: cluster→prompt-input selection (3-5 articles by source diversity), source-URL choice (highest weight + recency), prompt construction (system + user messages with grounding guardrails), Anthropic SDK call with `claude-haiku-4-5` + `max_tokens=150`, weighted char-count budget enforcement via `twitter-text-parser` lib, 2 re-prompt retries + last-resort word-boundary truncation, hashtag allowlist selection, posts-row write with cost. Out of scope: actual X API publish call (Phase 7), daily/monthly cost-cap kill-switch logic (Phase 7), tweet-id capture (Phase 7).

</domain>

<decisions>
## Implementation Decisions

### Cluster Article Selection for Prompt
- **D-01:** **Diverse-sources-first selection of 3-5 articles.** Algorithm: from cluster's `member_article_ids` Article rows, take ONE article per distinct source (most recent per source) up to 5 distinct sources. If cluster spans <5 sources, fill remaining slots with next-most-recent articles from already-represented sources until 5 OR until cluster exhausted. Honors the project's Core Value ("ângulo único de cada fonte") by guaranteeing every source contributes an angle when present.
- **D-02:** **Source URL choice = highest source-weight + recency tiebreak.** From the SELECTED 3-5 articles (D-01), sort by `(source.weight DESC, published_at DESC, id ASC)` and use the #1 article's `url` as the post's source URL. With v1 weights all 1.0, this reduces to "most recent" — predictable. Operator gains URL-routing control by tuning weights post-launch without code change.

### Fallback Path (Single Article)
- **D-03:** **Same prompt template, 1-article input.** When Phase 5 returns `fallback_article_id` (no cluster), the synthesizer pulls that single Article and feeds it to the SAME prompt (3-5 article slot just contains 1 entry). The system prompt is invariant; the user prompt naturally degrades to a single-source headline summary instead of cross-source synthesis. URL = the fallback article's URL. No special-case prompt branching.

### Weighted Char-Count Library
- **D-04:** **Use `twitter-text-parser` Python library** for weighted char counting. Add to pyproject (`twitter-text-parser>=3,<4` or whichever current major). Eliminates entire class of edge-case bugs (CJK weight=2, emoji ZWJ sequences, t.co URL replacement). Helper `tech_news_synth.synth.charcount.weighted_len(text: str) -> int` wraps the library so we control the surface area.

### Char Budget
- **D-05:** **Fixed `HASHTAG_BUDGET_CHARS = 30`.** Computed budget for synthesis body = `280 (X limit) - 23 (t.co URL) - 30 (hashtag reservation) - 2 (separator spaces) = 225 chars`. The synthesizer aims for ≤ 225 weighted chars in body. Hashtag budget covers 1-2 short hashtags comfortably (typical `#IA #Apple` ≈ 9 chars; ceiling case `#Cybersecurity #Programming` ≈ 27 chars). Constants live in `src/tech_news_synth/synth/budget.py` for transparency.

### Re-Prompt + Truncation Loop
- **D-06:** **Up to 3 LLM attempts (1 initial + 2 retries) then last-resort truncation per SYNTH-04.**
  Pseudocode:
  ```
  for attempt in 1..3:
      text = anthropic_call(prompt[+ retry-shorten suffix on attempt 2-3])
      if weighted_len(text) <= 225: return text
      retry_count += 1
  # all 3 attempts over budget → truncate at last whitespace before budget, append "…"
  truncated = _word_boundary_truncate(text, 224) + "…"
  return truncated
  ```
  Retry prompt suffix (attempts 2-3): `"O texto anterior tinha {actual_len} caracteres (limite: {budget}). Reescreva mais conciso, mantendo o sentido principal e os nomes próprios, em no máximo {budget} caracteres."`
  Log per call: `attempts: int`, `final_method: "completed" | "truncated"`, plus token + cost. SYNTH-04 success criterion: human spot-check of 10 fixture synthesized posts → every one ≤ 280 weighted chars after final formatting (`<text> <url> <hashtag(s)>`).

### Prompt Structure
- **D-07:** **System prompt + user prompt split.** System prompt (fixed across all calls): tone instructions ("você é um curador de notícias de tecnologia. Tom: jornalístico neutro, PT-BR. NÃO use emojis. NÃO use exclamações. NÃO use hashtags no corpo do texto"), grounding guardrails ("use APENAS as informações dos artigos fornecidos. NÃO invente datas, nomes, citações, métricas. Mantenha nomes próprios intactos no idioma original."), char budget ("o texto deve ter no máximo {N} caracteres"). User prompt (per call): the 3-5 articles formatted as `Fonte: {source_name} | Título: {title} | Resumo: {summary[:500]}`. Synthesis instruction at the end: "Sintetize em 1-2 frases o ângulo principal coberto por essas fontes, em português, dentro do limite de caracteres."

### Posts Row Ownership
- **D-08:** **Phase 6 writes the `posts` row** with `status='pending'`, `synthesized_text`, `hashtags TEXT[]`, `source_url`, `cost_usd`, `cluster_id` (or NULL on fallback), `cycle_id`, `created_at`. Phase 7 later UPDATEs the row with `tweet_id` + `posted_at` (success) or `status='failed'` + `error_detail`. Per PUBLISH-02: row exists BEFORE the X API call.
- **D-09:** **`posts.theme_centroid` is written by Phase 6.** Phase 6 has access to the cluster centroid via Phase 5's `SelectionResult` (need to extend SelectionResult or re-derive — see Claude's Discretion). Centroid stored as `np.asarray(centroid, dtype=np.float32).tobytes()`. On fallback, `theme_centroid = NULL` (no cluster centroid exists).
- **D-10:** **`posts.synthesized_text` stores the FINAL formatted text** including URL + hashtags (the literal string that would be tweeted). `posts.error_detail` stores the synthesis-attempt log (JSONB-serializable list of `{attempt, length, text_preview}` dicts) when truncation was used — operator can later inspect why the LLM didn't comply.

### Hashtag Allowlist (Decision Pending — to be addressed in Plan)
- **D-11:** **Hashtag allowlist storage and selection logic NOT discussed in this round.** Defer to Claude's Discretion within plan. Recommended approach: separate `config/hashtags.yaml` with topic→tags mapping (e.g., `ai: [#IA, #ML]`, `apple: [#Apple, #iOS]`, `security: [#Cybersecurity, #InfoSec]`) bind-mounted same as `sources.yaml`. Hashtag selector is a deterministic Python function: extract top TF-IDF terms from cluster centroid (already in `clusters.centroid_terms` JSONB from Phase 5) → match against allowlist topic keys (substring + slug match) → return up to 2 hashtags. The LLM does NOT pick hashtags. Defaults if no match: `[#tech]` single-tag fallback.

### DRY_RUN Behavior
- **D-12:** **Under DRY_RUN=1, Phase 6 STILL calls Anthropic** (real cost ≈ $0.000038 per call) AND writes the `posts` row with `status='dry_run'` and the full `synthesized_text`. Rationale: synthesis quality is the part most likely to need iteration; dry-run posts give the operator real material to inspect before re-enabling publish. Phase 7 sees `status='dry_run'` and skips the X API call (PUBLISH-06).

### Settings Additions
- **D-13:** **4 new Settings fields** (with validators):
  - `synthesis_max_tokens: int = Field(default=150, ge=50, le=500)` — Anthropic max_tokens
  - `synthesis_char_budget: int = Field(default=225, ge=100, le=280)` — body char ceiling per D-05
  - `synthesis_max_retries: int = Field(default=2, ge=0, le=5)` — re-prompt retry count per D-06
  - `hashtag_budget_chars: int = Field(default=30, ge=0, le=50)` — D-05 reservation
  - Pricing constants for cost calculation imported from a constants module (mirrors Phase 3 `smoke_anthropic.py` constants); NOT a Settings field (constants change with Anthropic pricing, not operator choice).

### Claude's Discretion
- Where centroid float32 array travels from Phase 5 to Phase 6 — extend `SelectionResult` with optional `winner_centroid: bytes | None` field, OR re-fetch `clusters.centroid_terms` and re-derive (lossy). Recommend extending SelectionResult (the centroid is already computed in `run_clustering`).
- Hashtag allowlist file format (yaml schema, JSON, Python dict) — recommend `config/hashtags.yaml` with pydantic schema for validation at boot (same fail-fast pattern as `sources.yaml`).
- Hashtag matching algorithm — recommend simple slug-substring intersection between `centroid_terms` keys and `hashtags.yaml` topic keys; tiebreak by topic-key recency in the file (deterministic).
- Where the synthesis module lives — recommend `src/tech_news_synth/synth/{__init__,prompt,client,budget,truncate,hashtags,charcount,orchestrator}.py` (mirrors Phase 4/5 layout).
- Cost constants module — `src/tech_news_synth/synth/pricing.py` with `HAIKU_INPUT_USD_PER_MTOK = 1.00`, `HAIKU_OUTPUT_USD_PER_MTOK = 5.00` + `# last verified 2026-04-13` comment (matches Phase 3 source).
- Whether to bind structlog `phase="synth"` for log scoping — recommend yes (matches Phase 4 `phase="ingest"` and Phase 5 `phase="cluster"`).
- Anthropic SDK client lifecycle — recommend ONE client per cycle (passed into `run_synthesis`) similar to `httpx.Client` per cycle in Phase 4. Cheap to instantiate but consistent pattern wins.
- run_log.counts additions for synthesis (Phase 6 extends Phase 5's schema): `synth_attempts: int`, `synth_truncated: bool`, `synth_input_tokens: int`, `synth_output_tokens: int`, `synth_cost_usd: float`, `post_id: int | None` (the row Phase 6 wrote).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project context
- `.planning/PROJECT.md` — PT-BR tone, Haiku 4.5 rationale, cost envelope
- `.planning/REQUIREMENTS.md` §SYNTH-01..SYNTH-07
- `.planning/ROADMAP.md` §"Phase 6: Synthesis"
- `.planning/intel/x-api-baseline.md` — Phase 3 Haiku pricing + GO/NO-GO ($0.000038/call observed)
- `.planning/phases/02-storage-layer/02-CONTEXT.md` (D-07 BYTEA centroid)
- `.planning/phases/02-storage-layer/02-02-SUMMARY.md` (posts repo interface)
- `.planning/phases/05-cluster-rank/05-CONTEXT.md` (D-14 SelectionResult shape)
- `.planning/phases/05-cluster-rank/05-02-SUMMARY.md` (run_clustering interface)
- `CLAUDE.md`

### Research outputs
- `.planning/research/STACK.md` — anthropic 0.79 pinned
- `.planning/research/FEATURES.md` — synthesis volume budget
- `.planning/research/PITFALLS.md` — never trust LLM to count chars (validate in Python)

### External specs
- Anthropic Python SDK — https://github.com/anthropics/anthropic-sdk-python
- Anthropic messages.create API — https://docs.claude.com/en/api/messages
- Claude model pricing — https://platform.claude.com/docs/en/about-claude/pricing
- twitter-text-parser PyPI — https://pypi.org/project/twitter-text-parser/
- X tweet character counting — https://developer.x.com/en/docs/counting-characters

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (Phases 1-5)
- `tech_news_synth.config.Settings.anthropic_api_key` (SecretStr) — already loaded.
- `tech_news_synth.db.posts.insert_post(...)` (Phase 2) — already supports all needed fields. Phase 6 wraps it.
- `tech_news_synth.db.articles.get_article_by_id(...)` — verify exists or add (likely needs the helper to fetch fallback article + cluster member articles).
- `tech_news_synth.cluster.models.SelectionResult` — Phase 5 output. May need extension for centroid bytes.
- `scripts/smoke_anthropic.py` (Phase 3) — proven Haiku 4.5 invocation pattern; copy the SDK call shape.
- `tech_news_synth.logging.get_logger().bind(phase="synth", cycle_id=...)` — structlog pattern.
- `pricing constants from Phase 3 smoke_anthropic.py` — promote to `synth/pricing.py`.

### Established Patterns
- Pure-function modules; one orchestrator per phase ties them together.
- pydantic v2 at schema boundaries (PromptInput, SynthesisResult).
- structlog `phase=<X>` binding for log scoping.
- UTC everywhere; deterministic ordering of inputs.
- Settings extended with phase-specific fields (validators); `.env.example` updated.
- Run `tests/unit/test_<module>.py` per pure module + `tests/integration/test_<flow>.py` for DB-touching logic.
- DRY_RUN inherited from contextvars; phase modules check `settings.dry_run` for behavior branching where relevant.

### Integration Points
- `src/tech_news_synth/scheduler.py::run_cycle` — add `synthesis = run_synthesis(session, cycle_id, selection, settings, anthropic_client)` between `run_clustering` and `finish_cycle`. Merge `synthesis.counts_patch` into `counts`.
- `src/tech_news_synth/__main__.py` — instantiate `anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())` once at boot OR per cycle (recommend per-cycle for memory hygiene + consistency with httpx pattern).
- `src/tech_news_synth/cluster/models.py` — extend `SelectionResult` with `winner_centroid: bytes | None` (numpy float32 tobytes) and `winner_source_url: str | None` for symmetry with fallback case (or compute URL inside Phase 6).
- New `config/hashtags.yaml` bind-mounted at `/app/config/hashtags.yaml` (same mechanism as Phase 1 D-03 + Phase 4 sources.yaml).
- No DB schema changes — all writes to existing `posts` table.
- New deps: `twitter-text-parser`. `anthropic` already pinned.

</code_context>

<specifics>
## Specific Ideas

- Synthesis prompt example (system):
  ```
  Você é um curador de notícias de tecnologia para a conta @ByteRelevant no X.
  Tom: jornalístico, neutro, em português brasileiro.
  Restrições:
  - Use APENAS as informações dos artigos fornecidos.
  - NÃO invente datas, nomes, citações ou métricas.
  - Mantenha nomes próprios intactos (no idioma original).
  - NÃO use emojis nem hashtags no corpo do texto.
  - O texto final deve ter no máximo {budget} caracteres.
  ```
- User prompt example:
  ```
  Artigos:
  [1] Fonte: techcrunch | Título: Apple unveils new M5 chip | Resumo: Apple announced...
  [2] Fonte: verge | Título: Inside Apple's M5 launch | Resumo: ...
  [3] Fonte: ars_technica | Título: M5 benchmarks reveal... | Resumo: ...

  Sintetize em 1-2 frases o ângulo principal coberto por essas fontes, em português, dentro do limite de {budget} caracteres.
  ```
- Hashtag allowlist starter file (`config/hashtags.yaml`):
  ```yaml
  topics:
    ai: ["#IA", "#ML"]
    apple: ["#Apple"]
    google: ["#Google"]
    microsoft: ["#Microsoft"]
    security: ["#Cybersecurity", "#InfoSec"]
    chips: ["#Semicondutores"]
    open_source: ["#OpenSource"]
    cloud: ["#Cloud"]
    web: ["#Web"]
    mobile: ["#Mobile"]
  default: ["#tech"]
  ```
- Final post format example:
  `"Apple anuncia o chip M5 com ganhos de até 30% em desempenho de IA. https://t.co/abc123 #Apple #IA"`

</specifics>

<deferred>
## Deferred Ideas

- **A/B prompt experiments** — flag-gated prompt variants for quality testing. v2 concern.
- **Multi-language synthesis** — PT-only per CLAUDE.md scope.
- **Image generation** (DALL-E / Imagen / etc.) — explicitly out of scope.
- **Personality variants** (more casual, more formal) — single neutral tone for v1.
- **Cost-driven model fallback** (Haiku → Sonnet on retry-fail) — single model for v1; revisit if quality empirically poor.
- **Hashtag auto-learning from engagement** — no engagement signal in v1.
- **Sentence-level char budget** — single budget for whole post; sentence-level optimization is over-engineering.
- **Streaming completions** — no streaming benefit for ≤150 token responses.

</deferred>

---

*Phase: 06-synthesis*
*Context gathered: 2026-04-14 via /gsd-discuss-phase*
