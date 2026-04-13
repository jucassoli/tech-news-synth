# Phase 4: Ingestion - Research

**Researched:** 2026-04-12
**Domain:** Multi-source HTTP fetch + parse + normalize + idempotent persist (RSS, HN Firebase, Reddit JSON) under per-source failure isolation
**Confidence:** HIGH (stack already pinned in Phase 1/2; only `pyyaml` is new; all patterns are well-established)

## Summary

Phase 4 wires **five public sources** into the existing `articles.upsert_batch` pipeline through three fetcher modules (RSS, HN Firebase, Reddit JSON) dispatched by a `type` discriminator in `sources.yaml`. The orchestrator owns: per-source `try/except` isolation, conditional-GET state persistence (RSS only), failure counter + auto-disable at 20 consecutive failures, and a single shared `httpx.Client` per cycle.

The key risks are **not technical novelty** — they are (1) reliable HTML stripping from polymorphic RSS payloads, (2) Reddit's increasingly hostile unauthenticated `.json` policy, and (3) pydantic v2 discriminated-union ergonomics on YAML load. All three have well-known mitigations documented below.

**Primary recommendation:** Build a thin, sequential orchestrator. Don't reach for asyncio (Phase 4 owns 5 sources × <30 items at 2h cadence — sequential httpx is ≤8s/cycle). Wrap every external call with `tenacity` retry on 5xx + httpx errors (NOT 4xx). Use pydantic v2 discriminated union for type-safe `sources.yaml` loading. Reuse Phase 2's `canonicalize_url` + `article_hash` verbatim — never re-implement.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01 — `sources.yaml` is a flat list with `type` discriminator.** Top-level shape: `max_articles_per_fetch`, `max_article_age_hours`, `sources: [{name, type, url, timeout_sec, ...}]`. `name` is unique per source (PK in `source_state`, also used as `articles.source`).

**D-02 — Pydantic v2 discriminated union validates at boot.** `Source = Annotated[Union[RssSource, HnFirebaseSource, RedditJsonSource], Field(discriminator="type")]`. Top-level `SourcesConfig` holds globals + `sources: list[Source]`. `load_sources_config(path: Path) -> SourcesConfig` helper. On `ValidationError`: print to stderr + raise → container exits non-zero (Phase 1 fail-fast).

**D-03 — YAML parser = `pyyaml` (`yaml.safe_load`)** — add `pyyaml>=6,<7` to pyproject. `safe_load` mandatory.

**D-04 — New `source_state` table via Phase 4 Alembic migration:** `name TEXT PK`, `etag TEXT NULL`, `last_modified TEXT NULL`, `consecutive_failures INT NOT NULL DEFAULT 0`, `disabled_at TIMESTAMPTZ NULL`, `last_fetched_at TIMESTAMPTZ NULL`, `last_status TEXT NULL`. Migration: `<rev>_add_source_state.py`.

**D-05 — Per-type fetcher modules + registry dispatch.** Layout: `src/tech_news_synth/ingest/{__init__,normalize,orchestrator,models}.py + fetchers/{__init__,rss,hn_firebase,reddit_json}.py`. `FETCHERS: dict[str, Callable] = {"rss": rss.fetch, ...}`.

**D-06 — One shared sync `httpx.Client` per cycle.** `httpx.Client(headers={"User-Agent": "ByteRelevant/0.1 (+https://x.com/ByteRelevant)"}, follow_redirects=True, http2=True)`. Per-request timeouts from `source.timeout_sec`. `tenacity.retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=16))` on `httpx.HTTPError` + 5xx only (not 4xx). Client closed in `try/finally`.

**D-07 — `ArticleRow` is a pydantic v2 model** in `ingest/models.py` with: `source, url, canonical_url, article_hash, title, summary, published_at, fetched_at`. Fetchers emit `ArticleRow`; `upsert_batch` accepts iterable + converts via `model_dump()`.

**D-08 — `max_articles_per_fetch: 30`** (global; per-source override allowed). Fetcher sorts by `published_at DESC` and slices.

**D-09 — `max_article_age_hours: 24`** (global; no per-source override). Filter before emission. `skipped_age` counter does NOT fail the source.

**D-10 — `timeout_sec` per source** (default 20 RSS, 15 HN/Reddit). Applied as `httpx.Timeout(source.timeout_sec, connect=5.0)`.

**D-11 — Total per-source failure isolation.** `try/except Exception` per fetcher → log + increment `consecutive_failures` + set `last_status="error:<kind>"` → continue. Reset to 0 on success.

**D-12 — Auto-disable fires at CYCLE START, not mid-cycle.** Top of `run_ingest`: if `consecutive_failures >= MAX_CONSECUTIVE_FAILURES` (default 20, env-configurable) OR `disabled_at IS NOT NULL` → skip + log. The 20th failure within a cycle still fires; NEXT cycle skips.

**D-13 — Re-enable is Phase 8 (OPS-04 `source-health` CLI).** Phase 4 only writes `disabled_at` and reads it at cycle start. Interim re-enable = manual SQL UPDATE in runbook.

**D-14 — Only RSS uses ETag/Last-Modified.** Send `If-None-Match` + `If-Modified-Since` when present. On 304: log + `last_status="skipped_304"` + do NOT increment failure counter. On 200: update `etag` + `last_modified` from response headers.

### Claude's Discretion
- Exact retry status-code list for tenacity (recommend: 429, 500, 502, 503, 504).
- HN Firebase fetch strategy (sequential at N=30 is fine — recommend it).
- Reddit JSON: verify endpoint still works unauthenticated (research below); fall back gracefully if blocked.
- HTML stripping with `bs4 + lxml` and 1000-char truncation.
- `run_log.counts` JSONB shape for Phase 4.
- Integration-test fixtures and respx-based unit-test strategy.

