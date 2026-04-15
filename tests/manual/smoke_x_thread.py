#!/usr/bin/env python3
"""Manual smoke test: publish a real news thread using the app pipeline.

Usage:

    uv run python tests/manual/smoke_x_thread.py --arm-live-post

This script selects a REAL news item from the live pipeline, synthesizes the
lead with the existing app functions, builds a 2- or 3-post thread, and
publishes it to @ByteRelevant so the operator can inspect the result on X.
It intentionally bypasses the scheduler and does not persist a ``posts`` row;
it is an operator tool kept under ``tests/manual``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import anthropic
from bs4 import BeautifulSoup

from tech_news_synth.cluster.models import SelectionResult
from tech_news_synth.cluster.orchestrator import run_clustering
from tech_news_synth.config import Settings, load_settings
from tech_news_synth.db.articles import get_articles_by_ids
from tech_news_synth.db.models import Article
from tech_news_synth.db.run_log import finish_cycle, start_cycle
from tech_news_synth.db.session import SessionLocal, init_engine
from tech_news_synth.ids import new_cycle_id
from tech_news_synth.ingest.http import build_http_client, fetch_with_retry
from tech_news_synth.ingest.orchestrator import run_ingest
from tech_news_synth.ingest.sources_config import SourcesConfig, load_sources_config
from tech_news_synth.logging import configure_logging
from tech_news_synth.publish.client import build_x_client, post_tweet
from tech_news_synth.synth.article_picker import pick_articles_for_synthesis
from tech_news_synth.synth.charcount import weighted_len
from tech_news_synth.synth.client import call_haiku
from tech_news_synth.synth.hashtags import HashtagAllowlist, load_hashtag_allowlist
from tech_news_synth.synth.orchestrator import run_synthesis
from tech_news_synth.synth.prompt import build_user_prompt
from tech_news_synth.synth.truncate import word_boundary_truncate
from tech_news_synth.synth.url_picker import pick_source_url

CTA = "Siga a thread 🧵👇"
REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKER_REEXEC_ENV = "SMOKE_X_THREAD_IN_DOCKER"
_DISABLE_DOCKER_REEXEC_ENV = "SMOKE_X_THREAD_DISABLE_DOCKER_REEXEC"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="smoke_x_thread",
        description=(
            "Publish a real demo thread to @ByteRelevant using a live news "
            "item from the pipeline. Requires --arm-live-post."
        ),
    )
    parser.add_argument(
        "--arm-live-post",
        action="store_true",
        help="REQUIRED to actually publish the demo thread.",
    )
    parser.add_argument(
        "--parts",
        type=int,
        choices=(2, 3),
        default=3,
        help="How many posts to publish in the demo thread (default: 3).",
    )
    return parser.parse_args()


def _load_runtime() -> tuple[Settings, SourcesConfig, HashtagAllowlist]:
    settings = load_settings()
    configure_logging(settings)
    init_engine(settings)
    sources_config = load_sources_config(Path(settings.sources_config_path))
    hashtag_allowlist = load_hashtag_allowlist(Path(settings.hashtags_config_path))
    return settings, sources_config, hashtag_allowlist


def _should_delegate_to_docker() -> bool:
    """Run inside a one-off container when invoked from the host machine.

    The smoke depends on container-style defaults:
      - Postgres host is usually ``postgres`` on the compose bridge
      - default config/log paths live under ``/app`` and ``/data``

    When the operator runs this directly on macOS/Linux, those assumptions do
    not hold. Re-execing inside a short-lived container makes the manual test
    behave like production without forcing the operator to remember overrides.
    """
    if os.environ.get(_DOCKER_REEXEC_ENV) == "1":
        return False
    if os.environ.get(_DISABLE_DOCKER_REEXEC_ENV) == "1":
        return False
    if Path("/.dockerenv").exists():
        return False
    return True


def _delegate_to_docker() -> int:
    print(
        "[smoke_x_thread] Host execution detected; re-running inside an ephemeral "
        "container on the compose network.",
        file=sys.stderr,
    )
    subprocess.run(
        ["docker", "compose", "up", "-d", "postgres"],
        cwd=REPO_ROOT,
        check=True,
    )

    inner_script = (
        "python -m pip install -q uv && "
        "uv run python - <<'PY'\n"
        "from tech_news_synth.config import load_settings\n"
        "from tech_news_synth.logging import configure_logging\n"
        "from tech_news_synth.db.session import init_engine\n"
        "from tech_news_synth.db.migrations import run_migrations\n"
        "settings = load_settings()\n"
        "configure_logging(settings)\n"
        "init_engine(settings)\n"
        "run_migrations()\n"
        "PY\n"
        "uv run python tests/manual/smoke_x_thread.py --arm-live-post"
    )

    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        "tech-news-synth_default",
        "--env-file",
        ".env",
        "-e",
        f"{_DOCKER_REEXEC_ENV}=1",
        "-e",
        "LOG_DIR=/tmp/tech-news-synth-logs",
        "-e",
        "PAUSED_MARKER_PATH=/tmp/tech-news-synth-paused",
        "-e",
        "SOURCES_CONFIG_PATH=/workspace/config/sources.yaml",
        "-e",
        "HASHTAGS_CONFIG_PATH=/workspace/config/hashtags.yaml",
        "-e",
        "POSTGRES_HOST=postgres",
        "-v",
        f"{REPO_ROOT}:/workspace",
        "-w",
        "/workspace",
        "python:3.12-slim",
        "bash",
        "-lc",
        inner_script,
    ]
    return subprocess.run(cmd, cwd=REPO_ROOT).returncode


def _selected_articles(
    session,
    selection: SelectionResult,
    sources_config: SourcesConfig,
) -> tuple[list[Article], str]:
    if selection.winner_cluster_id is not None:
        ids = selection.winner_article_ids or []
        articles_all = get_articles_by_ids(session, ids)
        selected = pick_articles_for_synthesis(articles_all, max_articles=5)
        source_weights = {s.name: getattr(s, "weight", 1.0) for s in sources_config.sources}
        source_url = pick_source_url(selected, source_weights)
        return selected, source_url

    article = session.get(Article, selection.fallback_article_id)
    if article is None:
        raise ValueError(
            f"fallback article {selection.fallback_article_id} not found for manual thread"
        )
    return [article], article.url


def _probable_card(source_url: str) -> dict[str, object]:
    """Best-effort check for social-card metadata.

    This is heuristic only; X may still render differently when the post goes
    live. We use it for operator visibility, not as a hard gate.
    """
    client = build_http_client()
    try:
        response = fetch_with_retry(client, "GET", source_url)
        html = response.text
    finally:
        client.close()

    soup = BeautifulSoup(html, "html.parser")
    metas: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        key = tag.get("property") or tag.get("name")
        value = tag.get("content")
        if key and value:
            metas[key.lower()] = value.strip()

    image = metas.get("twitter:image") or metas.get("og:image")
    card = metas.get("twitter:card")
    return {
        "probable_card": bool(image or card),
        "twitter_card": card,
        "image": image,
    }


def _thread_system_prompt(parts: int) -> str:
    return (
        "Você escreve threads curtas e jornalísticas para a conta @ByteRelevant no X.\n"
        "Tom: jornalístico, claro, neutro, em português brasileiro.\n"
        "Regras:\n"
        "- Use APENAS as informações das fontes fornecidas.\n"
        "- NÃO invente fatos, datas, nomes ou métricas.\n"
        "- NÃO use markdown, aspas de abertura ou listas.\n"
        "- Retorne APENAS JSON válido.\n"
        f"- Gere exatamente {parts - 1} objetos no array replies.\n"
        "- Cada reply deve soar como continuação natural da thread.\n"
        "- O último reply deve fechar a história explicando por que isso importa.\n"
        'Formato exato: {"replies":["texto 1","texto 2"]}'
    )


def _generate_replies(
    *,
    anthropic_client: anthropic.Anthropic,
    settings: Settings,
    selected: list[Article],
    lead_body: str,
    parts: int,
) -> list[str]:
    prompt = (
        f"{build_user_prompt(selected)}\n\n"
        f"Lead já usado no primeiro post:\n{lead_body}\n\n"
        f"Gere os próximos {parts - 1} posts da thread. "
        "Os replies devem aprofundar a notícia sem repetir a abertura. "
        "Cada reply precisa caber sozinho em um post do X. "
        "Não inclua URL, hashtag nem CTA."
    )
    text, _in_tok, _out_tok = call_haiku(
        anthropic_client,
        _thread_system_prompt(parts),
        prompt,
        settings.synthesis_max_tokens * 2,
    )
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    if "{" in cleaned and "}" in cleaned:
        cleaned = cleaned[cleaned.find("{") : cleaned.rfind("}") + 1]
    data = json.loads(cleaned)
    replies = data["replies"]
    if not isinstance(replies, list) or len(replies) != parts - 1:
        raise ValueError(f"invalid replies payload from model: {text}")
    return [str(item).strip() for item in replies]


def _compose_root(body_text: str, source_url: str) -> str:
    url_weight = 23
    cta_block = CTA
    overhead = weighted_len(cta_block) + url_weight + 4  # blank lines/spaces
    budget = max(0, 280 - overhead)
    lead = word_boundary_truncate(body_text, budget).strip()
    return f"{lead}\n\n{cta_block}\n\n{source_url}"


def _compose_reply(text: str, *, suffix: str = "") -> str:
    reply = text.strip()
    if suffix:
        reply = f"{reply}\n\n{suffix}"
    if weighted_len(reply) <= 280:
        return reply
    budget = 280 - (weighted_len(suffix) + 2 if suffix else 0)
    body = word_boundary_truncate(text.strip(), max(0, budget))
    return f"{body}\n\n{suffix}" if suffix else body


def main() -> int:
    args = _parse_args()
    if not args.arm_live_post:
        print(
            "REFUSING: pass --arm-live-post to publish a real demo thread.",
            file=sys.stderr,
        )
        print(
            "This script posts a REAL thread to @ByteRelevant and leaves it live.",
            file=sys.stderr,
        )
        return 2
    if _should_delegate_to_docker():
        return _delegate_to_docker()

    settings, sources_config, hashtag_allowlist = _load_runtime()
    anthropic_client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key.get_secret_value()
    )
    x_client = build_x_client(settings)
    cycle_id = new_cycle_id()

    with SessionLocal() as session:
        start_cycle(session, cycle_id)
        session.commit()

        http_client = build_http_client()
        try:
            ingest_counts = run_ingest(session, sources_config, http_client, settings)
            selection = run_clustering(session, cycle_id, settings, sources_config)
            if (
                selection.winner_cluster_id is None
                and selection.fallback_article_id is None
            ):
                finish_cycle(
                    session,
                    cycle_id,
                    status="ok",
                    counts={**ingest_counts, "publish_status": "empty"},
                    notes="manual smoke_x_thread: empty selection",
                )
                session.commit()
                print("No article selected from the live pipeline.", file=sys.stderr)
                return 1

            synthesis = run_synthesis(
                session,
                cycle_id,
                selection,
                settings,
                sources_config,
                anthropic_client,
                hashtag_allowlist,
                persist=False,
            )
            selected, source_url = _selected_articles(session, selection, sources_config)
            card_info = _probable_card(source_url)

            root = _compose_root(synthesis.body_text, source_url)
            replies = _generate_replies(
                anthropic_client=anthropic_client,
                settings=settings,
                selected=selected,
                lead_body=synthesis.body_text,
                parts=args.parts,
            )
            if synthesis.hashtags:
                replies[-1] = _compose_reply(
                    replies[-1],
                    suffix=" ".join(synthesis.hashtags),
                )
            else:
                replies[-1] = _compose_reply(replies[-1])
            replies = [_compose_reply(text) for text in replies[:-1]] + [replies[-1]]

            posted: list[dict[str, object]] = []
            reply_to_id: str | None = None
            thread_posts = [root, *replies]
            for idx, text in enumerate(thread_posts, start=1):
                outcome = post_tweet(
                    x_client,
                    text,
                    in_reply_to_tweet_id=reply_to_id,
                )
                if outcome.status != "posted" or outcome.tweet_id is None:
                    finish_cycle(
                        session,
                        cycle_id,
                        status="error",
                        counts={
                            **ingest_counts,
                            **selection.counts_patch,
                            **synthesis.counts_patch,
                            "publish_status": "failed",
                        },
                        notes=f"manual smoke_x_thread failed at part {idx}",
                    )
                    session.commit()
                    print(
                        json.dumps(
                            {
                                "status": "failed",
                                "failed_part": idx,
                                "reply_to_tweet_id": reply_to_id,
                                "error_detail": outcome.error_detail,
                            },
                            ensure_ascii=False,
                        ),
                        file=sys.stderr,
                    )
                    return 1

                reply_to_id = outcome.tweet_id
                posted.append(
                    {
                        "index": idx,
                        "tweet_id": outcome.tweet_id,
                        "url": f"https://x.com/ByteRelevant/status/{outcome.tweet_id}",
                        "elapsed_ms": outcome.elapsed_ms,
                        "text": text,
                    }
                )

            finish_cycle(
                session,
                cycle_id,
                status="ok",
                counts={
                    **ingest_counts,
                    **selection.counts_patch,
                    **synthesis.counts_patch,
                    "publish_status": "posted",
                    "tweet_id": posted[0]["tweet_id"],
                },
                notes="manual smoke_x_thread",
            )
            session.commit()
        finally:
            http_client.close()

    summary = {
        "status": "posted",
        "cycle_id": cycle_id,
        "parts": len(posted),
        "root_tweet_id": posted[0]["tweet_id"],
        "root_url": posted[0]["url"],
        "selected_titles": [a.title for a in selected],
        "source_url": source_url,
        "card_probe": card_info,
        "tweets": posted,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
