# Phase 1: Foundations - Context

**Gathered:** 2026-04-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver a running, observable, scheduled container chassis: `docker compose up` brings up healthy `app` + `postgres` services with validated secrets, UTC invariants, a PID-1 APScheduler firing a no-op `run_cycle()` on cadence, structured JSON logs to stdout + volume, graceful exception handling, and working `PAUSED` / `DRY_RUN` switches. No ingestion, clustering, synthesis, or publishing logic — those belong to later phases. This phase locks the import root, entrypoint, config shape, and log contract that every later phase writes through.

</domain>

<decisions>
## Implementation Decisions

### Package & Layout
- **D-01:** Python package name is `tech_news_synth` (matches repo name). Overrides an earlier consideration of `denver` / `byterelevant` / `app`. All downstream phases import from this root.
- **D-02:** Source layout is `src/tech_news_synth/` (src-layout). `pyproject.toml` points `[tool.hatch.build.targets.wheel] packages = ["src/tech_news_synth"]` (or equivalent for chosen build backend). Prevents accidental imports from repo root during tests.
- **D-03:** Runtime config `sources.yaml` lives in repo `./config/sources.yaml`, bind-mounted **read-only** to `/app/config/sources.yaml` in the container. Operator edits YAML on host and restarts — clean code/config separation. (Content of `sources.yaml` is populated in Phase 4; Phase 1 only wires the mount and validates the path exists if referenced.)

### Dockerfile & Entrypoint
- **D-04:** Dockerfile uses **multi-stage build** with `uv`:
  - Stage 1 (builder): `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` (or equivalent) runs `uv sync --frozen --no-dev` into `/app/.venv`.
  - Stage 2 (runtime): `python:3.12-slim-bookworm` copies `/app/.venv` + `src/` + `pyproject.toml` + `uv.lock`. Runtime image ≈ 150 MB, no build tools shipped.
- **D-05:** Container entrypoint is `python -m tech_news_synth` (runs `src/tech_news_synth/__main__.py`, which boots APScheduler). No `[project.scripts]` console script required for v1.
- **D-06:** CLI tools (`replay`, `post-now`, `source-health`) are exposed as **sub-commands under the same entrypoint**: `python -m tech_news_synth <subcommand>`. Phase 1 wires the argparse/click dispatcher skeleton; actual CLI implementations land in later phases (OPS-02/03/04 in Phase 8). Scheduler is the default when no subcommand is given (`python -m tech_news_synth` with no args = run scheduler).

### Scheduler & Cycle Semantics
- **D-07:** **First tick runs immediately on container startup**, then APScheduler `CronTrigger(hour="*/{INTERVAL_HOURS}", timezone=timezone.utc)` takes over for subsequent cycles. Rationale: immediate log feedback on deploy confirms the chassis works; no need to wait up to 2h for the first observable behavior. Trade-off acknowledged: every container restart triggers a cycle — acceptable in v1 because Phase 1 `run_cycle()` is a no-op and by the time later phases add I/O the daily cap (PUBLISH-04) and dry-run mode prevent runaway cost.
- **D-08:** Kill-switch uses **OR logic between `PAUSED=1` env and `/data/paused` marker file**: cycle is paused if either is set. Cycle-start log line states which source triggered via `paused_by` field (`env`, `marker`, or `both`). Env var = restart-required toggle (set in `.env`); marker file = live toggle without restart (`docker compose exec app touch /data/paused`). When paused, cycle exits with `status=paused`, performs zero I/O, returns 0.
- **D-09:** `cycle_id` format is **ULID** (26-char Crockford base32, time-sortable). Dependency: `python-ulid`. Generated once at cycle start, bound to structlog context, persisted as `run_log.cycle_id` (Phase 2) and tagged on every log line in the cycle. Chosen over UUIDv4 for chronological grep-ability and over custom timestamp strings to avoid format drift.
- **D-10:** `DRY_RUN=1` is **bound into every cycle log line** via structlog `contextvars.bind_contextvars(dry_run=...)` at cycle start. Zero chance of losing the flag when post-hoc analyzing logs. Phase 1 `run_cycle()` has no publish step, so `DRY_RUN` is a no-op behaviorally but must be visible in logs per INFRA-10.

