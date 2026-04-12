# Pitfalls Research

**Domain:** Automated tech-news curation agent (Python + RSS/HN/Reddit → TF-IDF clustering → Claude Haiku synthesis → X auto-posting)
**Researched:** 2026-04-12
**Confidence:** HIGH for X API / Docker / Postgres / feedparser specifics; MEDIUM for TF-IDF short-text and LLM length control (best-effort mitigations, no silver bullet).

---

## Critical Pitfalls

### Pitfall 1: Assuming the legacy X Free Tier (500 posts/month) is still available

**What goes wrong:**
The project states "tier Free — ~500 posts/mês". On **February 6, 2026**, X replaced the tiered model with **pay-per-use as the default** for new developers. The old Free tier is no longer available to new accounts. Legacy Free users were migrated to pay-as-you-go with a one-time $10 voucher. Building the entire business case on "12 free posts/day" is a ticking bomb: you either already don't qualify, or your credits will burn out.

**Why it happens:**
Project was planned using pre-2026 blog posts / Medium tutorials about Twitter's free tier. The official pricing page is the only source of truth, and it changed recently.

**How to avoid:**
- Verify **today** whether @ByteRelevant's developer account has legacy access or is on pay-per-use. Log into developer portal and confirm plan + quota.
- If pay-per-use: compute cost per post (currently ~$0.0005–0.005 per write depending on credit bundle) × 12 posts/day × 30 = expected monthly bill. Budget explicitly or reduce cadence.
- If you qualify for a legacy tier, document the exact daily/monthly write quota you see in the dashboard — **do not trust 500/month or 17/day numbers from blog posts.**
- Implement a **hard budget guard**: a daily counter in Postgres (`posts_today`) that refuses to call `create_tweet` if the quota will be exceeded. Fail loud (log ERROR), don't silently drop.
- Implement a **cost ceiling kill switch** via env var (`MAX_POSTS_PER_DAY=12`, `MAX_POSTS_PER_MONTH=360`).

**Warning signs:**
- 429 errors with `x-rate-limit-remaining: 0` earlier than expected.
- 403 responses on `create_tweet` with "client not enrolled" messages.
- Unexpected charges on the card linked to the X developer account.

**Phase to address:** **Phase 0 / Discovery** (before writing any code). Blocker — rethink economics if pay-per-use is the only option.

---

### Pitfall 2: tweepy `create_tweet` 403 Forbidden due to wrong OAuth flow or app permissions

