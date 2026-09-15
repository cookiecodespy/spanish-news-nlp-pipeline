"""Phase 2A exact-byte HTML ingestion for previously discovered official-source URLs.

This module preserves transport evidence only. ``CHANGED`` means the fetched HTML bytes
changed relative to the previous successful observation; it does not claim that the
research content changed semantically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import requests

from research_pipeline.discovery_state import DEFAULT_STATE_PATH, connect_state
from research_pipeline.ingestion_state import (
    IngestionStateError,
    candidate_urls,
    ensure_ingestion_schema,
    record_failure,
    record_success,
    require_discovered_candidate,
)
from research_pipeline.live_discovery import (
    DEFAULT_DELAY_S,
    robots_allows,
    robots_crawl_delay,
)
from research_pipeline.network import (
    NetworkPolicyError,
    fetch_html,
    fetch_robots_txt,
    is_allowed_fetch_url,
    robots_url_for,
)
from research_pipeline.registry import DEFAULT_REGISTRY_PATH, RegistryError, load_registry

DEFAULT_OBJECTS_DIRNAME = "objects/sha256"


class IngestionError(RuntimeError):
    """Raised when a candidate cannot be ingested safely."""


@dataclass(frozen=True)
class IngestionResult:
    source_id: str
    requested_url: str
    status: str
    classification: str | None
    final_url: str | None
    sha256: str | None
    bytes_read: int | None
    object_path: str | None
    error: str | None


def _source_by_id(registry: dict, source_id: str) -> dict:
    for source in registry["sources"]:
        if source.get("id") == source_id:
            if source.get("enabled") is True and source.get("official") is True:
                return source
            raise IngestionError(f"source is not enabled and official: {source_id}")
    raise IngestionError(f"unknown source id: {source_id}")


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def object_relative_path(sha256: str) -> Path:
    if len(sha256) != 64 or any(ch not in "0123456789abcdef" for ch in sha256):
        raise IngestionError("invalid SHA-256 hex digest")
    return Path(DEFAULT_OBJECTS_DIRNAME) / sha256[:2] / sha256


def store_exact_object(state_path: Path, sha256: str, body: bytes) -> str:
    """Store exact bytes once, never overwriting an existing content-addressed object."""
    expected = sha256_bytes(body)
    if expected != sha256:
        raise IngestionError(
            f"object digest mismatch: expected {sha256}, computed {expected}"
        )

    state_path = Path(state_path)
    relative = object_relative_path(sha256)
    path = state_path.parent / relative
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        existing = path.read_bytes()
        if existing != body:
            raise IngestionError(
                f"content-addressed object already exists with different bytes: {relative}"
            )
        return relative.as_posix()

    try:
        with path.open("xb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        # Another process may have won the exclusive create. Verify instead of overwrite.
        existing = path.read_bytes()
        if existing != body:
            raise IngestionError(
                f"content-addressed object race produced different bytes: {relative}"
            )

    return relative.as_posix()


def _error_result(source_id: str, requested_url: str, error: str) -> IngestionResult:
    return IngestionResult(
        source_id=source_id,
        requested_url=requested_url,
        status="ERROR",
        classification=None,
        final_url=None,
        sha256=None,
        bytes_read=None,
        object_path=None,
        error=error,
    )


def ingest_candidate(
    registry: dict,
    source_id: str,
    requested_url: str,
    connection,
    *,
    state_path: Path = DEFAULT_STATE_PATH,
    request_get: Callable = requests.get,
    robots_text: str | None | object = ...,
    delay_s: float = DEFAULT_DELAY_S,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> IngestionResult:
    """Fetch and preserve one previously discovered HTML candidate."""
    if delay_s < 0:
        raise ValueError("delay_s must be >= 0")

    source = _source_by_id(registry, source_id)
    ensure_ingestion_schema(connection)
    require_discovered_candidate(connection, source_id, requested_url)

    try:
        if not is_allowed_fetch_url(source, requested_url):
            raise IngestionError(
                f"candidate is no longer allowed by current source policy: {requested_url}"
            )

        if robots_text is ...:
            robots_text = fetch_robots_txt(
                source, requested_url, request_get=request_get
            )
        if not robots_allows(robots_text, requested_url):
            raise IngestionError(f"robots.txt disallows candidate: {requested_url}")

        requested_delay = robots_crawl_delay(robots_text, requested_url) or 0.0
        effective_delay = max(delay_s, requested_delay)
        if effective_delay > 0:
            sleep_fn(effective_delay)

        fetched = fetch_html(source, requested_url, request_get=request_get)
        digest = sha256_bytes(fetched.body)
        object_path = store_exact_object(state_path, digest, fetched.body)
        observation = record_success(
            connection,
            source_id=source_id,
            requested_url=requested_url,
            final_url=fetched.url,
            content_type=fetched.content_type,
            bytes_read=fetched.bytes_read,
            sha256=digest,
            object_path=object_path,
        )
        return IngestionResult(
            source_id=source_id,
            requested_url=requested_url,
            status="SUCCESS",
            classification=observation.classification,
            final_url=fetched.url,
            sha256=digest,
            bytes_read=fetched.bytes_read,
            object_path=object_path,
            error=None,
        )
    except (IngestionError, NetworkPolicyError, OSError) as exc:
        message = str(exc)
        record_failure(
            connection,
            source_id=source_id,
            requested_url=requested_url,
            error=message,
        )
        return _error_result(source_id, requested_url, message)


def ingest_source(
    registry: dict,
    source_id: str,
    connection,
    *,
    state_path: Path = DEFAULT_STATE_PATH,
    limit: int = 1,
    request_get: Callable = requests.get,
    delay_s: float = DEFAULT_DELAY_S,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> list[IngestionResult]:
    """Ingest a bounded, deterministic prefix of one source's discovered candidates."""
    if limit < 1:
        raise IngestionError("limit must be >= 1")
    source = _source_by_id(registry, source_id)
    urls = candidate_urls(connection, source_id, limit=limit)
    if not urls:
        raise IngestionError(
            f"no discovered candidates for {source_id}; run live discovery first"
        )

    robots_cache: dict[str, str | None] = {}
    results: list[IngestionResult] = []
    for url in urls:
        robots_url = robots_url_for(url)
        try:
            if robots_url not in robots_cache:
                robots_cache[robots_url] = fetch_robots_txt(
                    source, url, request_get=request_get
                )
            result = ingest_candidate(
                registry,
                source_id,
                url,
                connection,
                state_path=state_path,
                request_get=request_get,
                robots_text=robots_cache[robots_url],
                delay_s=delay_s,
                sleep_fn=sleep_fn,
            )
        except (NetworkPolicyError, OSError) as exc:
            message = str(exc)
            record_failure(
                connection,
                source_id=source_id,
                requested_url=url,
                error=message,
            )
            result = _error_result(source_id, url, message)
        results.append(result)
    return results


