"""Offline link-discovery primitives for allowlisted v2 sources."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from research_pipeline.registry import validate_registry


class DiscoveryPolicyError(ValueError):
    """Raised when discovery is attempted outside the configured trust boundary."""


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.hrefs.append(value)
                break


def normalize_url(base_url: str, href: str) -> str | None:
    """Resolve a link, strip fragments, and return a stable HTTP(S) URL."""
    if not isinstance(href, str) or not href.strip():
        return None

    joined = urljoin(base_url, href.strip())
    parsed = urlsplit(joined)
    scheme = parsed.scheme.lower()

    if scheme not in {"http", "https"} or not parsed.hostname:
        return None

    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def _source_by_id(registry: dict, source_id: str) -> dict:
    for source in registry["sources"]:
        if source.get("id") == source_id:
            return source
    raise DiscoveryPolicyError(f"Unknown source id: {source_id}")


def is_allowed_candidate(source: dict, url: str) -> bool:
    """Return whether a normalized candidate URL stays inside a source boundary."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    domains = {str(domain).lower() for domain in source.get("domains", [])}

    if parsed.scheme != "https":
        return False
    if source.get("enabled") is not True or source.get("official") is not True:
        return False
    if host not in domains:
        return False

    return any(url.startswith(prefix) for prefix in source.get("allowed_url_prefixes", []))


def discover_links(
    registry: dict,
    source_id: str,
    entrypoint: str,
    html: str,
    *,
    base_url: str | None = None,
) -> list[str]:
    """Extract unique, allowlisted links from one configured source entrypoint.

    ``entrypoint`` is the authorization origin and must be configured in the registry.
    ``base_url`` may be supplied after an allowlisted HTTP redirect so relative links are
    resolved against the page that was actually returned.
    """
    validate_registry(registry)
    source = _source_by_id(registry, source_id)

    if entrypoint not in source.get("entrypoints", []):
        raise DiscoveryPolicyError(
            f"Entrypoint is not configured for {source_id}: {entrypoint}"
        )

    normalized_entrypoint = normalize_url(entrypoint, entrypoint)
    resolution_base = normalize_url(base_url or entrypoint, base_url or entrypoint)
    if resolution_base is None:
        raise DiscoveryPolicyError(f"Invalid discovery base URL: {base_url}")
    if resolution_base != normalized_entrypoint and not is_allowed_candidate(
        source, resolution_base
    ):
        raise DiscoveryPolicyError(
            f"Discovery base URL is outside source policy: {resolution_base}"
        )

    parser = _LinkParser()
    parser.feed(html)

    candidates: set[str] = set()
    for href in parser.hrefs:
        candidate = normalize_url(resolution_base, href)
        if candidate is None or candidate in {normalized_entrypoint, resolution_base}:
            continue
        if is_allowed_candidate(source, candidate):
            candidates.add(candidate)

    return sorted(candidates)
