# Soak Log — tech-news-synth DRY_RUN 48h

> Append-only. `scripts/soak_monitor.py` appends one JSON line per poll
> (default cadence: every 30 min) plus a `## Soak run started ...` header
> and a `### Soak run ended ...` block per invocation. The operator fills
> the **Sign-Off** section below manually after each soak run ends.

## Pass Criteria (Phase 8 D-08 / OPS-06)

- [ ] ≥ 24 cycles over 48h
- [ ] Zero unhandled exceptions (all cycle errors caught by INFRA-08)
- [ ] Every non-empty cycle produced a `posts` row with `status='dry_run'`
      (empty-window cycles are allowed — they legitimately skip persistence)
- [ ] Every cycle emitted exactly one `cycle_summary` log line
- [ ] ≤ 2 cycles with `status='failed'` or `status='error'`

## How to Run

```bash
# Detached from operator host (preferred):
nohup docker compose run --rm app \
    uv run python scripts/soak_monitor.py --hours 48 --poll-minutes 30 \
    > soak.out 2>&1 &

# Foreground (Ctrl+C stops and writes final summary):
docker compose run --rm app \
    uv run python scripts/soak_monitor.py --hours 48 --poll-minutes 30
```

Exit codes: `0` on clean completion (reached `--hours` or Ctrl+C); `1` on
hard red-flag (`failed_last_48h > 2`).

---

## Operator Sign-Off (fill after each soak run ends)

| Field                    | Value |
| ------------------------ | ----- |
| Start ts (UTC)           |       |
| End ts (UTC)             |       |
| Final cycle count (48h)  |       |
| Failed cycles (48h)      |       |
| Dry-run posts (24h)      |       |
| Anomalies observed       |       |
| D-08 Decision            | [ ] PASS — proceed to cutover  /  [ ] FAIL — investigate |
| Operator                 |       |

---

## Raw poll log

<!-- soak_monitor.py appends below this line -->
