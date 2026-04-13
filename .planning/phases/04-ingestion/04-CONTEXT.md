# Phase 4: Ingestion - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver a robust fetch + normalize layer that produces a normalized `ArticleRow` stream and upserts it via `tech_news_synth.db.articles.upsert_batch` (Phase 2). Scope includes: `sources.yaml` loader + pydantic discriminated-union schema; new `source_state` table (Alembic migration) for per-source ETag/Last-Modified/consecutive_failures/disabled_at; three per-type fetchers (RSS, HN Firebase, Reddit JSON); a single shared sync `httpx.Client` per cycle; per-source failure isolation + auto-disable at 20 consecutive failures; article age cutoff + max-per-fetch caps; conditional GET; `ArticleRow` pydantic model; integration into `run_cycle()`. Out of scope: clustering + ranking (Phase 5), synthesis (Phase 6), publish (Phase 7), `source-health` CLI re-enable UX (Phase 8).

</domain>

<decisions>
## Implementation Decisions

### Source Config & State Storage
- **D-01:** **`sources.yaml` is a flat list with `type` discriminator.** Top-level shape:
  ```yaml
  max_articles_per_fetch: 30        # global default; per-source override allowed
  max_article_age_hours: 24         # global; no per-source override in v1
  sources:
    - name: techcrunch
      type: rss
      url: https://techcrunch.com/feed/
      timeout_sec: 20
    - name: verge
      type: rss
      url: https://www.theverge.com/rss/index.xml
      timeout_sec: 20
    - name: ars_technica
      type: rss
      url: https://feeds.arstechnica.com/arstechnica/index
      timeout_sec: 20
    - name: hacker_news
      type: hn_firebase
      url: https://hacker-news.firebaseio.com/v0
      timeout_sec: 15
      max_articles_per_fetch: 30     # override optional
    - name: reddit_technology
      type: reddit_json
      url: https://www.reddit.com/r/technology/.json
      timeout_sec: 15
  ```
  `name` is unique per source (also used as `source_state.name` PK and as `articles.source`).

- **D-02:** **Pydantic v2 discriminated union validates at boot.** `Source = Annotated[Union[RssSource, HnFirebaseSource, RedditJsonSource], Field(discriminator="type")]`. A top-level `SourcesConfig` holds `max_articles_per_fetch: int = 30`, `max_article_age_hours: int = 24`, `sources: list[Source]`. Load-and-validate happens in a `load_sources_config(path: Path) -> SourcesConfig` helper. On `ValidationError`, print the error to stderr and raise — container exits non-zero (matches Phase 1 fail-fast pattern).

- **D-03:** **YAML parser = `pyyaml` (`yaml.safe_load`)** — add `pyyaml>=6,<7` to pyproject. `ruamel.yaml` was considered but round-trip formatting isn't needed; only reads. `safe_load` is mandatory for untrusted yaml (though bind-mounted operator config is implicitly trusted, habit matters).

- **D-04:** **New `source_state` table added via Phase 4 Alembic migration.** Columns:
  - `name TEXT PRIMARY KEY` (matches `sources.yaml` entries; also matches `articles.source`)
  - `etag TEXT NULL`
  - `last_modified TEXT NULL` (HTTP header format, stored verbatim)
  - `consecutive_failures INT NOT NULL DEFAULT 0`
  - `disabled_at TIMESTAMPTZ NULL`
  - `last_fetched_at TIMESTAMPTZ NULL`
  - `last_status TEXT NULL` (last `"ok" | "skipped_304" | "skipped_disabled" | "error:<kind>"`)
  - Row upserted-on-first-sight per source_name. Migration file named `<rev>_add_source_state.py`.