### Deferred Ideas (OUT OF SCOPE)
- Async httpx (parallel fetches save 2s/cycle — not worth complexity).
- OAuth for Reddit (only if `.json` becomes blocked).
- Per-source metric histograms (Phase 8).
- Adaptive timeouts.
- Non-RSS feed types (Mastodon, JSON Feed, etc.).
- CLI `source-health --enable` (Phase 8 OPS-04).
- HTTP Range partial-content fetches.
- In-memory dedup before DB upsert.
- Cross-source semantic dedup (Phase 5 clustering).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INGEST-01 | `sources.yaml` mounted; schema supports add/edit/remove without code; invalid → fail boot with clear error | §"sources.yaml schema" + §"Boot validation" |
| INGEST-02 | All 5 v1 sources fetched: TechCrunch RSS, Verge RSS, Ars Technica RSS, HN Firebase, Reddit r/technology | §"Per-source fetcher recipes" (3 subsections) |
| INGEST-03 | `httpx` per-source timeout, descriptive UA, `tenacity` retry max 3 exp backoff | §"httpx + tenacity composition" |
| INGEST-04 | Conditional GET: ETag + Last-Modified persisted + sent → 304 → zero new rows | §"Conditional GET mechanics (RSS only)" |
| INGEST-05 | Per-source failure isolation: 5xx/timeout/parse → warn + skip; cycle continues | §"Orchestrator flow" + D-11 |
| INGEST-06 | Unified `Article` shape: id/source/url/canonical_url/title/summary/published_at(UTC)/fetched_at/article_hash; HTML stripped via bs4/lxml | §"`ArticleRow` model" + §"HTML stripping" |
| INGEST-07 | Per-source consecutive-failure counter persisted; auto-disable at 20; re-enable via CLI (Phase 8 owns CLI; Phase 4 owns counter + flag) | §"Auto-disable mechanics" + D-12/D-13 |
</phase_requirements>

## Standard Stack

### Core (all already pinned in pyproject — except pyyaml)

| Library | Version | Purpose | Source |
|---------|---------|---------|--------|
| **pyyaml** | `>=6,<7` (target 6.0.3 latest) | `safe_load` for `sources.yaml` | [VERIFIED: PyPI] PyYAML 6.0.3 latest, Python 3.12 wheels OK |
| **pydantic** | 2.9.x (already pinned) | Discriminated union for source types | [VERIFIED: pyproject.toml line 22] |
| **httpx[http2]** | 0.28.x (already pinned) | HTTP transport for all 3 fetcher types | [VERIFIED: pyproject.toml line 14] |
| **feedparser** | 6.0.11 (already pinned) | RSS/Atom parsing | [VERIFIED: pyproject.toml line 13] |
| **tenacity** | 9.x (already pinned) | Retry on 5xx + httpx errors | [VERIFIED: pyproject.toml line 25] |
| **beautifulsoup4** | 4.12.x (already pinned) | HTML strip from RSS summaries | [VERIFIED: pyproject.toml line 26] |
| **lxml** | 5.x (already pinned) | bs4 parser backend | [VERIFIED: pyproject.toml line 27] |
| **respx** | 0.21+ (already pinned, dev) | httpx mocking in unit tests | [VERIFIED: pyproject.toml line 37] |

**Single new install:**
```bash
uv add "pyyaml>=6,<7"
```

[VERIFIED: WebSearch 2026-04] PyYAML 6.0.3 is current; 6.0.2 was the 3.12-compatible release. `>=6,<7` resolves to latest 6.x which includes 3.12 wheels. `yaml.safe_load` is the canonical safe-parser API and has been stable across 5.x/6.x.

### Already in repo (DO NOT re-implement)

| Asset | Module | Use For |
|-------|--------|---------|
| `canonicalize_url(url)` | `tech_news_synth.db.hashing` | `ArticleRow.canonical_url` |
| `article_hash(url)` | `tech_news_synth.db.hashing` | `ArticleRow.article_hash` |
| `upsert_batch(session, rows)` | `tech_news_synth.db.articles` | Final persist step |
| `SessionLocal()` | `tech_news_synth.db.session` | Already opened by `scheduler.run_cycle` |
| `get_logger(__name__)` | `tech_news_synth.logging` | structlog + bound `cycle_id` |
| `Settings` (frozen) | `tech_news_synth.config` | Add 2 fields: `sources_config_path`, `max_consecutive_failures` |

## Architecture Patterns

### Project Structure (per D-05)

```
src/tech_news_synth/
├── ingest/
│   ├── __init__.py
│   ├── models.py            # ArticleRow, Source variants, SourcesConfig
│   ├── normalize.py         # canonicalize_url+article_hash adapter; HTML strip; UTC datetime helper
│   ├── orchestrator.py      # run_ingest(session, config, http_client, settings) → counts dict
│   ├── config_loader.py     # load_sources_config(path) → SourcesConfig (called from __main__)
│   └── fetchers/
│       ├── __init__.py      # FETCHERS registry
│       ├── rss.py           # fetch(source, client, state) → list[ArticleRow]
│       ├── hn_firebase.py
│       └── reddit_json.py
```

### Pattern 1: Pydantic v2 Discriminated Union

**What:** Use `Annotated[Union[...], Field(discriminator="type")]` to dispatch on `type` key without manual factory code.
**When:** Polymorphic config with type tags. Standard pydantic v2 idiom.

```python
# src/tech_news_synth/ingest/models.py
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field, HttpUrl


class _SourceBase(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    url: HttpUrl
    timeout_sec: float = Field(default=20.0, gt=0, le=120)
    max_articles_per_fetch: int | None = Field(default=None, ge=1, le=200)


class RssSource(_SourceBase):
    type: Literal["rss"]
    timeout_sec: float = 20.0


class HnFirebaseSource(_SourceBase):
    type: Literal["hn_firebase"]
    timeout_sec: float = 15.0


class RedditJsonSource(_SourceBase):
    type: Literal["reddit_json"]
    timeout_sec: float = 15.0


Source = Annotated[
    Union[RssSource, HnFirebaseSource, RedditJsonSource],
    Field(discriminator="type"),
]


class SourcesConfig(BaseModel):
    max_articles_per_fetch: int = Field(default=30, ge=1, le=200)
    max_article_age_hours: int = Field(default=24, ge=1, le=168)
    sources: list[Source] = Field(min_length=1)


class ArticleRow(BaseModel):
    source: str
    url: str
    canonical_url: str
    article_hash: str
    title: str = Field(min_length=1)
    summary: str = ""
    published_at: datetime          # MUST be tz-aware UTC
    fetched_at: datetime            # MUST be tz-aware UTC
```

