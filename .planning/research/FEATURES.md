# Feature Research

**Domain:** Automated tech-news curation & single-account X (Twitter) auto-posting agent (headless, ~12 posts/day, VPS)
**Researched:** 2026-04-12
**Confidence:** HIGH (stack + constraints well-scoped in PROJECT.md; ecosystem patterns verified via multiple sources)

## Feature Landscape

### Table Stakes (Operator Expects These — Missing = Silent Failure, Spam, or Lost Posts)

Non-negotiable for an unattended posting agent. Missing any one produces outages, duplicate posts, rate-limit bans, or undetectable drift.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Configurable source list (add/remove/edit feeds)** | Feeds die, rename, or 404 constantly; hard-coding forces a code deploy per source change | LOW | YAML/TOML config loaded at boot. Each entry: `{name, url, kind=rss\|hn\|reddit, enabled, weight}` |
| **Per-source fetcher with retries + timeout** | Flaky RSS endpoints are the norm; one bad feed must not kill the whole cycle | LOW | `requests` with `urllib3.Retry`: 3 retries, exp backoff, 10s connect / 20s read. Per-source try/except isolation |
| **Conditional GET (ETag + If-Modified-Since)** | Polite fetching; publishers rate-limit/ban aggressive pollers. 304 responses save bandwidth and reduce ban risk | LOW | Store `etag` + `last_modified` per source in DB. Send `If-None-Match` / `If-Modified-Since` next fetch. 304 → "no new items". `feedparser` supports this natively via `etag=` / `modified=` kwargs |
| **User-Agent identifying the bot + contact** | Anonymous scrapers are blocked first; named UAs with contact URL are tolerated | LOW | `tech-news-synth/0.1 (+https://x.com/ByteRelevant)` |
| **Dedup by canonical URL + title hash** | Same story republished across feeds; same feed re-emits items with tweaked timestamps | LOW | Normalize URL (strip `utm_*`, fragments, trailing slash) → sha256. Also hash normalized title. Skip if either hit in last 72h |
| **Title-similarity clustering with threshold** | Core value: pick "tema com maior cobertura" requires grouping near-duplicates across sources | MEDIUM | TF-IDF (sklearn) + cosine; threshold ~0.55–0.7 (tune). Agglomerative clustering with `distance_threshold` avoids pre-specifying K |
| **6h rolling window on clustering input** | Old news inflates cluster sizes and makes stale topics "win" | LOW | `WHERE fetched_at > now() - interval '6 hours'` before vectorizing |
| **Deterministic winner selection rule** | Non-determinism at cron-time = unreproducible output, untestable | LOW | Primary: distinct-source count in cluster. Tiebreak: recency of most recent item, then source-weight sum |
| **48h anti-repetition window (semantic)** | Posting the same topic twice in 48h = brand damage; pure URL hash is not enough (different articles, same story) | MEDIUM | Store `topic_hash` per post (hash of cluster top-terms or Haiku topic slug). Query `posted WHERE topic_hash = ? AND posted_at > now()-48h` |
| **Fallback when no strong cluster** | PROJECT.md requires 12 posts/day cadence on slow news days | LOW | Pick highest-weighted single item from last 6h not violating 48h window. Log `selection_mode=fallback` |
| **280-char budget enforcement (URL + hashtags accounted)** | X rejects >280; tweepy raises 403. Silent truncation by LLM destroys meaning | MEDIUM | Pre-compute budget: `280 − 23 (t.co) − sum(len(hashtag)+1)`. Hard constraint in Haiku prompt. Post-validate; if over, re-prompt tighter (max 2 retries) then hard-truncate on word boundary |
| **X rate-limit awareness (429 handling)** | Free tier ~500 posts/month / ~17/day in 2026; 429 without backoff = temp ban. `x-rate-limit-reset` header must be respected | MEDIUM | Catch `tweepy.TooManyRequests`, read `x-rate-limit-reset`, sleep until reset + jitter. Never retry faster than `Retry-After` |
| **Daily post-count guard (local counter)** | Don't trust X to return 429 before quota exhausted; self-throttle at 12/day | LOW | `SELECT count(*) FROM posts WHERE posted_at::date = current_date`. If ≥12, skip cycle with `reason=daily_cap` |
| **Idempotent posting (intent row before call)** | Network flake between `tweepy.create_tweet` and DB insert → double-post on next cron | MEDIUM | Generate `post_intent_id` (uuid), insert `status=pending` row first, update to `posted` with tweet_id on success. On restart, resolve pending by querying X or skipping within dedup window |
| **Structured JSON logs with cycle_id** | Unattended agent → logs are the only observability surface | LOW | One `cycle_id` (uuid) per run, propagated across all log lines. Fields: `event, cycle_id, source, cluster_id, topic_hash, chars, decision, error`. `structlog` or stdlib + JSON formatter |
| **Persistent history (fetched items + posts)** | Required for 48h window, debugging, and "why did it pick X?" audits | LOW | Postgres tables: `items`, `clusters`, `posts`. Retain ≥30 days |
| **Graceful failure per cycle (never crash the cron)** | One cycle failing must not stop the next | LOW | Top-level `try/except` around cycle, log traceback, exit 0 |
| **.env-based secrets with validation at boot** | Missing X keys = silent no-post for days if not caught early | LOW | `pydantic-settings` BaseSettings; fail-fast if `X_API_KEY`, `ANTHROPIC_API_KEY` missing |
| **Timezone-correct scheduling (UTC internal)** | `datetime.now()` in container UTC vs source timestamps in various TZs causes window errors | LOW | Always `datetime.now(tz=UTC)` internally; parse feed timestamps with `dateutil.parser` |

