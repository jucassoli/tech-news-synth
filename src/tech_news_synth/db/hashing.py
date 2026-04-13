"""URL canonicalization + SHA256 article_hash (D-06).

Pure functions — no DB, no network, no logging. Phase 4 ingestion will call
``article_hash(url)`` to compute the unique key used by the
``articles.article_hash`` column (``CHAR(64) UNIQUE``).

Canonicalization rules:

* Lowercase ``scheme`` and ``netloc`` (host).
* Drop URL fragment (``#foo``).
* Strip tracking query params: every key starting with ``utm_`` plus the
  exact keys ``gclid`` and ``fbclid``.
* Sort remaining query params alphabetically (by key, then value).
* Preserve path case and trailing slash exactly as given.
* Default ports (``:80``/``:443``) are kept as-is — whatever :func:`urlsplit`
  produces. If future phases require port normalization they can layer it on.
* IDN/punycode hosts pass through unchanged — no explicit IDNA conversion.

``article_hash(url)`` returns the 64-char lowercase hex SHA256 digest of the
UTF-8 encoded canonical URL.
"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAM_PREFIXES: tuple[str, ...] = ("utm_",)
_TRACKING_PARAMS_EXACT: frozenset[str] = frozenset({"gclid", "fbclid"})


def canonicalize_url(url: str) -> str:
    """Return a deterministic canonical form of ``url``.

    See module docstring for the exact rules.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()

    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.startswith(_TRACKING_PARAM_PREFIXES)
        and k not in _TRACKING_PARAMS_EXACT
    ]
    query_pairs.sort(key=lambda kv: (kv[0], kv[1]))
    query = urlencode(query_pairs)

    # Drop fragment by passing "" as the fifth component.
    return urlunsplit((scheme, netloc, parts.path, query, ""))


def article_hash(url: str) -> str:
    """Return the 64-char lowercase hex SHA256 of ``canonicalize_url(url)``.

    Deterministic across Python versions and OS — hashlib + UTF-8 encoding are
    both standards-defined.
    """
    canon = canonicalize_url(url)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()