[CITED: https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions]

### Pattern 2: YAML Loader with Validated Errors

```python
# src/tech_news_synth/ingest/config_loader.py
from __future__ import annotations
import sys
from pathlib import Path
import yaml
from pydantic import ValidationError
from tech_news_synth.ingest.models import SourcesConfig


def load_sources_config(path: str | Path) -> SourcesConfig:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"sources config not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)        # T-04-04: never yaml.load
    if not isinstance(raw, dict):
        raise ValueError(f"{p}: top-level must be a mapping, got {type(raw).__name__}")
    try:
        return SourcesConfig.model_validate(raw)
    except ValidationError as e:
        # Phase 1 fail-fast pattern: stderr + re-raise so __main__ exits 2.
        print(f"sources.yaml validation error:\n{e}", file=sys.stderr)
        raise
```

### Pattern 3: Orchestrator (sequential, isolated, stateful)

```python
# src/tech_news_synth/ingest/orchestrator.py — pseudocode shape
def run_ingest(
    session: Session,
    config: SourcesConfig,
    client: httpx.Client,
    settings: Settings,
) -> dict[str, object]:
    log = get_logger(__name__)
    counts = {"articles_fetched": {}, "articles_upserted": 0,
              "sources_ok": 0, "sources_error": 0, "sources_skipped_disabled": 0}

    states = _load_or_seed_states(session, config.sources)  # upsert + dict
    now = datetime.now(timezone.utc)
    age_floor = now - timedelta(hours=config.max_article_age_hours)

    for src in config.sources:
        state = states[src.name]
        slog = log.bind(source=src.name, source_type=src.type)

        # D-12: skip at cycle start if disabled
        if state.disabled_at is not None or state.consecutive_failures >= settings.max_consecutive_failures:
            slog.info("source_skipped_disabled",
                      consecutive_failures=state.consecutive_failures,
                      disabled_at=state.disabled_at)
            counts["sources_skipped_disabled"] += 1
            continue

        slog.info("source_fetch_start")
        t0 = time.monotonic()
        try:
            fetcher = FETCHERS[src.type]
            cap = src.max_articles_per_fetch or config.max_articles_per_fetch
            rows, new_etag, new_last_mod, http_status = fetcher(src, client, state, now)
            # Filter age + slice cap (defense in depth — fetcher should also do this)
            rows = [r for r in rows if r.published_at >= age_floor]
            rows.sort(key=lambda r: r.published_at, reverse=True)
            rows = rows[:cap]

            inserted = upsert_batch(session, [r.model_dump() for r in rows])

            # Success path: reset counter + update conditional-GET state
            state.consecutive_failures = 0
            state.last_status = "skipped_304" if http_status == 304 else "ok"
            state.last_fetched_at = now
            if src.type == "rss":
                if new_etag is not None: state.etag = new_etag
                if new_last_mod is not None: state.last_modified = new_last_mod
            session.commit()

            counts["articles_fetched"][src.name] = len(rows)
            counts["articles_upserted"] += inserted
            counts["sources_ok"] += 1
            slog.info("source_fetch_end", count=len(rows), upserted=inserted,
                      status=state.last_status, elapsed_ms=int((time.monotonic()-t0)*1000))
        except Exception as e:
            state.consecutive_failures += 1
            state.last_status = f"error:{type(e).__name__}"
            if state.consecutive_failures >= settings.max_consecutive_failures and state.disabled_at is None:
                state.disabled_at = now
            session.commit()
            counts["sources_error"] += 1
            counts["articles_fetched"][src.name] = 0
            slog.warning("source_fetch_error",
                         error_type=type(e).__name__, error=str(e),
                         consecutive_failures=state.consecutive_failures,
                         elapsed_ms=int((time.monotonic()-t0)*1000))
    return counts
```

### Pattern 4: Per-Type Fetcher Contract

All fetchers return `tuple[list[ArticleRow], etag_or_None, last_modified_or_None, http_status_int]`. Only RSS populates etag/last_modified; HN/Reddit return `(rows, None, None, 200)`.

### Anti-Patterns to Avoid

- **Catching exceptions inside fetchers and returning empty lists** — masks failures from the orchestrator's failure counter. Let exceptions propagate; orchestrator owns isolation.
- **Re-using `feedparser.parse(url)` (built-in fetch)** — no timeout, no retry, no UA control. Use `feedparser.parse(response.content)` against the httpx response.
- **Hard-slicing summary `summary[:1000]`** — produces UTF-8 mid-byte breakage if summary already trimmed. Strip HTML first, then truncate.
- **`datetime.now()` (naive) anywhere** — ruff DTZ rule will fail. Use `datetime.now(timezone.utc)`.
- **Inserting `source_state` rows lazily on first success** — orchestrator must seed all yaml entries at start of `run_ingest` so D-12 skip logic has rows to read.

## Per-Source Fetcher Recipes

### A. RSS (TechCrunch, Verge, Ars Technica)