### Fetcher Architecture
- **D-05:** **Per-type fetcher modules + registry dispatch.** Layout:
  ```
  src/tech_news_synth/ingest/
    __init__.py
    fetchers/
      __init__.py          # exposes FETCHERS registry dict
      rss.py               # def fetch(source, client, state) -> Iterable[ArticleRow]
      hn_firebase.py       # same signature
      reddit_json.py       # same signature
    normalize.py           # canonicalize_url reuse + HTML strip via bs4/lxml
    orchestrator.py        # run_ingest(session, config) — the function scheduler.run_cycle calls
  ```
  `FETCHERS: dict[str, Callable] = {"rss": rss.fetch, "hn_firebase": hn_firebase.fetch, "reddit_json": reddit_json.fetch}`. Adding a new type = new file + one registry line + pydantic model variant.

- **D-06:** **One shared sync `httpx.Client` per cycle.** Built once at cycle start with `httpx.Client(headers={"User-Agent": "ByteRelevant/0.1 (+https://x.com/ByteRelevant)"}, follow_redirects=True, http2=True)`. Per-request timeouts come from `source.timeout_sec`. `tenacity.retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=16))` decorates the inner HTTP call; retries on `httpx.HTTPError` + 5xx status codes only (4xx is not retried). Client is closed in a `try/finally`.

- **D-07:** **`ArticleRow` is a pydantic v2 model** in `src/tech_news_synth/ingest/models.py`:
  ```python
  class ArticleRow(BaseModel):
      source: str                  # source.name from yaml
      url: str                     # raw URL from feed
      canonical_url: str           # via tech_news_synth.db.hashing.canonicalize_url
      article_hash: str            # via tech_news_synth.db.hashing.article_hash
      title: str
      summary: str                 # HTML-stripped via bs4 + lxml
      published_at: datetime       # UTC-aware; fallback to fetched_at if source omits
      fetched_at: datetime         # UTC-aware; set by orchestrator
  ```
  Fetchers emit `ArticleRow` objects; `upsert_batch` accepts `Iterable[ArticleRow]` and converts to dicts via `row.model_dump()`.

### Volume Controls
- **D-08:** **`max_articles_per_fetch: 30`** (global; per-source override allowed). After fetching, each fetcher sorts by `published_at DESC` and slices `[:max_articles_per_fetch]`.
- **D-09:** **`max_article_age_hours: 24`** (global; no per-source override). Articles with `published_at < now(UTC) - 24h` are filtered out by the fetcher before emission. Skipped articles increment a `skipped_age` counter in the per-source log line but do NOT fail the source.
- **D-10:** **`timeout_sec` per source (default 20, HN+Reddit default 15)**. Applied as `httpx.Timeout(source.timeout_sec, connect=5.0)`. tenacity wraps the whole request call (connection + read).

### Failure Isolation & Auto-Disable
- **D-11:** **Per-source failure isolation is total:** each fetcher call is wrapped in `try/except Exception` inside the orchestrator. Any exception → log `event=source_error source=<name> error=<type>: <message>` + increment `source_state.consecutive_failures` + set `last_status="error:<kind>"` → continue to next source. Cycle proceeds to DB upsert with successful sources. On success, reset `consecutive_failures=0`, set `last_status="ok"`.
- **D-12:** **Auto-disable fires at CYCLE START, not mid-cycle.** At the top of `run_ingest`, for each source: if `source_state.consecutive_failures >= MAX_CONSECUTIVE_FAILURES` (default 20, env-configurable) OR `disabled_at IS NOT NULL` → skip with `event=source_skipped_disabled source=<name> consecutive_failures=<N>`. The 20th failure within a cycle still completes that fetch attempt; the NEXT cycle skips it. Clean boundary.
- **D-13:** **Re-enable is Phase 8 (OPS-04 `source-health` CLI).** Phase 4 writes `disabled_at` on cross-threshold and reads it at cycle start — that's all. Interim re-enable is a documented manual DB UPDATE in the runbook: `UPDATE source_state SET disabled_at=NULL, consecutive_failures=0 WHERE name='techcrunch';`. On operator re-enable (manual or CLI), `consecutive_failures` resets to 0 and `disabled_at` clears.