### Differentiators (Raise Post Quality or Operator Confidence)

Features beyond table stakes that improve output quality or give the operator real leverage. Align with Core Value ("um post por ciclo que destaca o tema com mais cobertura e o ângulo único de cada fonte").

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Dry-run mode (`DRY_RUN=1`)** | Operator can test full pipeline (fetch → cluster → synth) without burning X posts or daily quota | LOW | CLI flag + env var. Runs everything, logs intended tweet, skips `create_tweet`. Essential for dev loop on free tier |
| **Cluster-selection audit trail ("why this topic won")** | Operator can inspect bad picks and tune thresholds; black-box cluster → debuggable decision | MEDIUM | Persist per-cycle: all cluster IDs, member items, sizes, score breakdown, why runner-ups lost. Expose via `psql` or `--explain-last` CLI |
| **Replay past cycles from DB** | Reproduce bad post offline with saved items to test prompt/threshold changes | MEDIUM | `replay --cycle-id=X`: re-runs clustering + synthesis on stored items. No network fetch, no posting. High value for prompt iteration |
| **Per-source weight / trust score** | TechCrunch headline ≠ random Reddit post; weight lets operator nudge signal quality without banning sources | LOW | `weight: float` in source config, multiplied into cluster scoring |
| **Hashtag strategy (capped + curated)** | Hashtag spam hurts engagement; 1–2 focused hashtags outperform 5+. Needs deterministic control | MEDIUM | Curated tag map per topic domain (AI, crypto, gadgets, policy). Haiku picks from allowed set, max 2, char-budget-aware. Deny-list for banned/cringe tags |
| **URL canonicalization + t.co length awareness** | Strip tracking params before posting (cleaner tweets, better dedup). Reserve exactly 23 chars regardless of URL length | LOW | `w3lib.url.canonicalize_url` or manual. Never call external shorteners (t.co handles it) |
| **Kill switch (single file or DB flag)** | Breaking news / wrong post / brand incident → stop in seconds without redeploy | LOW | Check `/app/state/PAUSED` file OR `config.paused = true` row at cycle start. Document in runbook |
| **Manual post override (`post-now <topic>`)** | Operator wants to seed a topic manually (agent missed big news). Keeps the loop honest | MEDIUM | CLI: takes item IDs or free-text topic + URL, runs through synth + 280-char validation + 48h check. Respects daily cap |
| **Per-cycle metrics emitted to logs** | Trend visibility (cluster sizes, source health, char-budget failures) without a metrics stack | LOW | One `cycle_summary` log line per run: `{cycle_id, items_fetched, items_new, clusters, winner_size, topic_hash, chars_used, posted, fallback, duration_ms}`. Later: grep → CSV → chart |
| **Source-health tracking (consecutive failures)** | Dead feeds silently shrink input; 10 days of 404 from TechCrunch = blind spot | LOW | Track `consecutive_failures` per source; log warning at ≥3, auto-disable at ≥20 |
| **Language/locale filter on input** | PT output quality improves when input is predominantly EN-tech; mixed-language items pollute clusters | MEDIUM | `langdetect` on title; keep only EN + PT. Lower priority if sources are already EN-first |
| **Explicit temperature=0 + prompt version in logs** | Reproducibility: same input → same output; prompt changes are traceable | LOW | Log `prompt_version`, Haiku `temperature`, `model_id` per call |
| **Cost tracking (Haiku tokens per cycle)** | Unbounded token use = surprise bill; ~12 cycles/day × cluster summaries is small but worth visibility | LOW | Anthropic SDK returns `usage`; sum input+output tokens, log in `cycle_summary` |

