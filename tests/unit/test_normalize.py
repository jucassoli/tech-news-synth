"""Unit tests for tech_news_synth.ingest.normalize (INGEST-06, T-04-09)."""

from __future__ import annotations

from datetime import UTC, datetime, timezone

from tech_news_synth.db.hashing import article_hash, canonicalize_url
from tech_news_synth.ingest.normalize import build_article_row, strip_html


# ---------------------------------------------------------------------------
# strip_html
# ---------------------------------------------------------------------------
def test_strip_html_removes_tags_and_script():
    html = "<p>Hello <b>world</b><script>alert(1)</script></p>"
    assert strip_html(html) == "Hello world"


def test_strip_html_removes_style_content():
    html = "<p>Visible<style>.x{color:red}</style></p>"
    assert "color" not in strip_html(html)
    assert "Visible" in strip_html(html)


def test_strip_html_truncates_to_1000():
    html = "<p>" + ("x" * 5000) + "</p>"
    result = strip_html(html)
    assert len(result) == 1000


def test_strip_html_empty_input():
    assert strip_html("") == ""
    assert strip_html(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# build_article_row
# ---------------------------------------------------------------------------
def test_build_article_row_delegates_to_phase2_hashing():
    fetched = datetime(2026, 4, 13, 12, 0, tzinfo=UTC)
    row = build_article_row(
        source_name="techcrunch",
        raw_title="  A headline  ",
        raw_summary_or_html="<p>Body</p>",
        url="https://techcrunch.com/x?utm_source=foo&id=1#frag",
        published_at=datetime(2026, 4, 13, 10, 0, tzinfo=UTC),
        fetched_at=fetched,
    )
    raw_url = "https://techcrunch.com/x?utm_source=foo&id=1#frag"
    assert row.canonical_url == canonicalize_url(raw_url)
    assert row.article_hash == article_hash(raw_url)
    assert row.title == "A headline"
    assert row.summary == "Body"


def test_build_article_row_published_at_defaults_to_fetched_at():
    fetched = datetime(2026, 4, 13, 12, 0, tzinfo=UTC)
    row = build_article_row(
        source_name="s",
        raw_title="t",
        raw_summary_or_html="",
        url="https://example.com/a",
        published_at=None,
        fetched_at=fetched,
    )
    assert row.published_at == fetched


def test_build_article_row_naive_published_at_treated_as_utc():
    fetched = datetime(2026, 4, 13, 12, 0, tzinfo=UTC)
    naive = datetime(2026, 4, 13, 10, 0)  # no tz
    row = build_article_row(
        source_name="s",
        raw_title="t",
        raw_summary_or_html="",
        url="https://example.com/a",
        published_at=naive,
        fetched_at=fetched,
    )
    assert row.published_at.tzinfo is not None
    assert row.published_at.utcoffset().total_seconds() == 0
    assert row.published_at.replace(tzinfo=None) == naive


def test_build_article_row_aware_non_utc_converted():
    from datetime import timedelta

    fetched = datetime(2026, 4, 13, 12, 0, tzinfo=UTC)
    # 10:00 in UTC-3 is 13:00 UTC
    tz = timezone(timedelta(hours=-3))
    pub = datetime(2026, 4, 13, 10, 0, tzinfo=tz)
    row = build_article_row(
        source_name="s",
        raw_title="t",
        raw_summary_or_html="",
        url="https://example.com/a",
        published_at=pub,
        fetched_at=fetched,
    )
    assert row.published_at.tzinfo is not None
    # 10:00 UTC-3 = 13:00 UTC
    assert row.published_at.hour == 13
