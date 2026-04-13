"""Unit tests for URL canonicalization + SHA256 article_hash (D-06).

Pure-function helpers — no DB, no network, no mocks.
"""

from __future__ import annotations

import re

import pytest

from tech_news_synth.db.hashing import article_hash, canonicalize_url

# ---------------------------------------------------------------------------
# canonicalize_url — table-driven
# ---------------------------------------------------------------------------

# fmt: off
CANON_CASES = [
    # (label, input, expected)
    (
        "lowercase scheme+host, drop fragment, sort query",
        "HTTPS://Example.COM/Path?b=2&a=1#frag",
        "https://example.com/Path?a=1&b=2",
    ),
    (
        "strip all utm_* params",
        "https://x.com/a?utm_source=x&utm_medium=y&utm_campaign=z&q=1",
        "https://x.com/a?q=1",
    ),
    (
        "strip gclid and fbclid",
        "https://x.com/a?gclid=abc&fbclid=def&q=1",
        "https://x.com/a?q=1",
    ),
    (
        "preserve trailing slash",
        "https://x.com/a/",
        "https://x.com/a/",
    ),
    (
        "no query, no fragment — nop apart from host lowercase",
        "https://Example.com/Foo/Bar",
        "https://example.com/Foo/Bar",
    ),
    (
        "sort query params stably with duplicate keys",
        "https://x.com/a?b=2&a=2&a=1",
        "https://x.com/a?a=1&a=2&b=2",
    ),
    (
        "empty query string after stripping",
        "https://x.com/a?utm_source=x",
        "https://x.com/a",
    ),
    (
        "http scheme also lowercased",
        "HTTP://FOO.example.com/x",
        "http://foo.example.com/x",
    ),
]
# fmt: on


@pytest.mark.parametrize(("label", "url", "expected"), CANON_CASES)
def test_canonicalize_url(label: str, url: str, expected: str) -> None:
    assert canonicalize_url(url) == expected, label


def test_canonicalize_url_preserves_default_port_as_is() -> None:
    # Claude's choice per D-06 / Task 2 action: urlsplit preserves the explicit
    # port. We document (not strip) :443/:80 so that Phase 4 ingestion is aware.
    # If future phases need port normalization they can add it explicitly.
    assert canonicalize_url("https://x.com:443/a") == "https://x.com:443/a"
    assert canonicalize_url("http://x.com:80/a") == "http://x.com:80/a"


def test_canonicalize_url_passes_punycode_through() -> None:
    # Whatever urllib produces is accepted — no explicit IDN conversion.
    idn = "https://xn--bcher-kva.example/a"
    assert canonicalize_url(idn) == idn


def test_canonicalize_url_strips_surrounding_whitespace() -> None:
    assert canonicalize_url("  https://x.com/a  ") == "https://x.com/a"


# ---------------------------------------------------------------------------
# article_hash — SHA256 over canonical form
# ---------------------------------------------------------------------------

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def test_article_hash_returns_64_char_lowercase_hex() -> None:
    h = article_hash("https://example.com/a")
    assert _HEX64.match(h), f"not 64-char lowercase hex: {h!r}"


def test_article_hash_deterministic_across_calls() -> None:
    url = "https://example.com/article"
    assert article_hash(url) == article_hash(url)


def test_article_hash_collapses_urls_that_canonicalize_equal() -> None:
    # Tracking params and fragment do not affect identity.
    a = article_hash("https://Example.com/path?b=2&a=1#frag")
    b = article_hash("https://example.com/path?utm_source=x&a=1&b=2")
    assert a == b


def test_article_hash_distinguishes_distinct_canonical_urls() -> None:
    assert article_hash("https://x.com/a") != article_hash("https://x.com/b")


def test_article_hash_stable_value_known_vector() -> None:
    # Stability across Python versions — SHA256 over "https://example.com/a"
    # (the canonical form of the same input) must be deterministic forever.
    import hashlib

    expected = hashlib.sha256(b"https://example.com/a").hexdigest()
    assert article_hash("https://example.com/a") == expected