### Claude's Discretion
- Exact pydantic-settings class shape, field validators, and `SecretStr` usage (Claude picks idiomatic pattern).
- structlog processor chain and JSON renderer choice (orjson recommended per STACK.md).
- Dockerfile layer ordering and caching optimizations.
- Healthcheck commands (`pg_isready` for postgres; app healthcheck probe — likely a file-write or `python -c` import smoke).
- Logging file path and rotation policy inside the logs volume (not discussed — Claude picks sensible default, e.g. `/data/logs/app.jsonl` without rotation in v1; size-based rotation can land later).
- Test scope for Phase 1 — unit tests for config load + kill-switch + cycle_id formatting; integration test via `docker compose up` smoke in CI is optional.
- Exact pyproject build backend (hatchling vs setuptools) — Claude picks; must be uv-compatible.
- Pre-commit hook implementation for INFRA-04 secret-leak detection (gitleaks vs detect-secrets vs custom regex).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project context
- `.planning/PROJECT.md` — vision, constraints, key decisions
- `.planning/REQUIREMENTS.md` §INFRA-01..INFRA-10 — acceptance criteria this phase delivers
- `.planning/ROADMAP.md` §"Phase 1: Foundations" — goal and success criteria
- `CLAUDE.md` — project instructions and tech stack rationale

### Research outputs
- `.planning/research/STACK.md` — pinned versions (Python 3.12, uv, APScheduler 3.10, structlog 25.x, pydantic-settings 2.6, python-ulid); Dockerfile multi-stage pattern; "APScheduler as PID 1" rationale; Alpine-avoidance rationale
- `.planning/research/ARCHITECTURE.md` — cycle lifecycle, structlog context binding, kill-switch mechanics
- `.planning/research/PITFALLS.md` — system-cron-in-container anti-pattern, Alpine wheels issue, `TZ=` env gotcha, pydantic SecretStr logging

### External specs (read when implementing)
- APScheduler 3.10 `BlockingScheduler` + `CronTrigger` docs — https://apscheduler.readthedocs.io/en/3.x/
- pydantic-settings 2.6 — `.env` loading, `SecretStr` — https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- structlog 25 performance/JSON docs — https://www.structlog.org/en/stable/performance.html
- uv Docker guide — https://docs.astral.sh/uv/guides/integration/docker/

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **None** — greenfield repo. Only `.planning/`, `CLAUDE.md`, `README.md`, `.gitignore` exist at Phase 1 start.

### Established Patterns
- **None in code**. All patterns in this phase are net-new and become the templates later phases copy.

### Integration Points
- This phase **is** the integration surface for everything downstream:
  - `tech_news_synth.config.Settings` (pydantic-settings) — every later module reads from it
  - `tech_news_synth.scheduler.run_cycle()` — later phases replace the no-op body
  - `tech_news_synth.logging.configure_logging()` + `cycle_id` binding — every later phase logs through this
  - Postgres service in `compose.yaml` — Phase 2 wires Alembic against it
  - `/data` volume (logs + marker file) and `/app/config` bind-mount — Phase 4 reads `sources.yaml` from here

</code_context>

<specifics>
## Specific Ideas

- Brand voice is `@ByteRelevant` on X, but the Python package is **`tech_news_synth`** (user explicitly overrode branded naming). Keep the package name neutral; brand strings only appear in the User-Agent header (Phase 4) and any operator-facing runbook.
- First-tick-on-boot is a deliberate DX choice — expect it in logs on every `docker compose up`.
- ULIDs in logs will look like `01ARZ3NDEKTSV4RRFFQ69G5FAV` — downstream plans should treat them as opaque 26-char strings.

</specifics>

<deferred>
## Deferred Ideas

- **Logging rotation / per-level routing** — not discussed; Claude's default (single JSONL file, no rotation in v1) stands unless Phase 8 hardening asks for rotation.
- **App healthcheck semantics beyond "process alive"** — liveness via marker file write or sidecar probe can be added in Phase 8 if the VPS needs it.
- **Integration test via docker-compose in CI** — optional for Phase 1; unit tests cover config + kill-switch + cycle_id. Full compose-up smoke can land later.
- **Console scripts (`[project.scripts]`)** — not shipped in v1; revisit if operator ergonomics complain.
- **Multi-arch container builds (arm64)** — VPS is x86_64; skip.

</deferred>

---

*Phase: 01-foundations*
*Context gathered: 2026-04-12 via /gsd-discuss-phase*