### Conditional GET (INGEST-04)
- **D-14:** **Only RSS fetchers use ETag/Last-Modified.** HN Firebase and Reddit JSON don't reliably honor conditional GET (Firebase is a JSON REST endpoint; Reddit requires auth for stable caching). For RSS: send `If-None-Match: <source_state.etag>` and `If-Modified-Since: <source_state.last_modified>` when present. On `304 Not Modified`, log `event=source_not_modified source=<name>`, set `last_status="skipped_304"`, do NOT increment failure counter, continue. On `200`, update `source_state.etag` + `source_state.last_modified` from response headers.

### Claude's Discretion
- Exact retry status-code list for tenacity (429, 500, 502, 503, 504 recommended).
- HN Firebase fetch strategy: fetch `topstories.json` (IDs list) then `item/{id}.json` for top-N items — parallel? Serial with small `httpx.Client` reuse is fine at N=30. Claude picks.
- Reddit JSON endpoint: recent Reddit changes may require OAuth; the planner should verify and fall back gracefully with a clear log message if so (feature-flag disable Reddit in v1 if auth becomes mandatory).
- HTML stripping: `bs4 + lxml` with `soup.get_text(" ", strip=True)`. Summary truncation limit (recommend 1000 chars to fit reasonably in `articles.summary` TEXT column without bloating DB).
- `run_log.counts` JSONB shape for Phase 4: recommend `{"articles_fetched": {"techcrunch": 8, "verge": 12, ...}, "articles_upserted": 20, "sources_ok": 4, "sources_error": 1, "sources_skipped_disabled": 0}`.
- Integration-test postgres requirement for fetcher tests that write `source_state` + `articles` — reuse Phase 2 `db_session` fixture.
- Test doubles for HTTP: `respx` (already pinned) for httpx mocking at the fetcher unit-test level.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project context
- `.planning/PROJECT.md` — source list, User-Agent, cost context
- `.planning/REQUIREMENTS.md` §INGEST-01..INGEST-07
- `.planning/ROADMAP.md` §"Phase 4: Ingestion"
- `.planning/phases/01-foundations/01-CONTEXT.md` (D-03 `./config` bind-mount; D-09 ULID cycle_id)
- `.planning/phases/02-storage-layer/02-CONTEXT.md` (D-06 SHA256 article_hash; D-04 bigserial PKs)
- `.planning/phases/02-storage-layer/02-02-SUMMARY.md` (`articles.upsert_batch` interface)
- `.planning/phases/03-validation-gate/03-VERIFICATION.md` (GO decision)
- `CLAUDE.md`

### Research outputs
- `.planning/research/STACK.md` — httpx, feedparser, tenacity, bs4 pinned versions
- `.planning/research/ARCHITECTURE.md` — source-orchestration flow sketch
- `.planning/research/PITFALLS.md` — feedparser HTML stripping; timezone pitfalls