### Anti-Features (Deliberately NOT Building — PROJECT.md Out-of-Scope + Domain Traps)

Features that seem valuable but create complexity, brand risk, or scope drift disproportionate to a single-account v1 agent.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Multi-account posting** | "Could post to LinkedIn/Mastodon/second X handle" | 3× auth surface, 3× rate-limit logic, 3× content-tone tuning; platform norms differ. Out-of-scope per PROJECT.md | Ship single-account v1; fork/extend only after validation |
| **Threads (multi-tweet posts)** | "More context per topic" | Thread state machine, mid-thread failure recovery, partial-thread deletion, deeper 280-char juggling. PROJECT.md: "um post por ciclo" | Single post with sharpest angle; link to canonical source for depth |
| **Web UI / dashboard** | "Nicer than grep logs" | Auth, CSRF, sessions, hosting, TLS, maintenance. Massive v1 scope inflation. Out-of-scope per PROJECT.md | `psql` + `jq` on JSON logs + small CLI (`replay`, `explain-last`, `post-now`, `pause`) |
| **Active alerts (Discord/Telegram/Sentry/email)** | "Know when something breaks" | Yet another integration + credentials + delivery retry. Out-of-scope per PROJECT.md | JSON logs + daily cron that `grep ERROR` and writes a status file. Operator checks on their cadence |
| **Real-time streaming fetch** | "Fresher news" | X streaming is paid-tier; 2h polling is sufficient because "coverage" needs time to accumulate across sources | 2h cron; shorter windows lose the clustering signal |
| **Paid or scraped sources** | "More diverse input" | Legal exposure, ToS violations, brittle CSS, CAPTCHAs. Out-of-scope per PROJECT.md | Stick to RSS + public JSON (HN, Reddit); add new public feeds as surfaced |
| **Automatic source discovery** | "Agent finds its own feeds" | Quality control nightmare, spam/SEO-feed ingestion, abuse risk | Operator curates source list; 5-line YAML edit |
| **LLM-powered dedup/clustering** | "Better than TF-IDF" | Cost per cycle × pairwise comparisons, non-deterministic, harder to debug, slower. TF-IDF is good enough at this scale | TF-IDF + cosine; revisit only if measured precision <70% on a labeled sample |
| **Auto-reply / engagement bot** | "Grow the account" | Classic path to account suspension (X anti-spam heuristics), brand risk, moderation burden | Posts only. Engagement is a human task |
| **Image/media generation** | "Tweets with images get more engagement" | Image-gen costs, copyright of derived images, media upload retry logic, failure modes multiply | Text + link only in v1 |
| **Sentiment / "hot take" tone** | "More engaging than neutral" | Brand risk (bot making wrong call on sensitive story). PROJECT.md: "tom jornalístico neutro" | Keep neutral; differentiation is coverage signal, not opinion |
| **Multi-language output** | "Reach EN audience too" | 2× prompt tuning, 2× 48h window per language, 2× brand voice. Out-of-scope per PROJECT.md | PT-BR only; one brand, one voice |
| **Retry-forever on X 5xx** | "Don't miss a post" | Retry storms during X outages, quota burn, duplicate risk | Bounded retries (3× with backoff); if still failing, log and skip. Next cycle is 2h away |

## Feature Dependencies

```
[Configurable source list]
    └──required-by──> [Per-source fetcher with retries]
                          └──required-by──> [Conditional GET (ETag)]
                                                └──enhances──> [Source-health tracking]

[Persistent history (items + posts)]
    └──required-by──> [Dedup by URL/title hash]
    └──required-by──> [48h anti-repetition window]
    └──required-by──> [Replay past cycles]
    └──required-by──> [Cluster-selection audit trail]
    └──required-by──> [Daily post-count guard]

[Title-similarity clustering]
    └──required-by──> [Winner selection rule]
                          └──required-by──> [Fallback when no strong cluster]
                                                └──required-by──> [Haiku synthesis]
                                                                      └──required-by──> [280-char budget enforcement]
                                                                                            └──required-by──> [Post to X]

[Dry-run mode]
    └──enhances──> [All posting features] (test without side effects)

[Structured JSON logs with cycle_id]
    └──required-by──> [Per-cycle metrics]
    └──required-by──> [Cluster-selection audit trail]
    └──required-by──> [Cost tracking]

[Idempotent posting (intent row)]
    └──required-by──> [X 429 retry path] (avoids double-post)
    └──required-by──> [Daily post-count guard] (counter matches reality)

[Kill switch]
    └──conflicts-with──> [Retry-forever semantics] (kill switch must win)

[Manual post override]
    └──requires──> [280-char validation], [48h anti-repetition], [Daily cap]
       (override must share guardrails or it becomes the spam vector)
```

