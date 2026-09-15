"""Live discovery from explicitly allowlisted official source entrypoints.

This module is intentionally shallow: it fetches configured index/entrypoint pages and
returns eligible links. It does not recursively crawl or download discovered documents.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from urllib import robotparser

import requests

from research_pipeline.discovery import DiscoveryPolicyError, discover_links
from research_pipeline.network import (
    USER_AGENT,
    fetch_html,
    fetch_robots_txt,
    robots_url_for,
)
from research_pipeline.registry import DEFAULT_REGISTRY_PATH, load_registry

DEFAULT_DELAY_S = 1.0


@dataclass(frozen=True)
class DiscoveryResult:
    source_id: str
    entrypoint: str
    final_url: str
    candidate_count: int
    candidates: list[str]


def _source_by_id(registry: dict, source_id: str) -> dict:
    for source in registry["sources"]:
        if source.get("id") == source_id:
            return source
    raise DiscoveryPolicyError(f"Unknown source id: {source_id}")


def robots_allows(robots_text: str | None, entrypoint: str) -> bool:
    """Evaluate one entrypoint against already-fetched robots.txt content."""
    if robots_text is None:
        return True

    rules = robotparser.RobotFileParser()
    rules.set_url(robots_url_for(entrypoint))
    rules.parse(robots_text.splitlines())
    return rules.can_fetch(USER_AGENT, entrypoint)


def discover_entrypoint_live(
    registry: dict,
    source_id: str,
    entrypoint: str,
    *,
    request_get: Callable = requests.get,
    robots_text: str | None | object = ...,
    delay_s: float = DEFAULT_DELAY_S,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> DiscoveryResult:
    """Fetch one configured entrypoint and return allowlisted candidate URLs."""
    source = _source_by_id(registry, source_id)
    if source.get("enabled") is not True or source.get("official") is not True:
        raise DiscoveryPolicyError(f"Source is not enabled and official: {source_id}")
    if entrypoint not in source.get("entrypoints", []):
        raise DiscoveryPolicyError(
            f"Entrypoint is not configured for {source_id}: {entrypoint}"
        )

    if robots_text is ...:
        robots_text = fetch_robots_txt(source, entrypoint, request_get=request_get)
        if delay_s > 0:
            sleep_fn(delay_s)

    if not robots_allows(robots_text, entrypoint):
        raise DiscoveryPolicyError(f"robots.txt disallows entrypoint: {entrypoint}")

    fetched = fetch_html(source, entrypoint, request_get=request_get)
    candidates = discover_links(
        registry,
        source_id,
        entrypoint,
        fetched.text,
        base_url=fetched.url,
    )
    return DiscoveryResult(
        source_id=source_id,
        entrypoint=entrypoint,
        final_url=fetched.url,
        candidate_count=len(candidates),
        candidates=candidates,
    )


def discover_source_live(
    registry: dict,
    source_id: str,
    *,
    request_get: Callable = requests.get,
    delay_s: float = DEFAULT_DELAY_S,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> list[DiscoveryResult]:
    """Discover all configured entrypoints for one source, sequentially.

    robots.txt is fetched once per entrypoint host and reused for other entrypoints on
    that host during the same run.
    """
    source = _source_by_id(registry, source_id)
    if source.get("enabled") is not True or source.get("official") is not True:
        raise DiscoveryPolicyError(f"Source is not enabled and official: {source_id}")

    robots_cache: dict[str, str | None] = {}
    results: list[DiscoveryResult] = []

    for index, entrypoint in enumerate(source.get("entrypoints", [])):
        robots_url = robots_url_for(entrypoint)
        if robots_url not in robots_cache:
            robots_cache[robots_url] = fetch_robots_txt(
                source, entrypoint, request_get=request_get
            )
            if delay_s > 0:
                sleep_fn(delay_s)

        result = discover_entrypoint_live(
            registry,
            source_id,
            entrypoint,
            request_get=request_get,
            robots_text=robots_cache[robots_url],
            delay_s=0,
            sleep_fn=sleep_fn,
        )
        results.append(result)

        if delay_s > 0 and index < len(source.get("entrypoints", [])) - 1:
            sleep_fn(delay_s)

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="registry source id")
    parser.add_argument(
        "--registry", type=Path, default=DEFAULT_REGISTRY_PATH, help="registry JSON path"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_S,
        help="polite delay in seconds between requests (default: 1.0)",
    )
    args = parser.parse_args()

    if args.delay < 0:
        parser.error("--delay must be >= 0")

    registry = load_registry(args.registry)
    try:
        results = discover_source_live(registry, args.source, delay_s=args.delay)
    except (DiscoveryPolicyError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    payload = {
        "ok": True,
        "source_id": args.source,
        "entrypoints": [asdict(result) for result in results],
        "candidate_count": sum(result.candidate_count for result in results),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