### External specs
- httpx `Client` docs — https://www.python-httpx.org/api/#client
- tenacity docs — https://tenacity.readthedocs.io/
- feedparser — https://feedparser.readthedocs.io/
- HN Firebase API — https://github.com/HackerNews/API
- Reddit JSON endpoints — https://www.reddit.com/dev/api/ (section on `.json` suffix)
- RFC 7232 (Conditional Requests) — ETag / Last-Modified semantics

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tech_news_synth.db.hashing.canonicalize_url(url)` + `article_hash(url)` — exactly matches INGEST-06 requirements; do NOT reimplement.
- `tech_news_synth.db.articles.upsert_batch(session, rows)` — accepts iterable + uses `ON CONFLICT DO NOTHING`. Pass `ArticleRow.model_dump()` dicts.
- `tech_news_synth.db.session.SessionLocal` — single context-managed session per cycle, already wired by Phase 2.
- `tech_news_synth.db.run_log.start_cycle/finish_cycle` — pass the per-source counts dict as `counts` to `finish_cycle`.
- `tech_news_synth.config.Settings` — may need one new field: `max_consecutive_failures: int = 20` and potentially `sources_config_path: str = "/app/config/sources.yaml"`.
- `tech_news_synth.logging.get_logger()` — structlog; inherit contextvars `cycle_id` + `dry_run`.
- `tech_news_synth.ids.new_cycle_id` — not directly used; cycles already have IDs from scheduler.

### Established Patterns
- Pure modules + functions, no classes unless warranted (fetchers are module-level functions).
- pydantic v2 models for schema boundaries (settings, yaml config, ArticleRow).
- structlog `bind` for per-source log scoping: `log.bind(source=src.name).info("source_fetch_start")`.
- UTC everywhere: `datetime.now(timezone.utc)`; never naive datetimes.
- `tenacity` for external calls; no retry logic inside business code.
- Integration tests gated by `pytest.mark.integration` against compose postgres; unit tests with `respx` for HTTP mocking.

### Integration Points
- **`src/tech_news_synth/scheduler.py::run_cycle`** gains a call to `tech_news_synth.ingest.orchestrator.run_ingest(session, config, http_client)` inside the try block (between `start_cycle` and `finish_cycle`). Ingestion results feed into `run_log.counts`.
- **`src/tech_news_synth/__main__.py`** gains a call to `load_sources_config(settings.sources_config_path)` after `run_migrations()` and before `build_scheduler()`. Validates yaml at boot (INGEST-01 fail-fast).
- **Alembic migration** — new file `alembic/versions/<rev>_add_source_state.py` creating `source_state` table.
- **`compose.yaml`** — bind-mount already exists (`./config:/app/config:ro` from Phase 1). No compose changes.
- **`config/sources.yaml`** — new file committed to repo with the 5 v1 sources. Replaces the Phase 1 `sources.yaml.example` stub.
- **`pyproject.toml`** — add `pyyaml>=6,<7`. `tenacity`, `httpx`, `feedparser`, `beautifulsoup4`, `lxml`, `respx` all already pinned.

</code_context>

<specifics>
## Specific Ideas

- The 5 v1 source names (underscore-normalized for use as PKs + log fields): `techcrunch`, `verge`, `ars_technica`, `hacker_news`, `reddit_technology`.
- RSS summary stripping: `BeautifulSoup(html, "lxml").get_text(" ", strip=True)[:1000]`.
- HN item fetch: `GET {base}/item/{id}.json` returns `{title, url, time (unix), ...}`. `published_at = datetime.fromtimestamp(time, tz=UTC)`. For text-only posts with no url, `url = f"https://news.ycombinator.com/item?id={id}"`.
- Reddit JSON listing: `data.children[].data.{title, url, created_utc, selftext}`. Skip posts where `data.stickied=true` or `data.is_self=true && not data.url.startswith("http")`.
- Per-source log at cycle end: one line each for `source_fetch_start` + `source_fetch_end` with `count`, `elapsed_ms`, `status`.
- `source_state` rows are pre-seeded on first boot via `load_sources_config` — for each yaml entry, `INSERT ... ON CONFLICT DO NOTHING` into `source_state` with defaults.

</specifics>

<deferred>
## Deferred Ideas

- **Async httpx.** Parallel fetches save 2s/cycle at 2h cadence — not worth the complexity in v1.
- **OAuth for Reddit.** If the public `.json` endpoint stops working, feature-flag Reddit to disabled + revisit in v2 with OAuth script app credentials.
- **Per-source metric histograms.** `source_fetch_duration_ms` histograms are a Phase 8 hardening concern.
- **Adaptive timeouts.** Per-source p99 tracking with auto-adjust — premature optimization.
- **Non-RSS feed types.** Mastodon, JSON Feed, Atom extensions, RSS 1.0 edge cases — add on demand.
- **CLI `source-health --enable`** — Phase 8 (OPS-04).
- **Partial-content fetches.** HTTP Range headers on feeds — not worth the bandwidth savings at 2h cadence.
- **Duplicate suppression at fetch time (pre-DB).** Rely on DB UNIQUE + ON CONFLICT; cheaper than in-memory dedup.
- **Cross-source duplicate URL detection.** canonicalize_url handles trivial dedup; semantic near-duplicates are Phase 5's clustering problem.

</deferred>

---

*Phase: 04-ingestion*
*Context gathered: 2026-04-13 via /gsd-discuss-phase*
