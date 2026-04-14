# Orphaned Pending Posts Runbook

Triggered by structlog event `orphaned_pending`. The row(s) are marked
`failed` automatically by `cleanup_stale_pending` at the top of the next
cycle (default cutoff: 5 minutes after the original attempt).

## Why this happens

Phase 7 publishes in two phases:
1. `tweepy.Client.create_tweet` -> X API call
2. `UPDATE posts SET status='posted', tweet_id=...` -> DB commit

A container crash or lost DB connection between (1) and (2) leaves a
`pending` row even though the tweet may have been posted successfully.
X API v2 has no idempotency-key header (unlike Stripe), so we cannot
auto-recover: the guard surfaces the suspect row to the operator.

## Investigation

1. Visit <https://x.com/ByteRelevant> — does a tweet matching the row's
   `synthesized_text` exist on the timeline?
2. If **YES** (the tweet was posted but DB UPDATE failed), manually
   recover:

   ```sql
   UPDATE posts
      SET status='posted',
          tweet_id='<tweet_id_from_x_url>',
          posted_at='<iso_timestamp_from_x>',
          error_detail=NULL
    WHERE id=<row_id>;
   ```

3. If **NO** (no such tweet on the timeline), leave the row as `failed`.
   The next cycle will synthesize and publish fresh content. The 48h
   anti-repetition window may skip this cluster if it reappears, which
   is the correct behavior — prevents double-posting if the tweet was
   actually sent.

## Verifying cleanup ran

```sql
SELECT id, status, error_detail
  FROM posts
 WHERE error_detail LIKE '%orphaned_pending_row%'
 ORDER BY created_at DESC
 LIMIT 10;
```
