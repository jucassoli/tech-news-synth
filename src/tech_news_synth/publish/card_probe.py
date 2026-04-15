"""Best-effort source URL card probe for observability.

The X API does not provide a reliable pre-publication "card will render"
verdict. We approximate it by checking common social metadata on the source
page and expose the result as telemetry only.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from tech_news_synth.ingest.http import build_http_client, fetch_with_retry


def probe_source_card(source_url: str) -> dict[str, object]:
    """Return a heuristic view of whether the source likely renders a card."""
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


__all__ = ["probe_source_card"]