def _payload(source_id: str, results: list[IngestionResult]) -> dict:
    classifications = {"NEW": 0, "UNCHANGED": 0, "CHANGED": 0}
    error_count = 0
    for result in results:
        if result.status == "ERROR":
            error_count += 1
        elif result.classification in classifications:
            classifications[result.classification] += 1

    return {
        "ok": error_count == 0,
        "source_id": source_id,
        "processed": len(results),
        "new_count": classifications["NEW"],
        "unchanged_count": classifications["UNCHANGED"],
        "changed_count": classifications["CHANGED"],
        "error_count": error_count,
        "results": [asdict(result) for result in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="enabled registry source id")
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="maximum discovered candidates to ingest (default: 1)",
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_S,
        help="minimum polite delay per HTML fetch (robots.txt may increase it)",
    )
    args = parser.parse_args()

    connection = None
    try:
        registry = load_registry(args.registry)
        connection = connect_state(args.state)
        results = ingest_source(
            registry,
            args.source,
            connection,
            state_path=args.state,
            limit=args.limit,
            delay_s=args.delay,
        )
        payload = _payload(args.source, results)
    except (RegistryError, IngestionStateError, IngestionError, ValueError) as exc:
        payload = {"ok": False, "source_id": args.source, "error": str(exc)}
    finally:
        if connection is not None:
            connection.close()

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
