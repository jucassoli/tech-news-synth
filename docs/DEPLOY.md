# tech-news-synth — Deployment Runbook

> Walks a fresh Ubuntu 22.04+ VPS from `git clone` to a healthy
> `@ByteRelevant` agent in under 30 minutes. Follow sections in order.
> Every code block is copy-paste-ready — the only placeholders are
> `<angle-bracketed>` values you must substitute (secrets, timestamps, IDs).

**Applies to:** Phase 1-8 v1.0 ship. Single-host, single-account, Postgres-16 + APScheduler in-container.

**Covers:** OPS-05 (runbook), OPS-06 (48h soak), SC-5 (post-cutover verification).

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Secrets Acquisition](#2-secrets-acquisition)
3. [Clone + Configure](#3-clone--configure)
4. [Boot](#4-boot)
5. [First-Cycle Verification](#5-first-cycle-verification)
6. [Daily Operations](#6-daily-operations)
7. [Soak + Cutover](#7-soak--cutover)
   - [7.1 48h DRY_RUN Soak](#71-48h-dry_run-soak)
   - [7.2 Live Cutover Checklist](#72-live-cutover-checklist)
   - [7.3 Rollback](#73-rollback)
8. [Troubleshooting](#8-troubleshooting)
9. [References](#9-references)

---

## 1. Prerequisites

**Host.**

- Ubuntu 22.04 LTS or 24.04 LTS (any x86_64 VPS — Hetzner, DigitalOcean, Scaleway, OVH, etc.)
- ≥ 2 GB RAM, ≥ 5 GB free disk
- Outbound HTTPS egress to:
  - `api.anthropic.com` (synthesis)
  - `api.x.com` (publishing)
  - The five source domains resolved from `config/sources.yaml`:
    `techcrunch.com`, `theverge.com`, `arstechnica.com`,
    `hacker-news.firebaseio.com`, `www.reddit.com`

**Software.**

```bash
# Install Docker Engine (>=26) + Compose v2 plugin the official way:
sudo apt update
sudo apt install -y ca-certificates curl gnupg git
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add your user to the docker group so you don't need sudo for every command:
sudo usermod -aG docker "$USER"
# Log out and back in for the group change to take effect.
```

Verify:

```bash
docker --version          # Docker version 26.x or higher
docker compose version    # Docker Compose version v2.x (NOT docker-compose v1)
git --version
```

If `docker compose version` prints `command not found` or v1, install the **plugin** (the `docker-compose-plugin` apt package above). This project uses Compose v2 syntax — `docker compose` (space), not `docker-compose` (hyphen).

---

## 2. Secrets Acquisition

You need **five** secrets total: 1 Anthropic key + 4 X OAuth tokens. Record them in a password manager first; they'll go into `.env` in the next section.

### 2.1 Anthropic API Key

1. Sign in to <https://console.anthropic.com>.
2. Settings → **API Keys** → **Create Key**.
3. Name: `tech-news-synth`. Workspace: default.
4. Copy the `sk-ant-...` value (shown once). Store as `ANTHROPIC_API_KEY`.

Validate (optional, requires uv + Python 3.12 on the host OR inside the container):

```bash
ANTHROPIC_API_KEY=sk-ant-... uv run python scripts/smoke_anthropic.py
# Expected: prints a short PT-BR response and token cost < $0.001.
```

### 2.2 X (Twitter) OAuth 1.0a User Context — @ByteRelevant

> **Critical ordering:** set Read + Write permissions on the app **before**
> generating tokens. If you generate tokens first and flip permissions later,
> the tokens will be read-only. Regenerate them after the permission change.

1. Sign in to <https://developer.x.com> as the owner of `@ByteRelevant`.
2. Developer Portal → Projects → create (or open) the project → create an App.
3. App → **User authentication settings**:
   - App permissions: **Read and write** (NOT "Read" — posting requires write).
   - Type of App: Web app / Automated app or bot.
   - Callback URL: `http://localhost` (unused — required field only).
   - Save.
4. App → **Keys and tokens** tab:
   - **Consumer Keys** → Regenerate (or show) → copy `X_CONSUMER_KEY` + `X_CONSUMER_SECRET`.
   - **Authentication Tokens** → **Access Token and Secret** → Generate →
     copy `X_ACCESS_TOKEN` + `X_ACCESS_TOKEN_SECRET`.
     Confirm the "Created with permissions: Read and Write" line.

Validate (optional):

```bash
X_CONSUMER_KEY=... X_CONSUMER_SECRET=... \
X_ACCESS_TOKEN=... X_ACCESS_TOKEN_SECRET=... \
    uv run python scripts/smoke_x_auth.py
# Expected: prints the @ByteRelevant handle + user id + "Read+Write OK".
```

See `scripts/smoke_x_post.py` for an end-to-end posting smoke (will post a real tweet — only run with DRY_RUN validated).

---

## 3. Clone + Configure

```bash
git clone https://github.com/<owner>/tech-news-synth.git
cd tech-news-synth
cp .env.example .env
$EDITOR .env
```

Fill the **required** keys in `.env`:

| Env var                     | Notes                                                      |
| --------------------------- | ---------------------------------------------------------- |
| `ANTHROPIC_API_KEY`         | From §2.1.                                                 |
| `X_CONSUMER_KEY`            | From §2.2.                                                 |
| `X_CONSUMER_SECRET`         | From §2.2.                                                 |
| `X_ACCESS_TOKEN`            | From §2.2.                                                 |
| `X_ACCESS_TOKEN_SECRET`     | From §2.2.                                                 |
| `POSTGRES_PASSWORD`         | Strong random password (`openssl rand -base64 24`).        |
| `DRY_RUN`                   | **Set to `1` for first boot** (skips real X posting).      |

Optional tuning (leave defaults unless you have a reason):

| Env var                         | Default | Meaning                                                                  |
| ------------------------------- | ------- | ------------------------------------------------------------------------ |
| `INTERVAL_HOURS`                | 2       | Scheduler cadence. Must divide 24 (allowed: 1, 2, 3, 4, 6, 8, 12, 24).   |
| `MAX_POSTS_PER_DAY`             | 12      | Hard cap before PUBLISH-04 kicks in.                                     |
| `MAX_MONTHLY_COST_USD`          | 30.00   | Hard kill-switch when X+synthesis cost exceeds this in a rolling month.  |
| `CLUSTER_WINDOW_HOURS`          | 6       | How far back to pull articles when clustering.                           |
| `ANTI_REPEAT_WINDOW_HOURS`      | 48      | Skip theme if we already posted a similar one within this window.        |
| `ANTI_REPEAT_COSINE_THRESHOLD`  | 0.5     | Similarity threshold for anti-repeat gate.                               |
| `PUBLISH_STALE_PENDING_MINUTES` | 5       | Orphan-pending cleanup threshold (Phase 7).                              |
| `X_API_TIMEOUT_SEC`             | 30      | Timeout on `client.create_tweet`.                                        |

The `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `LOG_DIR`, `PAUSED_MARKER_PATH`, and `SOURCES_CONFIG_PATH` defaults are correct for the Docker Compose deployment and should not be changed.

Verify `.env` is gitignored (pre-commit should also flag it):

```bash
git check-ignore -v .env    # prints the matching .gitignore rule
```

---

## 4. Boot

```bash
docker compose up -d --build
```

Wait ~60s for both services to become healthy, then:

```bash
docker compose ps
# NAME                        STATUS                 PORTS
# tech-news-synth-postgres-1  Up 45 seconds (healthy)
# tech-news-synth-app-1       Up 45 seconds (healthy)
```

If either shows `unhealthy` or `restarting`, jump to [§8 Troubleshooting](#8-troubleshooting).

Tail live logs:

```bash
docker compose logs -f app
```

APScheduler fires an immediate first cycle on boot (Phase 1 D-07) — you should see a `scheduler_starting` line, then `cycle_start`, then per-source `source_fetch_*` lines, then (usually) one `cycle_summary` line within ~30-90s.

---

## 5. First-Cycle Verification

With `DRY_RUN=1` in `.env`, the agent performs every step except the actual X posting — the `posts` row status will be `dry_run` instead of `posted`.

Expected `cycle_summary` fields (Plan 08-01 D-06):

```bash
docker compose logs app | grep cycle_summary | tail -1 | jq '.'
```

```json
{
  "event": "cycle_summary",
  "cycle_id": "01KP...",
  "duration_ms": 3421,
  "articles_fetched_per_source": {"techcrunch": 8, "verge": 12, ...},
  "cluster_count": 4,
  "chosen_cluster_id": 42,
  "char_budget_used": 223,
  "token_cost_usd": 0.00014,
  "post_status": "dry_run",
  "status": "ok",
  "dry_run": true,
  "timestamp": "2026-04-15T12:00:03.421Z"
}
```

Quick SQL sanity check:

```bash
docker compose exec postgres \
  psql -U app -d tech_news_synth \
  -c "SELECT cycle_id, status, started_at, finished_at FROM run_log ORDER BY started_at DESC LIMIT 1;"
```

Cross-checks:

```bash
# All sources health:
docker compose exec app python -m tech_news_synth source-health

# Pending posts from this cycle (should be 0 or 1 dry_run row):
docker compose exec postgres \
  psql -U app -d tech_news_synth \
  -c "SELECT id, status, created_at FROM posts ORDER BY id DESC LIMIT 3;"
```

If you see `cycle_summary` + a `dry_run` posts row (or an empty-window skip with `post_status=empty`), the boot is successful. Proceed to §6.

---

## 6. Daily Operations

All commands are idempotent and safe to run while the scheduler is up (session isolation + Phase 7 stale-pending guard).

### Tail logs

```bash
# Live:
docker compose logs -f app

# Just cycle summaries (operator dashboard view):
docker compose logs app | grep cycle_summary | jq '.'

# Errors only:
docker compose logs app | jq 'select(.level=="error")'
```

### Source health

```bash
# Aligned-text status table:
docker compose exec app python -m tech_news_synth source-health

# Machine-readable:
docker compose exec app python -m tech_news_synth source-health --json | jq '.'

# Re-enable a source that was auto-disabled by Phase 4 INGEST-07:
docker compose exec app python -m tech_news_synth source-health --enable reddit_technology

# Manually disable a misbehaving source:
docker compose exec app python -m tech_news_synth source-health --disable ars_technica
```

Unknown source name → exit 1 + `stderr: "unknown source: NAME"`. Toggles are idempotent and audit-logged (`source_toggled` structured event).

### Force a cycle off-cadence

```bash
docker compose exec app python -m tech_news_synth post-now
```

Blocks ~30-90s, writes a `run_log` row + emits `cycle_summary`. Exit 0 on `status='ok'` (includes capped / dry_run / paused), exit 1 on `status='error'`.

### Replay a past cycle offline (no writes)

Useful for prompt-iterating synthesis against a historical article set.

```bash
# Pick a cycle:
docker compose exec postgres \
  psql -U app -d tech_news_synth \
  -c "SELECT cycle_id FROM run_log ORDER BY started_at DESC LIMIT 5;"

# Replay (real Anthropic call — ~$0.0001):
docker compose exec app python -m tech_news_synth replay --cycle-id 01KP...
```

Prints a JSON payload with `text`, `hashtags`, `cost_usd`, `input_tokens`, `output_tokens`, `final_method`. Never writes a `posts` row (defense-in-depth `session.rollback()`).

### Kill switch (live, no restart)

```bash
# Pause (next cycle exits early with status='paused', emits no posts row):
docker compose exec app touch /data/paused

# Resume:
docker compose exec app rm /data/paused
```

### DRY_RUN toggle (requires restart)

```bash
$EDITOR .env                # flip DRY_RUN=1 <-> DRY_RUN=0
docker compose restart app
```

### Container + migration state

```bash
docker compose ps
docker compose exec app alembic current      # prints current schema revision
docker compose exec postgres psql -U app -d tech_news_synth -c "\dt"
```

---

## 7. Soak + Cutover

v1 ships after the 48h DRY_RUN soak (§7.1) passes AND the live cutover (§7.2) produces ≥ 12 clean tweets in 24h. §7.3 is the rollback path if something goes wrong.

### 7.1 48h DRY_RUN Soak

**Purpose:** prove the agent runs for 48h without intervention, producing ≥ 24 cycles (one per 2h ± 30min tolerance), zero unhandled exceptions, ≤ 2 transient failures — Phase 8 D-08 / OPS-06 pass criteria.

Preconditions:

```bash
grep '^DRY_RUN=' .env      # must print DRY_RUN=1
docker compose restart app # pick up the setting if you just changed it
```

Start the monitor in the background (detached, survives terminal disconnect):

```bash
nohup docker compose run --rm app \
    uv run python scripts/soak_monitor.py --hours 48 --poll-minutes 30 \
    > soak.out 2>&1 &
```

Or attached in a terminal (Ctrl+C stops and writes final summary):

```bash
docker compose run --rm app \
    uv run python scripts/soak_monitor.py --hours 48 --poll-minutes 30
```

Monitor output: one JSON line per poll on stdout AND appended to `.planning/intel/soak-log.md`. Example:

```json
{"ts": "2026-04-15T14:00:00+00:00", "last_cycle_age_min": 5.2, "cycles_last_24h": 11, "cycles_last_48h": 23, "failed_last_48h": 0, "dry_run_posts_last_24h": 10}
```

Red flags the monitor watches for:

| Flag | Condition                              | Action                                            |
| ---- | -------------------------------------- | ------------------------------------------------- |
| Soft | `last_cycle_age_min > 150` (>2.5h)     | stderr warn; continue (may be transient)          |
| Hard | `failed_last_48h > 2`                  | stderr error; monitor exits 1 (investigate + re-soak) |

After 48h:

1. Check the end of `.planning/intel/soak-log.md` for a `### Soak run ended ...` block with `D-08 PASS: True`.
2. Fill the **Operator Sign-Off** table at the top of `.planning/intel/soak-log.md`.
3. Commit the filled-in intel file: `git add .planning/intel/soak-log.md && git commit -m "intel(08-02): soak run 2026-04-15 PASSED"`.
4. If PASS → proceed to §7.2. If FAIL → investigate root cause, fix, restart from a clean DB snapshot if necessary, re-soak.

### 7.2 Live Cutover Checklist

1. **Confirm soak passed.** Re-check the sign-off in `.planning/intel/soak-log.md`.
2. Flip `DRY_RUN=0` in `.env`:
   ```bash
   $EDITOR .env
   # DRY_RUN=1   ->   DRY_RUN=0
   ```
3. Restart app:
   ```bash
   docker compose restart app
   ```
4. **Record the cutover timestamp** (you'll need it for §7.2 step 7):
   ```bash
   CUTOVER_TS=$(date -u --iso-8601=seconds)
   echo "$CUTOVER_TS" | tee -a .planning/intel/cutover-report.md
   # Example: 2026-04-17T12:00:00+00:00
   ```
5. Monitor the first 3 live cycles (~6h):
   ```bash
   docker compose logs -f app | grep cycle_summary
   ```
   Expect `post_status=posted`, `dry_run=false`, `status=ok`.
6. Spot-check the timeline at <https://x.com/ByteRelevant> — real tweets should appear, once per cycle, in PT-BR, with shortened URLs and the expected hashtags.
7. **After 24h**, run the acceptance check:
   ```bash
   docker compose run --rm app \
       uv run python scripts/cutover_verify.py --since "$CUTOVER_TS"
   ```
   Expected output: one `## Cutover verification — <ts>` block appended to `.planning/intel/cutover-report.md`, stdout echo of same, **exit 0 on GO**.

   Pass criteria (SC-5):
   - Posts in 24h: ≥ 12
   - Jaccard duplicates (48h window, threshold 0.5): 0
   - Cost 24h: ≤ $0.7224 (2× baseline $0.3612)
8. Fill the **Operator Sign-Off** table at the top of `.planning/intel/cutover-report.md`.
9. Commit: `git add .planning/intel/cutover-report.md && git commit -m "intel(08-02): cutover GO verdict <date>"`.

If **NO-GO**: see §7.3.

### 7.3 Rollback

Rollback is a manual, documented flip — no watchdog, no auto-rollback (single operator is the trust boundary).

```bash
# 1. Halt live posting:
$EDITOR .env                # DRY_RUN=0  ->  DRY_RUN=1
docker compose restart app

# 2. Investigate pending rows from the cutover window:
docker compose exec postgres \
  psql -U app -d tech_news_synth -c \
  "SELECT id, cycle_id, status, created_at, error_detail FROM posts \
   WHERE created_at > '<CUTOVER_TS>' ORDER BY created_at;"

# 3. (Optional) Manually delete any offending tweets from the
#    @ByteRelevant timeline via the X web UI.

# 4. (Optional) If a row is stuck `pending` beyond
#    PUBLISH_STALE_PENDING_MINUTES, Phase 7 auto-cleans it on the next
#    cycle (marks as 'failed' with error_detail='stale_pending_cleanup').
#    See docs/runbook-orphaned-pending.md for the full procedure.
```

Once you've captured the failure mode and fixed it (code or config), redo §7.1 (48h soak) before attempting §7.2 again.

---

## 8. Troubleshooting

| Symptom                                         | Likely cause                                          | Fix                                                                                                                             |
| ----------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `posts` rows stuck `status='pending'`           | Publish crashed between `insert_post` and `update_post_to_posted` | Phase 7 auto-cleans after `PUBLISH_STALE_PENDING_MINUTES`. Manual procedure: `docs/runbook-orphaned-pending.md`.                |
| Source consistently `disabled`                  | `MAX_CONSECUTIVE_FAILURES` exceeded (INGEST-07)       | Investigate feed URL (may have changed); `source-health --enable NAME` after the root cause is fixed.                           |
| Anthropic `401` / `403`                         | Stale / wrong `ANTHROPIC_API_KEY`                     | Re-check at console.anthropic.com → API Keys. Rotate in `.env`, `docker compose restart app`.                                   |
| Anthropic `529` / overloaded                    | Transient upstream                                    | Phase 6 tenacity retries + `cycle_summary.status=error` for this cycle. Resolves on the next cycle.                             |
| X `401` / `403`                                 | Token was generated BEFORE Read+Write permission was set | Regenerate all four OAuth tokens per §2.2 after confirming Read+Write is active. Update `.env`, restart.                        |
| X `429 Too Many Requests`                       | Rate limit                                            | Phase 7 logs + skips rest of cycle; next cycle retries. Check `x-rate-limit-reset` header in logs.                              |
| `publish_status=capped` in `cycle_summary`      | `MAX_POSTS_PER_DAY` reached for the UTC day           | Expected; next cycle retries at UTC midnight. Raise `MAX_POSTS_PER_DAY` in `.env` + restart if you intentionally want more.     |
| Cycle hits monthly cost cap                     | `MAX_MONTHLY_COST_USD` exceeded                       | Hard kill-switch — every subsequent cycle exits `paused` until the UTC month rolls over OR you raise the cap in `.env`.         |
| `unhealthy` container on `docker compose ps`    | Healthcheck failing                                   | `docker compose logs --tail=100 app` and `docker compose logs postgres`. DB connectivity issue is most common.                  |
| Alembic migration failure on boot               | Version skew after `git pull`                         | `docker compose logs app` → look for migration stacktrace. May need `docker compose run --rm app alembic downgrade <rev>`.      |
| `cycle_summary` not emitted for a cycle         | Cycle hit `paused` kill switch — no row written       | Expected: kill switch short-circuits BEFORE `start_cycle`. Not a bug.                                                           |

---

## 9. References

- Phase 3 cost baseline intel: `.planning/intel/x-api-baseline.md`
- Phase 7 orphaned-pending operator runbook: `docs/runbook-orphaned-pending.md`
- Phase 8 soak log: `.planning/intel/soak-log.md`
- Phase 8 cutover report: `.planning/intel/cutover-report.md`
- Project constraints and tech stack: `CLAUDE.md` + `.planning/PROJECT.md`
- Requirements traceability: `.planning/REQUIREMENTS.md`
- Smoke scripts (hand-run, optional): `scripts/smoke_anthropic.py`, `scripts/smoke_x_auth.py`, `scripts/smoke_x_post.py`
- Soak monitor: `scripts/soak_monitor.py` (§7.1)
- Cutover verifier: `scripts/cutover_verify.py` (§7.2 step 7)

---

*Runbook maintained alongside the code. If you change behavior, update this file in the same commit.*
