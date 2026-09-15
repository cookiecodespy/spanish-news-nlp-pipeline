"""Conservative HTTP helpers for live v2 source discovery.

The network layer deliberately does not crawl. It fetches one already-authorized URL at
a time, follows redirects manually, validates every hop, and enforces hard response-size
and content-type limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from research_pipeline.discovery import is_allowed_candidate, normalize_url

USER_AGENT = (
    "agent-research-pipeline/0.1 "
    "(+https://github.com/cookiecodespy/spanish-news-nlp-pipeline)"
)
TIMEOUT = (5, 15)
MAX_REDIRECTS = 4
MAX_HTML_BYTES = 4 * 1024 * 1024
MAX_ROBOTS_BYTES = 512 * 1024
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
HTML_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}


class NetworkPolicyError(RuntimeError):
    """Raised when a response violates the live-discovery network policy."""


@dataclass(frozen=True)
class FetchedText:
    url: str
    text: str
    content_type: str
    status_code: int
    bytes_read: int


def _normalized_entrypoints(source: dict) -> set[str]:
    return {
        normalized
        for entrypoint in source.get("entrypoints", [])
        if (normalized := normalize_url(entrypoint, entrypoint)) is not None
    }


def is_allowed_fetch_url(source: dict, url: str) -> bool:
    """Allow configured entrypoints or normal allowlisted candidate URLs."""
    normalized = normalize_url(url, url)
    if normalized is None:
        return False
    if source.get("enabled") is not True or source.get("official") is not True:
        return False
    return normalized in _normalized_entrypoints(source) or is_allowed_candidate(
        source, normalized
    )


def robots_url_for(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))


def _same_allowed_host(source: dict, url: str) -> bool:
    parsed = urlsplit(url)
    domains = {str(domain).lower() for domain in source.get("domains", [])}
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in domains


def _robots_hop_allowed(source: dict, url: str) -> bool:
    parsed = urlsplit(url)
    return _same_allowed_host(source, url) and parsed.path == "/robots.txt"


def _content_type(response) -> str:
    raw = response.headers.get("Content-Type", "")
    return raw.split(";", 1)[0].strip().lower()


def _close(response) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()


def _read_limited(response, max_bytes: int) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            declared = int(content_length)
        except ValueError:
            declared = None
        if declared is not None and declared > max_bytes:
            raise NetworkPolicyError(
                f"response too large: declared {declared} bytes, limit {max_bytes}"
            )

    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise NetworkPolicyError(
                f"response too large while streaming: limit {max_bytes} bytes"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _decode(response, payload: bytes) -> str:
    encoding = getattr(response, "encoding", None) or "utf-8"
    try:
        return payload.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


def _request(
    url: str,
    *,
    request_get: Callable = requests.get,
):
    try:
        return request_get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
            },
            timeout=TIMEOUT,
            stream=True,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise NetworkPolicyError(f"network request failed for {url}: {exc}") from exc


def fetch_html(
    source: dict,
    url: str,
    *,
    request_get: Callable = requests.get,
    max_bytes: int = MAX_HTML_BYTES,
) -> FetchedText:
    """Fetch one authorized HTML URL while validating every redirect hop."""
    current = normalize_url(url, url)
    if current is None or not is_allowed_fetch_url(source, current):
        raise NetworkPolicyError(f"URL is outside source fetch policy: {url}")

    for redirect_count in range(MAX_REDIRECTS + 1):
        response = _request(current, request_get=request_get)

        if response.status_code in REDIRECT_STATUSES:
            if redirect_count >= MAX_REDIRECTS:
                _close(response)
                raise NetworkPolicyError("too many redirects")
            location = response.headers.get("Location")
            if not location:
                _close(response)
                raise NetworkPolicyError("redirect response missing Location header")
            target = normalize_url(current, urljoin(current, location))
            if target is None or not is_allowed_fetch_url(source, target):
                _close(response)
                raise NetworkPolicyError(
                    f"redirect target is outside source fetch policy: {location}"
                )
            _close(response)
            current = target
            continue

        if not 200 <= response.status_code < 300:
            status = response.status_code
            _close(response)
            raise NetworkPolicyError(f"unexpected HTTP status {status} for {current}")

        content_type = _content_type(response)
        if content_type not in HTML_CONTENT_TYPES:
            _close(response)
            raise NetworkPolicyError(
                f"unexpected content type for discovery page: {content_type or '<missing>'}"
            )

        try:
            payload = _read_limited(response, max_bytes)
            text = _decode(response, payload)
        finally:
            _close(response)

        return FetchedText(
            url=current,
            text=text,
            content_type=content_type,
            status_code=response.status_code,
            bytes_read=len(payload),
        )

    raise NetworkPolicyError("redirect loop exhausted")


def fetch_robots_txt(
    source: dict,
    entrypoint: str,
    *,
    request_get: Callable = requests.get,
    max_bytes: int = MAX_ROBOTS_BYTES,
) -> str | None:
    """Fetch robots.txt for an entrypoint host.

    A 404/410 means no robots file is present and returns ``None``. Other failures are
    treated conservatively as errors rather than silently bypassing the policy.
    """
    if not is_allowed_fetch_url(source, entrypoint):
        raise NetworkPolicyError(f"Entrypoint is outside source fetch policy: {entrypoint}")

    current = robots_url_for(entrypoint)
    if not _robots_hop_allowed(source, current):
        raise NetworkPolicyError(f"robots.txt URL is outside source domains: {current}")

    for redirect_count in range(MAX_REDIRECTS + 1):
        response = _request(current, request_get=request_get)

        if response.status_code in REDIRECT_STATUSES:
            if redirect_count >= MAX_REDIRECTS:
                _close(response)
                raise NetworkPolicyError("too many robots.txt redirects")
            location = response.headers.get("Location")
            if not location:
                _close(response)
                raise NetworkPolicyError("robots.txt redirect missing Location header")
            target = normalize_url(current, urljoin(current, location))
            if target is None or not _robots_hop_allowed(source, target):
                _close(response)
                raise NetworkPolicyError(
                    f"robots.txt redirect target is outside policy: {location}"
                )
            _close(response)
            current = target
            continue

        if response.status_code in {404, 410}:
            _close(response)
            return None
        if not 200 <= response.status_code < 300:
            status = response.status_code
            _close(response)
            raise NetworkPolicyError(f"unexpected robots.txt HTTP status {status}")

        content_type = _content_type(response)
        if content_type and not content_type.startswith("text/"):
            _close(response)
            raise NetworkPolicyError(
                f"unexpected robots.txt content type: {content_type}"
            )

        try:
            payload = _read_limited(response, max_bytes)
            text = _decode(response, payload)
        finally:
            _close(response)
        return text

    raise NetworkPolicyError("robots.txt redirect loop exhausted")