### Dependency Notes

- **Persistence is the spine.** Nearly every differentiator (replay, audit, metrics) and every safety feature (dedup, daily cap, anti-repetition) reads from the same `items` + `clusters` + `posts` tables. Get schema right in Phase 1.
- **Idempotent posting precedes rate-limit handling.** If post+DB-write isn't atomic-ish, retries on 429 double-post. Intent-row pattern first, then retry logic.
- **Dry-run must exist before first real post.** Without it, every integration test costs a real tweet + daily-cap slot. Build it in the same phase as the X client wrapper.
- **Audit trail depends on clustering, not vice-versa.** Ship clustering first; add audit persistence in the next iteration if Phase 1 is heavy.

## MVP Definition

### Launch With (v1 — minimum to run unattended for 7 days without human intervention)

- [ ] Configurable source list (YAML) — swap feeds without redeploy
- [ ] Fetcher with retries + per-source isolation + User-Agent + conditional GET (ETag/Last-Modified)
- [ ] Persistent storage: `items`, `clusters`, `posts` in Postgres
- [ ] URL + title hash dedup (ingest-time)
- [ ] TF-IDF + cosine clustering over rolling 6h window
- [ ] Deterministic winner selection (distinct sources → recency → weight)
- [ ] Fallback picker when no cluster ≥ threshold (cadence ≥ quality on slow days)
- [ ] 48h anti-repetition via `topic_hash`
- [ ] Claude Haiku synthesis with hard 280-char budget (URL 23c + hashtags)
- [ ] Idempotent X posting via intent row + tweepy v2
- [ ] X 429 handling (respect `x-rate-limit-reset`)
- [ ] Local daily post-count guard (12/day)
- [ ] Structured JSON logs with `cycle_id` on every line
- [ ] Dry-run mode (`DRY_RUN=1`) — everything short of `create_tweet`
- [ ] Kill switch (file or DB flag checked at cycle start)
- [ ] Graceful per-cycle failure (no cron death, exit 0)
- [ ] `.env` secret loading with fail-fast validation at boot
- [ ] Docker Compose with app + Postgres, persistent volumes

### Add After Validation (v1.x — once v1 runs clean for 2–4 weeks)

- [ ] Cluster-selection audit trail — add when operator asks "why did it pick X?"
- [ ] Replay from DB (`replay --cycle-id=X`) — add when prompt tuning becomes routine
- [ ] Per-cycle metrics line (`cycle_summary`) — add when log grepping hurts
- [ ] Source-health tracking (auto-disable after N failures) — add when first source silently dies
- [ ] Manual post override CLI (`post-now`) — add when operator has missed a real story
- [ ] Curated hashtag map — add when default hashtags feel generic
- [ ] Cost tracking per cycle (Haiku tokens) — add when Anthropic bill enters awareness

### Future Consideration (v2+ — only after v1.x shows product-market fit)

- [ ] Language filter on input (langdetect) — defer unless non-EN/PT noise pollutes clusters
- [ ] Explainable clustering (top terms per cluster in DB) — defer unless debugging demands it
- [ ] Per-source dynamic weight tuning — defer; manual weights in YAML are enough
- [ ] Second account / cross-posting — explicit anti-feature for v1
- [ ] Threads — explicit anti-feature; requires full state machine

## Feature Prioritization Matrix

