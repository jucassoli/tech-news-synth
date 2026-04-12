# tech-news-synth

Automated agent that collects tech news from multiple RSS sources
every 2 hours, clusters related stories, and publishes an
LLM-synthesized summary of the top story to X (@ByteRelevant).

## Stack
- Python 3.11+
- Anthropic Claude (Haiku) for synthesis
- tweepy for X API
- SQLite for dedupe/history
- cron for scheduling

## Status
🚧 Work in progress