**What goes wrong:**
Developer creates an X app with **Read-only** permissions, generates access tokens, then gets persistent `Forbidden 403` when calling `client.create_tweet(...)`. Or they use **OAuth 2.0 app-only Bearer Token** (which cannot post on a user's behalf) instead of **OAuth 1.0a User Context**.

**Why it happens:**
- Twitter's dev portal defaults to Read-only.
- Two auth flows (Bearer vs. User Context) look interchangeable in the SDK but aren't — only User Context can write.
- Crucially: **if you change app permissions from Read to Read+Write AFTER generating tokens, the old tokens remain Read-only.** Tokens must be regenerated.

**How to avoid:**
- In dev portal: set app to **Read and Write** *before* generating access tokens.
- Use `tweepy.Client(consumer_key=..., consumer_secret=..., access_token=..., access_token_secret=...)` (4 secrets = OAuth 1.0a User Context). If you only have a bearer token, you cannot post.
- If permissions were changed: **regenerate** access token + secret, update `.env`.
- Add a startup smoke test: on container boot, call `client.get_me()` once and log the authenticated handle — confirms token validity without burning a post quota.

**Warning signs:**
- `Forbidden: 403 Forbidden` on every `create_tweet` call, same error for all content.
- `get_me()` works but `create_tweet()` fails → permissions issue.
- Nothing works → token/secret mismatch.

**Phase to address:** **Phase covering X integration** (likely an early "publishing" phase). Write a `test_auth.py` script that runs OAuth handshake + `get_me()` before any synthesis code is plumbed in.

---

### Pitfall 3: LLM output exceeds 280 chars — silent truncation by X or request failure

**What goes wrong:**
Claude Haiku is told "máximo 280 caracteres" and returns 291. Tweepy sends it, X rejects with 400. Or worse: code naively slices `text[:280]`, cutting mid-word, breaking a URL, or truncating a hashtag, producing an embarrassing post.

**Why it happens:**
LLMs cannot reliably count characters/tokens in their own output. Research shows naive "write max N chars" prompts achieve <30% compliance; countdown/explicit counting prompts reach ~95% but never 100%. Also, the **t.co URL wrapper counts as 23 chars regardless of actual URL length**, and emoji/acentos (PT-BR) can count as 2 UTF-16 code units toward Twitter's "weighted" character count.

**How to avoid:**
- Budget: assume link = 23 chars + 1 space + 2 hashtags (~20 chars) = ~44 chars reserved. Tell Claude the **text budget is ~230 chars**, not 280.
- **Never trust the LLM output blindly.** Compute length using Twitter's `twitter-text` rules (there's `twitter-text-python` pkg) or a conservative proxy: `len(text.encode('utf-16-le')) // 2`.
- Retry loop: if output > budget, re-prompt with "Reduza para ≤N caracteres mantendo o sentido." Max 2 retries, then fall back to sentence-level truncation ending on period.
- Never hard-slice `[:280]` — always truncate at the last whitespace before the budget, append "…" if truncated (counts 1 char).
- Log every (input chars, output chars, retries) to Postgres for tuning.

**Warning signs:**
- `400 Bad Request` with `"Your Tweet text is too long"`.
- Posts ending mid-word in production.
- High retry rate (>10%) indicates prompt is too permissive.

**Phase to address:** **Phase covering synthesis** (LLM integration). Build a `TweetFormatter` unit with tests for PT-BR accented text, emoji, URL accounting.

---

### Pitfall 4: TF-IDF cosine similarity fails on short headlines (false negatives and false positives)

**What goes wrong:**
Two headlines about the same story get low cosine similarity because they share almost no vocabulary:
- "Apple anuncia novo iPhone 17 com chip A19"
- "Cupertino revela smartphone com processador de próxima geração"
→ similarity ≈ 0.1, clustering separates them. Meanwhile two **unrelated** headlines sharing stopword-ish tokens ("Google lança ferramenta de IA" + "Amazon lança ferramenta de busca") may cluster together.

**Why it happens:**
TF-IDF on ~8–12 word headlines produces extremely sparse vectors; synonyms are invisible. Also Portuguese morphology (plurals, verb conjugations) inflates vocabulary without semantic benefit.