| Feature | User (Operator) Value | Implementation Cost | Priority |
|---------|-----------------------|---------------------|----------|
| Configurable source list (YAML) | HIGH | LOW | P1 |
| Fetcher with retries + conditional GET | HIGH | LOW | P1 |
| Persistent history (items/clusters/posts) | HIGH | LOW | P1 |
| URL + title hash dedup | HIGH | LOW | P1 |
| TF-IDF clustering + winner selection | HIGH | MEDIUM | P1 |
| Fallback picker | HIGH | LOW | P1 |
| 48h anti-repetition (topic_hash) | HIGH | MEDIUM | P1 |
| 280-char budget enforcement | HIGH | MEDIUM | P1 |
| Idempotent posting (intent row) | HIGH | MEDIUM | P1 |
| X 429 handling | HIGH | MEDIUM | P1 |
| Daily post-count guard | HIGH | LOW | P1 |
| Structured JSON logs + cycle_id | HIGH | LOW | P1 |
| Dry-run mode | HIGH | LOW | P1 |
| Kill switch | HIGH | LOW | P1 |
| Cluster-selection audit trail | MEDIUM | MEDIUM | P2 |
| Replay from DB | MEDIUM | MEDIUM | P2 |
| Per-cycle metrics line | MEDIUM | LOW | P2 |
| Source-health tracking | MEDIUM | LOW | P2 |
| Manual post override CLI | MEDIUM | MEDIUM | P2 |
| Curated hashtag map | MEDIUM | MEDIUM | P2 |
| Cost tracking (Haiku tokens) | LOW | LOW | P2 |
| Language filter (langdetect) | LOW | MEDIUM | P3 |
| Per-source dynamic weight tuning | LOW | HIGH | P3 |

**Priority key:**
- **P1:** Must have for v1 launch — missing causes silent failure, spam, rate-limit bans, or lost posts
- **P2:** Should have, add when operator pain signals the need (typically 2–6 weeks after v1)
- **P3:** Future; only if measurable quality problems emerge

## Competitor / Analog Feature Analysis

Direct competitors for "single-account automated tech-news X poster in PT" are thin; closest analogs are self-hosted aggregators and posting bots.

| Feature | Feedly (commercial aggregator) | typical `rss-to-twitter` OSS bots | Our Approach |
|---------|--------------------------------|-----------------------------------|--------------|
| Source management | Web UI, OPML import | Config file, 1 feed per post | YAML config, multi-feed with weights |
| Deduplication | Proprietary clustering at scale | URL-only, often none | URL + title hash + TF-IDF semantic cluster |
| "Why this item won" | Opaque AI ranking | First-in-first-out | Persisted cluster scoring audit trail |
| Post synthesis | N/A (aggregator) | Verbatim headline + link | Claude Haiku synthesis, neutral journalistic tone, PT |
| Anti-repetition | Per-user read state | None — reposts common | 48h semantic `topic_hash` window |
| Rate-limit handling | N/A | Usually naive (fail on 429) | Explicit `x-rate-limit-reset` respect + local daily cap |
| Observability | Commercial dashboard | `print()` to stdout | Structured JSON logs + `cycle_summary` metrics |
| Dry-run / replay | N/A | Rare | First-class `DRY_RUN` + DB-backed replay |

**Differentiation summary:** The combination of (a) semantic clustering as the selection criterion, (b) LLM synthesis with strict char budget, (c) 48h semantic anti-repetition, and (d) replayable/auditable decisions is uncommon in OSS RSS-to-X bots, which mostly republish headlines verbatim. Aligns with Core Value in PROJECT.md.

## Sources

- [Conditional GET for RSS Hackers (Fishbowl)](https://fishbowl.pastiche.org/2002/10/21/http_conditional_get_for_rss_hackers) — ETag/If-Modified-Since canonical guidance
- [Best practices for syndication feed caching (Ctrl blog)](https://www.ctrl.blog/entry/feed-caching.html) — modern RSS caching norms
- [X API Rate Limits (official docs)](https://docs.x.com/x-api/fundamentals/rate-limits) — 429 + `x-rate-limit-reset` behavior
- [X API v2 Free Tier specifics (devcommunity)](https://devcommunity.x.com/t/specifics-about-the-new-free-tier-rate-limits/229761) — 2026 free-tier post caps
- [Twitter/X API Pricing 2026 (xpoz.ai)](https://www.xpoz.ai/blog/guides/understanding-twitter-api-pricing-tiers-and-alternatives/) — current tier landscape
- [tweepy 429 handling discussions](https://github.com/tweepy/tweepy/discussions/1820) — community experience with retry/backoff
- [Clustering and summarization for news aggregation (Najkov, Medium)](https://medium.com/@danilo.najkov/using-clustering-and-summarization-algorithms-for-news-aggregation-eb16a891c479) — TF-IDF + agglomerative pattern for news
- [Google News System Design guide](https://www.systemdesignhandbook.com/guides/google-news-system-design/) — canonical aggregator feature set
- [Feedly engineering: clustering & deduplication](https://feedly.com/engineering/posts/reducing-clustering-latency) — production aggregator tradeoffs
- `PROJECT.md` (in-repo) — binding constraints: 12 posts/day, 48h window, PT neutral, Compose, VPS

---
*Feature research for: automated tech-news curation & X auto-posting agent (single-account, headless)*
*Researched: 2026-04-12*
