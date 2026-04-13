"""Shared httpx.Client + tenacity retry wrapper (D-06, INGEST-03, T-04-03/04).

One ``httpx.Client`` per cycle: carries the pinned ``ByteRelevant/0.1``
User-Agent, follows redirects, uses HTTP/2, default timeout 30s connect=5s
(fetchers override per request via ``fetch_with_retry(..., timeout=)``).

``fetch_with_retry`` retries exactly 3 attempts with exponential backoff
1→16s. Retries on 5xx + 429 (raised internally as ``_RetryableHTTP``) and
on ``httpx.TransportError`` (timeouts, connection errors). 4xx is NEVER
retried. ``304 Not Modified`` is returned to the caller unchanged
(conditional GET semantics per D-14).
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

USER_AGENT = "ByteRelevant/0.1 (+https://x.com/ByteRelevant)"
_RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class _RetryableHTTP(httpx.HTTPStatusError):
    """Internal — raised so tenacity sees the right exception class.

    Subclass of ``httpx.HTTPStatusError`` so it carries ``request`` +
    ``response``. Not part of the public API.
    """


def build_http_client(*, default_timeout_sec: float = 30.0) -> httpx.Client:
    """Build the per-cycle shared client.

    Caller MUST close the client in a ``try/finally`` (D-06). The default
    timeout is a ceiling; each fetcher overrides per-request via
    ``fetch_with_retry(..., timeout=httpx.Timeout(source.timeout_sec, connect=5.0))``.
    """
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        http2=True,
        timeout=httpx.Timeout(default_timeout_sec, connect=5.0),
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    retry=retry_if_exception_type((_RetryableHTTP, httpx.TransportError)),
    reraise=True,
)
def fetch_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    timeout: httpx.Timeout | float | None = None,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Single HTTP call wrapped by tenacity (D-06).

    - Retries on 5xx + 429 (raised as :class:`_RetryableHTTP`).
    - Retries on :exc:`httpx.TransportError` (timeouts, connection errors).
    - Does NOT retry on 4xx (returned to caller as-is).
    - 304 returned to caller unchanged (conditional GET — D-14).
    """
    req_kwargs: dict[str, Any] = {"headers": headers or {}, **kwargs}
    if timeout is not None:
        req_kwargs["timeout"] = timeout
    response = client.request(method, url, **req_kwargs)
    if response.status_code in _RETRY_STATUS_CODES:
        raise _RetryableHTTP(
            f"retryable status {response.status_code}",
            request=response.request,
            response=response,
        )
    return response


__all__ = ["USER_AGENT", "build_http_client", "fetch_with_retry"]