[CITED: https://feedparser.readthedocs.io/en/latest/]

**Flow:**
1. Build conditional-GET headers from `state.etag` / `state.last_modified`.
2. `client.get(url, headers=headers, timeout=httpx.Timeout(src.timeout_sec, connect=5.0))`.
3. If `response.status_code == 304`: return `([], state.etag, state.last_modified, 304)`.
4. `response.raise_for_status()` (so tenacity sees 5xx as `httpx.HTTPStatusError`).
5. `feed = feedparser.parse(response.content)`.
6. If `feed.bozo` AND `bozo_exception` is `xml.sax.SAXParseException` or `NonXMLContentType` → raise (treat as failure). `CharacterEncodingOverride` is benign — log and continue.
7. For each `entry`:
   - `title = entry.get("title", "").strip()` — skip if empty
   - `link = entry.get("link") or entry.get("id")` — skip if neither
   - `summary_html = entry.get("summary") or (entry.get("content") and entry.content[0].value) or ""`
   - `summary = strip_html(summary_html)[:1000]`
   - `pub = entry.get("published_parsed") or entry.get("updated_parsed")`
   - `published_at = datetime(*pub[:6], tzinfo=timezone.utc) if pub else fetched_at`
   - `canonical = canonicalize_url(link)`; `h = article_hash(link)`
   - emit `ArticleRow(source=src.name, url=link, canonical_url=canonical, article_hash=h, ...)`
8. Return `(rows, response.headers.get("ETag"), response.headers.get("Last-Modified"), 200)`.

**Conditional-GET headers:**
```python
headers: dict[str, str] = {}
if state.etag:           headers["If-None-Match"] = state.etag           # store verbatim — quoted/unquoted varies
if state.last_modified:  headers["If-Modified-Since"] = state.last_modified
```

**bozo handling:** [CITED: https://feedparser.readthedocs.io/en/stable/bozo.html]

### B. HN Firebase

[CITED: https://github.com/HackerNews/API]

**Flow:**
1. `r = client.get(f"{src.url}/topstories.json", timeout=...)` — returns array of up to 500 ints.
2. Take first `cap` IDs (default 30).
3. Sequentially: `r2 = client.get(f"{src.url}/item/{item_id}.json", timeout=...)`.
4. Each item JSON has fields: `by, descendants, id, kids, score, time, title, type, url, text`.
5. Map `type`:
   - `"story"` with `url` → use `url`
   - `"story"`/`"ask"`/`"show"` without `url` (Ask/Show HN text posts) → `url = f"https://news.ycombinator.com/item?id={id}"`; summary = strip_html(`text` or "")
   - `"job"` → include if has url; otherwise skip (jobs without urls are noise)
   - `"poll"`, `"pollopt"`, `"comment"` → skip
   - `null` (deleted/dead) → skip
6. `published_at = datetime.fromtimestamp(item["time"], tz=timezone.utc)`.
7. Return `(rows, None, None, 200)`.

**Sequential at N=30:** ~150-300ms per item × 30 = 5-9s per cycle. Acceptable at 2h cadence (D-06 already shipped sync `httpx.Client`).

### C. Reddit r/technology JSON

[CITED: https://til.simonwillison.net/reddit/scraping-reddit-json] [VERIFIED: WebSearch 2026-04]

**STATUS WARNING (LOW confidence):** Reddit's official policy now states unauthenticated requests have **10 QPM** limit (or are rejected entirely depending on source — docs are inconsistent in 2026). With our descriptive UA `ByteRelevant/0.1 (+https://x.com/ByteRelevant)` and only 1 fetch / 2h cycle (= 0.008 QPM), we are deeply under any threshold. Empirically, Simon Willison's TIL still shows the endpoint working with custom UAs as of mid-2025. **Plan must include a graceful 403/429 fallback path** (log, increment failure counter, continue). If Reddit becomes blocked, D-11 isolation handles it; D-12 will auto-disable after 20 failed cycles (≈40h).

**Flow:**
1. `r = client.get(src.url, timeout=...)` — UA already set on shared client.
2. If `r.status_code in (403, 429)`: raise `httpx.HTTPStatusError` (orchestrator counts as failure).
3. `data = r.json()`.
4. Iterate `data["data"]["children"]`; each child has `child["data"]` with: `title, url, created_utc, selftext, stickied, is_self, domain, permalink, id`.
5. **Skip rules:**
   - `stickied == True` (mod-pinned posts, not news)
   - `is_self == True` AND not `url.startswith("http")` (text-only self posts with no external link)
6. `published_at = datetime.fromtimestamp(child["data"]["created_utc"], tz=timezone.utc)`.
7. `summary = strip_html(child["data"].get("selftext", ""))[:1000]`.
8. Return `(rows, None, None, 200)`.

## HTML Stripping (`normalize.py`)

```python
from bs4 import BeautifulSoup

def strip_html(html: str) -> str:
    if not html:
        return ""
    # bs4 + lxml is forgiving; <script>/<style> are stripped by get_text by default.
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(" ", strip=True)
```

[CITED: https://www.crummy.com/software/BeautifulSoup/bs4/doc/#get-text] `get_text(" ", strip=True)` joins text nodes with a space and trims. Script and style content are NOT included in `get_text()` output by default (they have no text-content children, since their content is interpreted differently).

**Truncation:** apply `[:1000]` AFTER strip. UTF-8 multi-byte safety: Python str slicing operates on code points, not bytes — safe regardless of language.

## httpx + tenacity Composition

[CITED: https://tenacity.readthedocs.io/] [CITED: https://www.python-httpx.org/api/]

Tenacity wraps **the inner HTTP call**, not the whole fetcher, so retry-able transport errors and 5xx replies are retried but parse errors (which happen after `response.raise_for_status()`) are NOT retried.

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import httpx

_RETRYABLE_STATUSES = {500, 502, 503, 504, 429}  # 429 included — Reddit/HN courtesy

class _RetryableHTTP(httpx.HTTPStatusError):
    """Internal marker so tenacity only retries on the listed statuses."""

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException, _RetryableHTTP)),
    reraise=True,
)
def _http_get(client: httpx.Client, url: str, *, headers: dict[str, str], timeout: httpx.Timeout) -> httpx.Response:
    r = client.get(url, headers=headers, timeout=timeout)
    if r.status_code == 304:
        return r                          # not an error — caller short-circuits
    if r.status_code in _RETRYABLE_STATUSES:
        # Convert to retryable exception so tenacity sees it.
        raise _RetryableHTTP(f"HTTP {r.status_code}", request=r.request, response=r)
    r.raise_for_status()                  # 4xx → httpx.HTTPStatusError → NOT retried (orchestrator catches)
    return r
```

**Why a custom subclass:** tenacity's `retry_if_result` is awkward for status-code checks because the success-vs-fail semantics differ per code (304 = success, 503 = retry, 404 = give up). Raising a typed exception is cleaner than predicate gymnastics.

## Conditional GET Mechanics (RSS only)

[CITED: RFC 7232 — https://datatracker.ietf.org/doc/html/rfc7232]

**Send (if state has them):**
- `If-None-Match: <state.etag>` (etag stored verbatim — including surrounding quotes if server sent them)
- `If-Modified-Since: <state.last_modified>` (HTTP-date format like `Wed, 01 Jan 2026 12:00:00 GMT`)

**Server responses:**
- `304 Not Modified` (no body) → no new articles. Persist `etag`/`last_modified` unchanged. Set `last_status = "skipped_304"`. Do NOT increment failure counter.
- `200 OK` → parse body. Read `response.headers.get("ETag")` and `response.headers.get("Last-Modified")` and store verbatim into `source_state`.
- Some feeds return 200 with body even when nothing changed (no ETag support); idempotent upsert (`ON CONFLICT DO NOTHING`) absorbs the duplicates harmlessly.

**Storage:** TEXT columns in `source_state`. Don't try to normalize ETag quoting — strong vs weak (`W/"abc"`) and quoting are server-controlled.

## Auto-Disable Mechanics (D-12, INGEST-07)

| Event | Action |
|-------|--------|
| Fetcher raises any `Exception` | `consecutive_failures += 1`; `last_status = "error:<TypeName>"` |
| `consecutive_failures >= settings.max_consecutive_failures` AND `disabled_at IS NULL` | `disabled_at = now(UTC)` (cycle still completed this attempt) |
| Next cycle starts | Top-of-loop check: `if disabled_at IS NOT NULL OR consecutive_failures >= MAX → skip` |
| Fetcher succeeds | `consecutive_failures = 0`; `last_status = "ok"` (or `"skipped_304"`); `disabled_at` left as-is (Phase 8 CLI clears it) |
| Operator manual re-enable (interim, until Phase 8 CLI) | `UPDATE source_state SET disabled_at=NULL, consecutive_failures=0 WHERE name='X';` |

**Why "skip at cycle start, not mid-cycle":** Cleaner audit trail; the failure that crosses threshold is logged in cycle N, the skip is logged starting cycle N+1. Operator searching logs sees a clear hand-off.

## `__main__.py` and `scheduler.py` Integration

### `__main__.py::_dispatch_scheduler` boot order (after Phase 2):
```
load_settings → configure_logging → init_engine → run_migrations
  → load_sources_config(settings.sources_config_path)   # NEW (INGEST-01)
  → run(settings, sources_config=config_sources)         # NEW kwarg
```

`load_sources_config` raising `FileNotFoundError` or `ValidationError` propagates → `__main__` returns exit 2 (matches existing `ValidationError` branch).

### `scheduler.py` changes:
1. `build_scheduler(settings, sources_config)` — stash `sources_config` on the scheduler closure or pass via `kwargs`.
2. `run_cycle(settings, sources_config)` — after kill-switch check, before `_run_cycle_body`:
   ```python
   client = httpx.Client(
       headers={"User-Agent": "ByteRelevant/0.1 (+https://x.com/ByteRelevant)"},
       follow_redirects=True,
       http2=True,
   )
   try:
       counts = run_ingest(session, sources_config, client, settings)
   finally:
       client.close()
   ```
3. Pass `counts` dict to `finish_cycle(session, cycle_id, status, counts=counts)`.

### Settings additions (`config.py`):
```python
sources_config_path: str = "/app/config/sources.yaml"
max_consecutive_failures: int = Field(default=20, ge=1, le=1000)
```

Both have defaults; `.env.example` should document them but not require them.

## Alembic Migration for `source_state`

```bash
alembic revision --autogenerate -m "add source_state table"
```

Add SQLAlchemy 2.0 model alongside Phase 2 models:

```python
# src/tech_news_synth/db/models.py — append
class SourceState(Base):
    __tablename__ = "source_state"
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(Text, nullable=True)
```

**Post-edit checks** (Phase 2 D-02 protocol):
- Confirm `disabled_at` and `last_fetched_at` render as `TIMESTAMPTZ` (SA 2.0 `DateTime(timezone=True)` → `TIMESTAMPTZ` in PG dialect).
- Confirm `consecutive_failures` has `server_default="0"` so existing rows auto-fill on migration.
- No FK to `articles` (intentional — `name` is operator-controlled, not a relational reference).
- Migration filename auto-generated; commit verbatim.

## Initial `config/sources.yaml`

Replace Phase 1's stub `sources.yaml.example`:

```yaml
# config/sources.yaml — committed to repo
max_articles_per_fetch: 30
max_article_age_hours: 24

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

  - name: reddit_technology
    type: reddit_json
    url: https://www.reddit.com/r/technology/.json
    timeout_sec: 15
```

## Common Pitfalls

### Pitfall 1: feedparser's built-in fetcher
**What goes wrong:** `feedparser.parse(url)` does its own HTTP — no timeout, no UA control, no tenacity retry, no integration with the shared `httpx.Client`.
**How to avoid:** Always fetch with `httpx`, then `feedparser.parse(response.content)` (bytes, not text — preserves encoding declaration in XML prolog).
**Warning sign:** Cycle hangs > 30s on a flaky feed because `feedparser` has no timeout.

### Pitfall 2: feedparser `bozo=1` over-strict rejection
**What goes wrong:** `bozo=1` triggers on benign issues like `CharacterEncodingOverride` (server says UTF-8 but XML declares ISO-8859-1) and feed is rejected, source counted as failed.
**How to avoid:** Only treat `bozo` as failure when `feed.bozo_exception` is `xml.sax.SAXParseException` or `feedparser.NonXMLContentType`. Other bozo causes log a warning and continue.

### Pitfall 3: Naive `datetime.now()` anywhere
**What goes wrong:** ruff DTZ005/DTZ001 fails CI; runtime comparisons against TIMESTAMPTZ silently produce wrong window.
**How to avoid:** `from datetime import datetime, timezone, timedelta` + always `datetime.now(timezone.utc)`. For struct_time conversion: `datetime(*tup[:6], tzinfo=timezone.utc)`.

### Pitfall 4: `httpx.Client` not closed on exception path
**What goes wrong:** Connection pool leak across cycles → eventual file-descriptor exhaustion in long-running container.
**How to avoid:** `try/finally: client.close()` in `scheduler.run_cycle` (NOT inside `run_ingest`). Or use `with httpx.Client(...) as client:` context manager.

### Pitfall 5: ETag quoting normalization
**What goes wrong:** Operator code strips quotes from `W/"abc123"` to store `W/abc123`; server then rejects `If-None-Match: W/abc123` and re-sends full body every cycle.
**How to avoid:** Store ETag verbatim. Send verbatim. Never trim, lowercase, or unquote.

### Pitfall 6: Reddit `.json` 403 with empty/default UA
**What goes wrong:** Default `python-httpx/0.28` UA → 403 immediately. Even with custom UA, Reddit's anti-bot may serve HTML login page with 200 status.
**How to avoid:** UA already correct (D-06). Add a defensive content-type check: `if "application/json" not in r.headers.get("content-type", ""): raise ValueError(...)`. Falls into D-11 isolation.

### Pitfall 7: HN deleted/dead items returning `null`
**What goes wrong:** `client.get("/v0/item/{deleted_id}.json")` returns the JSON literal `null`. `r.json()` returns Python `None`. `None["title"]` → `TypeError`.
**How to avoid:** `item = r.json(); if item is None or item.get("dead") or item.get("deleted"): continue`.

### Pitfall 8: Concurrent cycle would corrupt `source_state`
**What goes wrong:** APScheduler `max_instances=1` (already configured in Phase 1) prevents this, but if anyone changes that setting, two cycles racing on the same `source_state` row could over/under-count failures.
**How to avoid:** Already mitigated by APScheduler config. Document the dependency in `orchestrator.py` docstring.

## Code Examples

### `_load_or_seed_states` helper

```python
from sqlalchemy.dialects.postgresql import insert as pg_insert

def _load_or_seed_states(session, sources):
    # Idempotent insert of any new source names; existing rows untouched.
    if sources:
        stmt = pg_insert(SourceState).values(
            [{"name": s.name} for s in sources]
        ).on_conflict_do_nothing(index_elements=["name"])
        session.execute(stmt)
        session.commit()
    rows = session.execute(
        select(SourceState).where(SourceState.name.in_([s.name for s in sources]))
    ).scalars().all()
    return {r.name: r for r in rows}
```

### Strip + UTC datetime helper (`normalize.py`)

```python
from datetime import datetime, timezone
from time import struct_time
from bs4 import BeautifulSoup

def strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)

def to_utc(struct: struct_time | None, fallback: datetime) -> datetime:
    if struct is None:
        return fallback
    return datetime(*struct[:6], tzinfo=timezone.utc)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `feedparser.parse(url)` (built-in HTTP) | `feedparser.parse(httpx_response.content)` | always — feedparser docs themselves recommend external fetch for production | enables timeouts, retries, unified UA |
| `requests` for HTTP | `httpx` (sync `Client`) | 2024+ ecosystem shift | already pinned; HTTP/2 + better timeout API |
| Naive in-memory dedup before insert | DB-level `ON CONFLICT DO NOTHING` | Phase 2 already shipped | one source of truth |
| Discriminator via custom factory functions | Pydantic v2 `Annotated[Union, Field(discriminator=...)]` | pydantic v2 (2023+) | type-safe + validates at parse time |

**Deprecated/outdated:**
- `requests` library — `httpx` now standard (anthropic SDK already depends on it)
- `feedparser`'s built-in HTTP fetcher — use external `httpx` instead
- Reddit's old high-rate unauthenticated API — restricted in 2023+; OAuth recommended for production-grade reliability (deferred to v2)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Reddit `.json` endpoint will work with our descriptive UA at 1 req / 2h | Reddit fetcher | LOW: D-11/D-12 handle gracefully — source auto-disables after ~40h of failures; cycle continues with 4 other sources |
| A2 | TechCrunch / Verge / Ars Technica RSS URLs are still valid | sources.yaml | LOW: easy fix in YAML; D-11 isolates failures |
| A3 | HN Firebase API endpoint stable (`hacker-news.firebaseio.com/v0`) | HN fetcher | LOW: HN API is famously stable since 2014 |
| A4 | `httpx[http2]` does not break on RSS/HN/Reddit endpoints (h2 dep already installed via pyproject extra) | httpx config | VERY LOW: HTTP/2 fallbacks transparently to HTTP/1.1 if server doesn't support |
| A5 | `bs4 + lxml` `get_text` handles all real-world RSS payloads without exceptions | normalize.py | LOW: bs4 is deeply battle-tested; pathological HTML logged but shouldn't crash |
| A6 | `feedparser.parse(bytes)` (vs `parse(str)`) handles encoding from XML prolog correctly | rss.py | LOW: feedparser's recommended idiom |

**Recommendation for discuss-phase or planner:** A1 is the only assumption with non-trivial probability (Reddit's 2026 anti-bot posture is documented as "inconsistent"). Plan should include explicit success criterion: "First live cycle in compose smoke MUST log at least one successful Reddit fetch OR document the failure mode and confirm fallback path works." If Reddit fails, defer source to v2 OAuth.

## Open Questions

1. **Does `httpx[http2]` cause any RSS-server compatibility issues?**
   - What we know: `h2` dep already pulled in via Phase 1 pyproject extra; httpx negotiates per-request.
   - What's unclear: Some older feed servers (notably enterprise CDNs) misbehave with HTTP/2 ALPN.
   - Recommendation: Keep `http2=True`; if a specific source fails, document and disable HTTP/2 per-source via a future YAML field. Not a v1 concern.

2. **Should HN Firebase fetches use a small ThreadPoolExecutor (5 workers) for parallel item fetches?**
   - What we know: Sequential at 30 items × 200ms = 6s; well under 15s timeout.
   - What's unclear: Whether VPS network jitter pushes us close to timeout under bad conditions.
   - Recommendation: Sequential v1. Add `concurrent.futures.ThreadPoolExecutor(max_workers=5)` only if Phase 4 verification shows >10s p95.

3. **Should `source.url` for `hn_firebase` type include the trailing `/v0` or not?**
   - Decision: Include it (per CONTEXT D-01 example). Fetcher appends `/topstories.json` etc.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | Runtime | ✓ | 3.12.3 | — |
| PyYAML 6.x | sources.yaml load | ✗ (NOT in pyproject) | needs install | — |
| httpx[http2] | All fetchers | ✓ (Phase 1) | 0.28.x | — |
| feedparser 6.0.11 | RSS fetcher | ✓ (Phase 1) | 6.0.11 | — |
| tenacity 9.x | Retry wrapper | ✓ (Phase 1) | 9.x | — |
| beautifulsoup4 + lxml | HTML strip | ✓ (Phase 1) | 4.12 / 5.x | — |
| respx 0.21+ | Unit tests | ✓ (Phase 1 dev) | 0.21+ | — |
| Postgres 16 | source_state migration | ✓ (Phase 2) | 16-bookworm | — |
| Alembic 1.18 | Migration | ✓ (Phase 2) | 1.18 | — |
| Internet egress to: techcrunch.com, theverge.com, arstechnica.com, hacker-news.firebaseio.com, reddit.com | Live cycles | (assume) | n/a | per-source isolation handles per-host failures |

**Missing dependencies with no fallback:**
- `pyyaml` — must be added to pyproject before any code runs.

**Missing dependencies with fallback:**
- None.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-mock + respx + time-machine |
| Config file | `pyproject.toml [tool.pytest.ini_options]` (already configured) |
| Quick run command | `uv run pytest tests/unit -q` |
| Full suite command | `POSTGRES_HOST=$(docker inspect tech-news-synth-postgres-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}') uv run pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INGEST-01 | `load_sources_config` fails clearly on missing/invalid YAML | unit | `pytest tests/unit/test_sources_config.py -x` | ❌ Wave 0 |
| INGEST-01 | Boot exits non-zero when sources.yaml absent | integration | `pytest tests/integration/test_main_boot.py::test_missing_sources_yaml -x` | ❌ Wave 0 |
| INGEST-02 | Each fetcher type returns `list[ArticleRow]` from a fixture payload | unit (per fetcher) | `pytest tests/unit/test_fetcher_rss.py tests/unit/test_fetcher_hn.py tests/unit/test_fetcher_reddit.py -x` | ❌ Wave 0 |
| INGEST-02 | Orchestrator dispatches all 5 sources in one run | integration | `pytest tests/integration/test_run_ingest.py::test_all_sources_dispatched -x` | ❌ Wave 0 |
| INGEST-03 | tenacity retries 5xx 3 times with backoff (UA header asserted) | unit | `pytest tests/unit/test_http_get_retry.py -x` | ❌ Wave 0 |
| INGEST-03 | Per-source timeout enforced | unit (respx + slow response) | `pytest tests/unit/test_fetcher_timeout.py -x` | ❌ Wave 0 |
| INGEST-04 | First cycle stores etag; second sends `If-None-Match`; 304 → 0 new rows | integration | `pytest tests/integration/test_conditional_get.py -x` | ❌ Wave 0 |
| INGEST-05 | One source returning 500 doesn't abort cycle; others succeed | integration | `pytest tests/integration/test_run_ingest.py::test_failure_isolation -x` | ❌ Wave 0 |
| INGEST-06 | `ArticleRow` validation: invalid url/empty title rejected; canonical_url + article_hash correct | unit | `pytest tests/unit/test_article_row.py -x` | ❌ Wave 0 |
| INGEST-06 | HTML strip removes `<script>` and tags | unit | `pytest tests/unit/test_strip_html.py -x` | ❌ Wave 0 |
| INGEST-07 | After 20 simulated failures, source's `disabled_at` is set | integration | `pytest tests/integration/test_auto_disable.py -x` | ❌ Wave 0 |
| INGEST-07 | Disabled source skipped at next cycle start | integration | `pytest tests/integration/test_auto_disable.py::test_skip_after_disable -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/unit -q && uv run ruff check .`
- **Per wave merge:** Full suite (unit + integration with live postgres)
- **Phase gate:** Full suite green + compose smoke (operator) before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_sources_config.py` — covers INGEST-01
- [ ] `tests/unit/test_article_row.py` — covers INGEST-06 (model validation)
- [ ] `tests/unit/test_strip_html.py` — covers INGEST-06 (normalize)
- [ ] `tests/unit/test_http_get_retry.py` — covers INGEST-03 (tenacity)
- [ ] `tests/unit/test_fetcher_rss.py` — covers INGEST-02 (RSS variant) + INGEST-04 (304 path)
- [ ] `tests/unit/test_fetcher_hn.py` — covers INGEST-02 (HN variant)
- [ ] `tests/unit/test_fetcher_reddit.py` — covers INGEST-02 (Reddit variant)
- [ ] `tests/unit/test_fetcher_timeout.py` — covers INGEST-03 (timeout)
- [ ] `tests/integration/test_run_ingest.py` — covers INGEST-02, INGEST-05
- [ ] `tests/integration/test_conditional_get.py` — covers INGEST-04
- [ ] `tests/integration/test_auto_disable.py` — covers INGEST-07
- [ ] `tests/integration/test_main_boot.py` — covers INGEST-01 (boot path)
- [ ] `tests/fixtures/rss/{techcrunch,verge,ars}.xml` — RSS fixture files (canned real responses)
- [ ] `tests/fixtures/json/{hn_topstories,hn_item_story,hn_item_ask,reddit_listing}.json` — JSON fixtures

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | All sources are unauthenticated public endpoints |
| V3 Session Management | no | Stateless HTTP fetches |
| V4 Access Control | no | Read-only public data |
| V5 Input Validation | yes | pydantic v2 discriminated union + ArticleRow validation |
| V6 Cryptography | no | TLS handled by httpx; no app-layer crypto |
| V11 Business Logic | yes | Failure isolation + auto-disable enforce upper bound on bad-source impact |
| V12 File Resources | yes | `yaml.safe_load` (T-04-04); only one fixed config path |
| V13 API | yes | All external HTTP via single `httpx.Client` with bounded timeouts + retries |
| V14 Configuration | yes | Bound `max_consecutive_failures`; bind-mount read-only |

### Known Threat Patterns for {Python httpx + RSS/JSON ingestion}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| **T-04-01: SSRF via operator-controlled `sources.yaml` URL** | Tampering / Information Disclosure | Operator-trusted YAML (bind-mount), but also: pydantic `HttpUrl` validates scheme is http/https; httpx `follow_redirects=True` respects scheme; document operator trust boundary in `config/README.md` |
| **T-04-02: XXE in RSS via lxml entity expansion** | Tampering / DoS | feedparser sets `resolve_entities=False` by default and uses defusedxml-style hardening; passing `response.content` to `feedparser.parse` (not raw lxml) inherits this mitigation |
| **T-04-03: Unbounded response (zip bomb / huge feed)** | DoS | httpx timeout (per source), bounded retries (3), summary truncation (1000 chars), DB upsert idempotency. Optional defense: `r.read()` with content-length pre-check. v1: rely on timeout + per-cycle isolation |
| **T-04-04: YAML deserialization RCE** | EoP | `yaml.safe_load` ONLY — never `yaml.load`. Already locked in D-03 |
| **T-04-05: SQL injection via source name** | Tampering | All SQL via SQLAlchemy ORM/Core (parameterized); operator-supplied `name` constrained by pydantic regex `^[a-z][a-z0-9_]*$` (defense in depth) |
| **T-04-06: Log injection via article title (CRLF / ANSI escape)** | Tampering | structlog JSON renderer escapes control chars automatically (orjson) |
| **T-04-07: HTML script injection in summary** | Tampering / XSS | `bs4.get_text()` strips tags including script bodies; output is plain text. Summary is also display-only in Phase 6 LLM prompt — no HTML render path |
| **T-04-08: Disclosed PII / secrets via fetched RSS body stored in DB** | Information Disclosure | Out of scope: public sources; we control what to truncate. Phase 6 handles LLM prompt grounding (no PII concern at fetch layer) |
| **T-04-09: Feed serving malicious URLs that get re-published** | Tampering | Out of scope at Phase 4. Phase 6/7 own publish-time URL allowlist if needed |

## Sources

### Primary (HIGH confidence)
- [pydantic v2 Discriminated Unions docs](https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions) — discriminator pattern
- [httpx Client docs](https://www.python-httpx.org/api/#client) — per-request timeout, headers
- [tenacity docs](https://tenacity.readthedocs.io/) — retry decorator
- [feedparser bozo docs](https://feedparser.readthedocs.io/en/stable/bozo.html) — bozo exception handling
- [feedparser docs root](https://feedparser.readthedocs.io/en/latest/) — `parse(bytes)` recommendation
- [Hacker News API GitHub](https://github.com/HackerNews/API) — endpoint shape, item types
- [BeautifulSoup get_text docs](https://www.crummy.com/software/BeautifulSoup/bs4/doc/#get-text)
- [PyPI PyYAML](https://pypi.org/project/PyYAML/) — 6.0.3 latest, 3.12 wheels OK
- [RFC 7232 Conditional Requests](https://datatracker.ietf.org/doc/html/rfc7232) — ETag / If-None-Match semantics
- [SQLAlchemy 2.0 declarative_base docs](https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html) — used for SourceState model
- Phase 2 SUMMARY (`02-02-SUMMARY.md`) — `upsert_batch` contract, session lifecycle
- Phase 1 / Phase 2 / Phase 4 CONTEXT files — locked decisions D-01 to D-14

### Secondary (MEDIUM confidence)
- [Simon Willison's TIL: Reddit JSON scraping](https://til.simonwillison.net/reddit/scraping-reddit-json) — practitioner notes on UA + rate limits
- [PainOnSocial: Reddit API rate limits 2026](https://painonsocial.com/blog/reddit-api-rate-limits-guide) — 10 QPM unauth, custom UA helps

### Tertiary (LOW confidence — flag for live verification at compose smoke)
- Reddit `.json` endpoint reliability under 2026 anti-bot posture (A1 in Assumptions Log) — needs live test in Phase 4 verification

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libs already pinned and used in Phase 1/2; only `pyyaml` is new and is itself trivial
- Architecture: HIGH — sequential orchestrator with per-source isolation is a well-known pattern; fetcher contract is small
- Pitfalls: HIGH for feedparser/datetime/httpx; MEDIUM for Reddit 2026 anti-bot behavior

**Research date:** 2026-04-12
**Valid until:** 2026-05-12 (30 days; Reddit endpoint behavior may shift sooner — re-verify if Phase 4 isn't started by 2026-04-30)