**How to avoid:**
- **Preprocess aggressively**: lowercase, strip punctuation, remove Portuguese stopwords (`nltk.corpus.stopwords('portuguese')` + custom: "anuncia", "revela", "lança"), apply stemming (`nltk.stem.RSLPStemmer` for PT) or lemmatization.
- Use **character n-grams** (`TfidfVectorizer(analyzer='char_wb', ngram_range=(3,5))`) — robust to morphology and typos, often better than word n-grams for short multilingual text.
- **Augment headline with article summary/description** from the RSS `<description>` field before vectorizing — doubles or triples the signal.
- Set similarity threshold empirically (start 0.35 for char n-grams), not theoretically. Build a labeled eval set of 50 pairs from real feeds and tune.
- Plan to **upgrade to sentence embeddings** (e.g., `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, runs CPU, free) when TF-IDF plateaus. Architect the clusterer behind an interface so it's swappable.

**Warning signs:**
- Manually obvious "same story" clusters don't merge in logs.
- Cluster sizes are consistently 1–2 (nothing cluster-worthy means TF-IDF too strict) or everything merges into one giant cluster (threshold too loose).
- "Tema vencedor" feels random to a human operator.

**Phase to address:** **Phase covering clustering**. Build a labeled fixture of ~50 real-world headline pairs (same-story vs. different-story) and treat clustering quality as a measurable metric, not vibes.

---

### Pitfall 5: 48h anti-repetition window defeated by naive hashing

**What goes wrong:**
Same story re-surfaces 30h later from a different source with slightly different wording; the theme-hash is computed from the normalized cluster title, but `"Apple lança iPhone 17"` and `"iPhone 17 é lançado pela Apple"` produce different MD5 hashes → duplicate post.

**Why it happens:**
Any lexical hash (MD5, SHA1 of normalized text) is **not semantic** — synonyms, word order, conjugations break it.

**How to avoid:**
- Do **not** hash the title. Instead, store a **centroid vector** (or top-K TF-IDF terms as a set) per published post, and compare new candidate clusters against the last 48h of centroids using cosine similarity with threshold ≥ 0.5. If any match, skip or re-rank.
- Persist: `post_id, published_at TIMESTAMPTZ, theme_terms TEXT[], centroid BYTEA (pickled)`.
- Use PostgreSQL's `pg_trgm` extension + GIN index on a "normalized canonical terms" TEXT column as a cheap fallback (trigram similarity on a sorted stopword-free string).
- Index `published_at` with `BRIN` or `btree` for fast 48h window queries.

**Warning signs:**
- Same story posted twice within 48h (verify manually from post history).
- Slightly rephrased headlines pass the dedup check.

**Phase to address:** **Phase covering dedup/persistence**. Write regression tests: given a seeded history, a rephrased same-story cluster must be rejected.

---

### Pitfall 6: Postgres `TIMESTAMPTZ` + container TZ misalignment → 48h window is actually 45h or 51h

**What goes wrong:**
App container runs UTC (Docker default). Postgres container runs UTC. But developer sets `TZ=America/Sao_Paulo` on one and not the other. `NOW() - INTERVAL '48 hours'` in Postgres uses session timezone to *display* but compares UTC. Meanwhile Python's `datetime.now()` (naive) returns local or UTC depending on container TZ. Mixing `datetime.now()` with `NOW()` in queries produces off-by-3h errors every comparison.

**Why it happens:**
- Docker containers default to UTC.
- `feedparser` returns `published_parsed` as a **naive struct_time normalized to UTC** — losing timezone info even though it parsed it.
- PostgreSQL `TIMESTAMPTZ` stores UTC internally but presents in session TZ; `TIMESTAMP WITHOUT TIME ZONE` silently accepts whatever you pass.
- psycopg3 returns `TIMESTAMPTZ` as timezone-aware Python `datetime` with UTC — but only if the column is TZ-aware. If you used `TIMESTAMP`, you get naive datetimes.

**How to avoid:**
- **Force everything UTC**. Do not set `TZ=` anywhere. Store all times as `TIMESTAMPTZ`. In Python, always use `datetime.now(timezone.utc)` — never `datetime.now()` or `datetime.utcnow()` (deprecated + naive).
- Convert `feedparser` `published_parsed` struct_time: `datetime(*p[:6], tzinfo=timezone.utc)`.
- Set `postgresql.conf` (or env `PGTZ`): `timezone = 'UTC'`.
- Display/log conversion to São Paulo time is a **presentation concern**, not a storage concern.

**Warning signs:**
- Posts appearing twice at the window boundary.
- Logs showing timestamps that don't match cron schedule.
- `48h window` queries returning unexpected row counts depending on time of day.

**Phase to address:** **Phase covering persistence / scheduling**. Establish "UTC everywhere, convert on display only" as an architecture rule in ARCHITECTURE.md.

---

### Pitfall 7: Cron inside container doesn't see environment variables from `.env`

**What goes wrong:**
Docker Compose injects env vars into PID 1 (your app). But if you run **system cron** (`/usr/sbin/cron`) inside the container, cron spawns children with a **minimal environment** that does not inherit your compose env vars. Your scheduled job starts, reads `os.environ['ANTHROPIC_API_KEY']`, gets `KeyError`, and silently dies because cron swallows stdout.

**Why it happens:**
System cron was designed for multi-user Unix, not containers. It deliberately scrubs the environment. `docker compose` injection happens at container start — cron's spawned children don't see it.

**How to avoid:**
- **Don't use system cron inside the container.** Use a **Python-native scheduler**: `APScheduler` (`BlockingScheduler` with `CronTrigger` or `IntervalTrigger`). PID 1 is your Python process; env vars are inherited.
- Set `APScheduler` timezone explicitly: `scheduler = BlockingScheduler(timezone=pytz.UTC)`.
- Alternative if you *must* use cron: write env to `/etc/environment` in the entrypoint (`printenv > /etc/environment`) before `cron -f`. Fragile — avoid.
- Beware DST: APScheduler's `CronTrigger` may double-fire or skip during DST transitions on non-UTC timezones. UTC avoids this entirely.

**Warning signs:**
- Container running, but no posts appearing.
- No errors in `docker logs` because cron writes to `/var/spool/mail/root` or `/dev/null`.
- Manually running the script works; scheduled runs don't.

**Phase to address:** **Phase covering scheduler/runtime**. Decide APScheduler vs. cron early; write it into STACK.md.

---

### Pitfall 8: `.env` leaked to git or baked into Docker image

**What goes wrong:**
Developer commits `.env` by accident (forgot `.gitignore`), or `COPY . /app` in Dockerfile copies `.env` into the image layer. Now secrets are in git history forever and in every image layer pushed anywhere.

**Why it happens:**
- `.gitignore` added after first commit → `.env` already tracked.
- `COPY . /app` is a greedy pattern; `.dockerignore` forgotten.
- Public repo with the oversight → hours until bots find the X/Anthropic keys.

**How to avoid:**
- Commit `.env.example` with dummy values. Commit `.gitignore` **first**, with `.env` + `.env.*` (except `.env.example`).
- Commit `.dockerignore` with `.env`, `.env.*`, `.git/`, `__pycache__/`, `.venv/`.
- Use `env_file: .env` in docker-compose.yml — this reads at runtime from host, never bakes into the image.
- Run `git ls-files | grep env` before every push. Add a pre-commit hook with `gitleaks` or `detect-secrets`.
- Rotate keys immediately if any leak occurred — assume compromised.

**Warning signs:**
- `git log -- .env` returns any commits.
- `docker history <image>` shows `.env`-sized layers in `COPY .` step.
- Unusual Anthropic billing or X posts you didn't author.

**Phase to address:** **Phase 1 / Setup**. Make this the first commit: `.gitignore`, `.dockerignore`, `.env.example`, `.env` (local, ignored).

---

### Pitfall 9: Reddit JSON endpoint returns 429 or 403 without a proper User-Agent

**What goes wrong:**
`requests.get("https://www.reddit.com/r/technology/.json")` with default `python-requests/2.x` User-Agent returns **429 Too Many Requests** immediately or shadow-bans the IP for hours. Reddit rate-limits **per User-Agent**; the default UA is heavily contested shared pool.

**Why it happens:**
Reddit explicitly requires unique UAs and throttles generic ones. This is documented but easy to forget.

**How to avoid:**
- Set a descriptive UA: `"ByteRelevant/0.1 (tech-news-synth; contact: your@email)"`.
- Respect `Retry-After` header on 429.
- Implement exponential backoff with jitter. Cap at 3 retries, then skip this source for this cycle and log WARN.
- Consider switching to **PRAW** with a script-type OAuth app (free, 100 QPM) for higher, more stable limits — but adds a secret to manage.
- Cache responses for at least 10 minutes (not worth re-fetching r/technology hot list more often).

**Warning signs:**
- All Reddit fetches returning 429 in logs.
- Reddit returning HTML login walls instead of JSON.
- Reddit absent from most clusters.

**Phase to address:** **Phase covering ingestion**. Every source client must have: custom UA, timeout, retry+backoff, per-source failure isolation.

---

### Pitfall 10: feedparser bozo exceptions and one bad feed killing the pipeline

**What goes wrong:**
TechCrunch has a malformed CDATA section one afternoon. `feedparser.parse(url)` sets `bozo=1` but returns a partial `FeedParserDict`. Developer ignored `bozo`, downstream code accesses `entries[0].published_parsed` → `AttributeError`, unhandled exception, the entire 2-hour cycle fails. No post that cycle.

**Why it happens:**
- `feedparser` is "tolerant" by design but signals problems via `bozo` that's easy to ignore.
- Feeds sometimes omit `published`, `guid`, or `title`.
- `published_parsed` is `None` if date was unparseable or missing.
- Network timeouts cause feedparser to return empty results without raising.

**How to avoid:**
- **Isolate each source**: one try/except per source, never let one feed's failure abort the cycle.
- Check presence defensively: `entry.get('title', '').strip()`, `entry.get('published_parsed') or entry.get('updated_parsed')`.
- If `bozo=1`, inspect `bozo_exception` — `CharacterEncodingOverride` is usually safe to ignore; `NonXMLContentType` or `xml.sax.SAXParseException` means skip that feed this cycle.
- Use `feedparser.parse(url, request_headers={'User-Agent': ..., 'If-Modified-Since': last_seen})` — saves bandwidth and reduces 304 churn.
- De-dup entries within a cycle by `entry.id or entry.link` — same article can appear via multiple feeds.
- Timeout the HTTP fetch: wrap in `requests.get(url, timeout=10)` then pass bytes to `feedparser.parse(...)`. `feedparser`'s built-in fetch has no timeout.

**Warning signs:**
- Cycles producing 0 clusters.
- Exception stack traces in logs referring to `None.lower()` or `NoneType has no attribute`.
- Same article appearing in multiple clusters in the same cycle.

**Phase to address:** **Phase covering ingestion**. Ingestion layer should return `list[Article]` with strong contracts; malformed entries dropped with WARN logs, never propagated.

---

### Pitfall 11: Anthropic API cost/latency spike from unbounded prompt size

**What goes wrong:**
Pipeline passes 3–5 articles to Claude for synthesis, but "3 articles" means feeding the full article bodies (10–30k chars each). Input tokens balloon to 50k+, cost per post ~$0.05 instead of $0.001, latency > 10s, occasional rate-limit errors.

**Why it happens:**
Developer assumes the model needs the full text. For a 280-char synthesis, it needs headlines + first paragraph max.

**How to avoid:**
- Feed **only**: cluster headlines (deduped), source names, and the RSS `<description>` (typically 1–2 sentences). Never full article bodies.
- Cap total input: `max 3 articles × 500 chars summary ≈ 1500 input chars + prompt ≈ 2500 tokens`.
- Use `anthropic.Anthropic().messages.count_tokens(...)` before the call if you're unsure.
- Set a hard `max_tokens=150` on the response (280 chars ≈ 70–100 tokens for PT).
- Monitor cost per post: log (input_tokens, output_tokens, cost_estimate) to Postgres.
- Model choice: pin an explicit Haiku version string at build time, do NOT use an alias that can change under you.

**Warning signs:**
- Anthropic bill higher than expected (>$1/day for 12 posts = red flag).
- Synthesis latency > 5s.
- 429 / rate-limit errors from Anthropic.

**Phase to address:** **Phase covering synthesis**. Establish input budget as a code invariant with a test.

---

### Pitfall 12: LLM hallucinates facts / invents quotes / mistranslates brand names

**What goes wrong:**
Claude Haiku, given three headlines about OpenAI's GPT-5, writes "Sam Altman confirmou lançamento para dezembro" — which no source said. Or translates "Vision Pro" to "Pro de Visão". Published post is factually wrong or embarrassing, tied to @ByteRelevant's reputation.

**Why it happens:**
LLMs "fill gaps" when prompts don't explicitly constrain to source material. Smaller models (Haiku) hallucinate more than Sonnet/Opus. Portuguese training data is thinner; brand/product names may be literally translated.

**How to avoid:**
- **Grounded prompt**: "Você DEVE usar APENAS informações presentes nas manchetes e resumos fornecidos. NÃO invente datas, nomes, números ou citações. Se uma informação não estiver nos dados, omita-a."
- Preserve proper nouns: "Mantenha nomes de empresas, produtos e pessoas EXATAMENTE como aparecem nas fontes (ex: 'Vision Pro' não se traduz)."
- Post-generation validation: extract named entities from input (regex on capitalized words / a NER lib), verify entities in output are a subset. Flag mismatches.
- Start tone conservative: "jornalístico neutro, factual, sem adjetivos superlativos, sem especulação."
- Human-in-the-loop for v0.1: log synthesis to a **staging queue** for 1 week before auto-publishing; review samples, tune prompt.
- Add a kill-switch: env var `DRY_RUN=true` → synthesize and log but don't post.

**Warning signs:**
- Dates/numbers in posts not in source material.
- Post-publication corrections needed.
- Brand names mangled.

**Phase to address:** **Phase covering synthesis + quality**. First release should run in `DRY_RUN` mode for N cycles with manual review before enabling `create_tweet`.

---

### Pitfall 13: Legal/ToS — RSS is public but republishing summaries has limits

**What goes wrong:**
Summarizing and tweeting content from TechCrunch/Verge/Ars without attribution → DMCA or account suspension. Or: Hacker News comments are user-generated content with their own copyright; quoting them in a tweet without attribution is risky.

**Why it happens:**
"Public RSS" ≠ "public domain". Fair use / "direito de citação" in Brazil allows brief excerpts with attribution for commentary; rewriting full summaries without source link is thinner ice.

**How to avoid:**
- **Always include source link** in the tweet — the project already plans this. Link is both attribution AND drives traffic to original (reduces complaint likelihood).
- Name the source if space allows: "via TechCrunch".
- Don't quote article prose verbatim beyond ~10 words; always paraphrase through the LLM synthesis.
- Reddit: linking to a Reddit thread is fine; quoting a specific user's comment without attribution is not.
- Don't post content from sources that have explicit anti-AI terms without reviewing. TechCrunch / Verge / Ars are fine for this pattern; add new sources deliberately.

**Warning signs:**
- Takedown requests from a publisher.
- X account strikes for ToS violations.
- Publisher contacting @ByteRelevant.

**Phase to address:** **Phase covering source management / publishing**. Add "attribution required" as an invariant in the tweet composer.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Hard-code source URLs in Python constants | Ship faster | Adding/removing sources requires code change + redeploy (violates stated requirement) | Never — requirement says sources configurable |
| `datetime.now()` naive everywhere | No tz wrestling at first | Off-by-hours bugs in 48h window, DST chaos | Never — always use `datetime.now(timezone.utc)` |
| Skip retry logic for HTTP calls | Simpler code | One flaky source → whole cycle fails | Never for ingestion; acceptable for Anthropic (fail the cycle, log, try next cycle) |
| Store clusters as JSON blobs in one Postgres column | Flexible schema | Can't query, can't index, can't evolve | Early prototype only; normalize before Phase 2 |
| Log to stdout without JSON structure | Easy to read | Can't grep fields, can't ship to aggregators later | Never — project requires structured JSON logs |
| Single global `anthropic.Anthropic()` client with no retries | Works | Transient 5xx / rate-limit kills cycle | Never — wrap with tenacity or SDK's built-in retry |
| No DRY_RUN mode | Simpler | Can't test in prod-like without burning API quota and embarrassing posts | Never skip — must have from day one |
| Use `COPY . .` in Dockerfile | Easy | Leaks secrets, bloats image, invalidates cache on every file change | Only with a strict `.dockerignore` |
| Use `latest` tag for postgres image | "Always current" | Breaks on major version bumps (pg15→pg16 data incompatibility) | Never — pin `postgres:16.x-alpine` |
| Inline SQL strings in Python | No ORM learning curve | SQL injection risk, no schema migrations | Early prototype with parameterized queries; add Alembic before Phase 2 |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| X API (tweepy) | Using OAuth 2.0 Bearer token for posting | OAuth 1.0a User Context (4 secrets: consumer key/secret + access token/secret) |
| X API (tweepy) | Assuming 500 posts/month free tier still exists | Verify current plan in dev portal; budget for pay-per-use |
| X API character count | `len(text) == 280` | Twitter's weighted count differs for emoji/accents; `t.co` links always 23 chars. Use `twitter-text` library or reserve 50 char buffer |
| Anthropic SDK | Using model alias like `claude-haiku` | Pin explicit version string — aliases can change |
| Anthropic SDK | Not setting `max_tokens` | Always set; for tweet synthesis 150 is plenty |
| feedparser | Trusting `entry.published_parsed` is always present | Fallback chain: `published_parsed` → `updated_parsed` → skip entry |
| feedparser | Using feedparser's built-in HTTP fetcher | Fetch with `requests` (has timeout), pass bytes to `feedparser.parse()` |
| Reddit JSON | Default `python-requests` User-Agent | Unique descriptive UA string; respect `Retry-After` |
| Hacker News API | Fetching `topstories.json` then N=500 full item fetches | Fetch top 30 only; parallelize with small concurrency (5) |
| Postgres in Docker | `postgres:latest` image | Pin minor version; major bumps require `pg_upgrade` |
| Postgres in Docker | Mounting host dir as data volume on Linux with wrong UID | Use named volume (`pgdata:`) — Docker manages permissions |
| psycopg3 | Mixing `psycopg2` and `psycopg3` docs | They have different APIs; verify imports (`import psycopg` vs `import psycopg2`) |
| Docker Compose | Using `version: "3.x"` at top (deprecated in Compose v2) | Omit version key entirely (Compose v2) |
| Docker Compose | `depends_on` without `condition: service_healthy` | App starts before Postgres is ready → crash loop. Use healthcheck + `condition: service_healthy` |
| APScheduler | `BlockingScheduler` without `timezone=` | Uses system TZ (UTC in container); set `timezone=pytz.UTC` explicitly |
| APScheduler | Catching exceptions inside the job function only | Also register `EVENT_JOB_ERROR` listener so silent failures are logged |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Re-fetching all RSS feeds every cycle with no conditional GET | Bandwidth waste, rate-limit risk, slow cycles | Send `If-Modified-Since` / `ETag` headers; respect 304 | 5+ sources × 12 cycles/day |
| TF-IDF vectorizer re-fit every cycle on full 6h window | Cycle latency grows with catalog size | Fit once, reuse; or fit per-cycle on just that cycle's articles (current cycle doesn't need to cluster against history, dedup does) | 100+ articles per cycle |
| Storing full article text in Postgres with no limits | DB bloats, backups slow | Truncate descriptions to 2000 chars before insert; never store full article body | After weeks of operation |
| No index on `(published_at, theme_hash)` in posts table | 48h lookup becomes sequential scan | Create compound index from day 1 | ~1000 rows (fast), but design debt forever |
| Synchronous source fetching | 5 sources × 3s timeout = 15s best case, much worse with retries | `concurrent.futures.ThreadPoolExecutor` with 5 workers for I/O-bound fetching | Adding the 6th source |
| Logging full article bodies in JSON logs | Log volume grows 10MB/day | Log IDs and lengths, not content | 1 week of operation |
| No connection pooling on Postgres | Each function call opens new connection | `psycopg_pool.ConnectionPool` with min=1, max=3 | Any sustained operation |
| Calling Anthropic without caching when cluster unchanged | Re-synthesizing same content if cycle retried | Cache synthesis by cluster centroid hash with 2h TTL | Restart loops / retries |

---

## Summary for Roadmap Phase Mapping

| Phase Theme | Top Pitfalls to Address |
|-------------|-------------------------|
| Phase 0 (Discovery/Feasibility) | #1 X Free Tier reality check — **blocker**; #2 OAuth flow verification |
| Phase 1 (Setup/Scaffolding) | #8 secrets hygiene; pinned image versions; `.dockerignore`; UTC-everywhere rule |
| Phase 2 (Ingestion) | #9 Reddit UA; #10 feedparser bozo isolation; source-level failure containment |
| Phase 3 (Clustering/Dedup) | #4 TF-IDF short-text handling (char n-grams, PT stemming); #5 semantic dedup (not hash) |
| Phase 4 (Synthesis) | #3 char-limit enforcement; #11 input budget; #12 hallucination guardrails + DRY_RUN |
| Phase 5 (Publishing) | #2 OAuth 1.0a + permissions regen; #1 quota guard; #13 attribution invariant |
| Phase 6 (Scheduler/Runtime) | #7 APScheduler (not system cron); #6 TIMESTAMPTZ / UTC storage |
| Phase 7 (Hardening/Observability) | Performance traps table; structured JSON logs; kill-switches |

**Highest-risk, do-first:** #1 (X Free Tier reality check). If the economics don't work, nothing else matters.

---

## Sources

- [X API Pricing in 2026: Every Tier Explained](https://www.wearefounders.uk/the-x-api-price-hike-a-blow-to-indie-hackers/) — HIGH confidence: Feb 2026 pricing changes
- [Postproxy: X (Twitter) API Pricing in 2026](https://postproxy.dev/blog/x-api-pricing-2026/) — MEDIUM confidence, corroborating pricing
- [X API Pricing: Pay-Per-Use Credits + Legacy Tiers](https://jesusiniesta.es/blog/x-api-pricing-tiers-what-you-actually-get) — MEDIUM confidence
- [Official X API docs - rate limits](https://docs.x.com/x-api/fundamentals/rate-limits) — HIGH confidence (authoritative)
- [tweepy 403 on create_tweet GitHub issue #1796](https://github.com/tweepy/tweepy/issues/1796) — HIGH confidence (real-user reports)
- [X Developer Community: tweepy create_tweet 403](https://devcommunity.x.com/t/tweepy-create-tweet-403/171721) — HIGH confidence
- [feedparser: Bozo Detection docs](https://feedparser.readthedocs.io/en/stable/bozo.html) — HIGH confidence (official)
- [feedparser: Character Encoding docs](https://feedparser.readthedocs.io/en/latest/character-encoding.html) — HIGH confidence
- [feedparser issue #212: published_parsed is naive](https://github.com/kurtmckee/feedparser/issues/212) — HIGH confidence
- [APScheduler issue #346: CronTrigger timezone default](https://github.com/agronholm/apscheduler/issues/346) — HIGH confidence
- [APScheduler CronTrigger docs + DST behavior](https://apscheduler.readthedocs.io/en/latest/modules/triggers/cron.html) — HIGH confidence
- [How to Handle Timezones in Docker Containers (How-To Geek)](https://www.howtogeek.com/devops/how-to-handle-timezones-in-docker-containers/) — MEDIUM confidence
- [Reddit API Rate Limits 2026](https://painonsocial.com/blog/reddit-api-rate-limits-guide) — MEDIUM confidence
- [Simon Willison: Scraping Reddit via JSON API](https://til.simonwillison.net/reddit/scraping-reddit-json) — HIGH confidence (practitioner)
- [psycopg timezone timestamptz discussion #56](https://github.com/psycopg/psycopg/discussions/56) — HIGH confidence
- [docker-library/postgres timezone issues #641](https://github.com/docker-library/postgres/issues/641) — HIGH confidence
- [arxiv 2508.13805: Prompt-Based Exact Length-Controlled Generation](https://arxiv.org/html/2508.13805v1) — MEDIUM confidence
- [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) — HIGH confidence (official)
- [Claude API rate limits](https://platform.claude.com/docs/en/api/rate-limits) — HIGH confidence (official)
