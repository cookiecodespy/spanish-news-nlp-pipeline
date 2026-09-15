"""Operator-facing assurance commands for the v2 research pipeline.

This module deliberately keeps assurance deterministic. It validates local configuration,
reads pipeline state, and can run explicit live smoke checks using the same network and
discovery policy as production discovery. It does not use an LLM and it does not ingest
candidate document bodies.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Callable

import requests

from research_pipeline.discovery import DiscoveryPolicyError
from research_pipeline.discovery_state import (
    DEFAULT_STATE_PATH,
    DiscoveryStateError,
    connect_state,
    latest_run,
)
from research_pipeline.live_discovery import DEFAULT_DELAY_S, discover_source_live
from research_pipeline.network import NetworkPolicyError
from research_pipeline.registry import (
    DEFAULT_REGISTRY_PATH,
    RegistryError,
    load_registry,
)

NORMALIZER_PACKAGE = "trafilatura"
NORMALIZER_VERSION = "2.2.0"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class SourceVerification:
    source_id: str
    status: str
    candidate_count: int
    detail: str


def _enabled_sources(registry: dict) -> list[dict]:
    return [
        source
        for source in registry["sources"]
        if source.get("enabled") is True and source.get("official") is True
    ]


def _nearest_existing_parent(path: Path) -> Path:
    current = path.resolve()
    if current.exists():
        return current if current.is_dir() else current.parent
    current = current.parent
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def _normalizer_check() -> Check:
    """Verify the parser version that materially determines normalized artifacts."""
    try:
        runtime = package_version(NORMALIZER_PACKAGE)
    except PackageNotFoundError:
        return Check(
            "normalizer",
            "FAIL",
            f"{NORMALIZER_PACKAGE} is not installed (expected {NORMALIZER_VERSION})",
        )
    except Exception as exc:
        return Check("normalizer", "FAIL", f"could not inspect normalizer version: {exc}")

    if runtime != NORMALIZER_VERSION:
        return Check(
            "normalizer",
            "FAIL",
            f"{NORMALIZER_PACKAGE} {runtime} installed; expected {NORMALIZER_VERSION}",
        )
    return Check(
        "normalizer",
        "PASS",
        f"{NORMALIZER_PACKAGE} {runtime} matches the pinned artifact extractor",
    )


def doctor(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
) -> dict:
    """Run deterministic local readiness checks without making network requests."""
    checks: list[Check] = []
    registry = None

    try:
        registry = load_registry(registry_path)
        enabled = len(_enabled_sources(registry))
        checks.append(
            Check(
                "registry",
                "PASS",
                f"valid registry with {enabled} enabled official sources",
            )
        )
    except RegistryError as exc:
        checks.append(Check("registry", "FAIL", str(exc)))

    state_path = Path(state_path)
    if state_path.exists():
        connection = None
        try:
            connection = connect_state(state_path)
            checks.append(Check("state", "PASS", f"state schema OK: {state_path}"))
        except (DiscoveryStateError, OSError) as exc:
            checks.append(Check("state", "FAIL", str(exc)))
        finally:
            if connection is not None:
                connection.close()
    else:
        parent = _nearest_existing_parent(state_path.parent)
        writable = os.access(parent, os.W_OK)
        checks.append(
            Check(
                "state",
                "PASS" if writable else "FAIL",
                (
                    f"state not created yet; writable parent: {parent}"
                    if writable
                    else f"state not created and nearest parent is not writable: {parent}"
                ),
            )
        )

    if registry is not None:
        entrypoints = sum(len(source.get("entrypoints", [])) for source in _enabled_sources(registry))
        checks.append(
            Check(
                "entrypoints",
                "PASS" if entrypoints > 0 else "FAIL",
                f"{entrypoints} configured entrypoints across enabled sources",
            )
        )

    checks.append(_normalizer_check())

    ok = all(check.status == "PASS" for check in checks)
    return {"ok": ok, "checks": [asdict(check) for check in checks]}


def _table_exists(connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def _empty_stage(status_name: str) -> dict:
    return {
        "status": status_name,
        "observation_id": None,
        "classification": None,
        "requested_url": None,
        "timestamp": None,
        "error": None,
    }


def _latest_ingestion_view(connection, source_id: str) -> dict:
    if not _table_exists(connection, "ingestion_observations"):
        return _empty_stage("NOT_INITIALIZED")
    row = connection.execute(
        """
        SELECT id, status, classification, requested_url, final_url, fetched_at,
               sha256, error
        FROM ingestion_observations
        WHERE source_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (source_id,),
    ).fetchone()
    if row is None:
        return _empty_stage("NEVER_RUN")
    return {
        "status": str(row["status"]).upper(),
        "observation_id": int(row["id"]),
        "classification": row["classification"],
        "requested_url": row["requested_url"],
        "final_url": row["final_url"],
        "sha256": row["sha256"],
        "timestamp": row["fetched_at"],
        "error": row["error"],
    }


def _latest_normalization_view(connection, source_id: str) -> dict:
    if not _table_exists(connection, "normalization_observations"):
        return _empty_stage("NOT_INITIALIZED")
    row = connection.execute(
        """
        SELECT id, status, classification, requested_url, normalized_at,
               normalized_sha256, title, extractor_name, extractor_version, error
        FROM normalization_observations
        WHERE source_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (source_id,),
    ).fetchone()
    if row is None:
        return _empty_stage("NEVER_RUN")
    return {
        "status": str(row["status"]).upper(),
        "observation_id": int(row["id"]),
        "classification": row["classification"],
        "requested_url": row["requested_url"],
        "normalized_sha256": row["normalized_sha256"],
        "title": row["title"],
        "extractor": (
            {
                "name": row["extractor_name"],
                "version": row["extractor_version"],
            }
            if row["extractor_name"] and row["extractor_version"]
            else None
        ),
        "timestamp": row["normalized_at"],
        "error": row["error"],
    }


def _source_status_without_state(source_id: str) -> dict:
    return {
        "source_id": source_id,
        # Legacy/top-level fields continue to describe discovery for compatibility.
        "status": "NEVER_RUN",
        "run_id": None,
        "candidate_count": 0,
        "new_count": 0,
        "known_count": 0,
        "finished_at": None,
        "error": None,
        "ingestion": _empty_stage("NOT_INITIALIZED"),
        "normalization": _empty_stage("NOT_INITIALIZED"),
    }


def status(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
) -> dict:
    """Return concise operator-visible state across discovery, ingestion and normalization."""
    registry = load_registry(registry_path)
    sources = _enabled_sources(registry)
    state_path = Path(state_path)

    if not state_path.exists():
        return {
            "ok": True,
            "state_exists": False,
            "state_path": str(state_path),
            "sources": [_source_status_without_state(source["id"]) for source in sources],
        }

    connection = connect_state(state_path)
    try:
        rows = []
        for source in sources:
            discovery = latest_run(connection, source["id"])
            if discovery is None:
                row = _source_status_without_state(source["id"])
                row["ingestion"] = _latest_ingestion_view(connection, source["id"])
                row["normalization"] = _latest_normalization_view(connection, source["id"])
                rows.append(row)
                continue

            rows.append(
                {
                    "source_id": source["id"],
                    "status": str(discovery["status"]).upper(),
                    "run_id": int(discovery["id"]),
                    "candidate_count": int(discovery["candidate_count"]),
                    "new_count": int(discovery["new_count"]),
                    "known_count": int(discovery["known_count"]),
                    "finished_at": discovery["finished_at"],
                    "error": discovery["error"],
                    "ingestion": _latest_ingestion_view(connection, source["id"]),
                    "normalization": _latest_normalization_view(connection, source["id"]),
                }
            )
    finally:
        connection.close()

    return {
        "ok": True,
        "state_exists": True,
        "state_path": str(state_path),
        "sources": rows,
    }


def _verification_status(exc: Exception) -> str:
    text = str(exc).lower()
    if "robots.txt disallows" in text:
        return "BLOCKED"
    return "FAIL"


def verify_live(
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    source_id: str | None = None,
    delay_s: float = DEFAULT_DELAY_S,
    request_get: Callable = requests.get,
    sleep_fn: Callable[[float], None] | None = None,
) -> dict:
    """Run an explicit live smoke verification without mutating discovery state."""
    if delay_s < 0:
        raise ValueError("delay_s must be >= 0")

    registry = load_registry(registry_path)
    sources = _enabled_sources(registry)
    if source_id is not None:
        sources = [source for source in sources if source["id"] == source_id]
        if not sources:
            raise DiscoveryPolicyError(f"Unknown or disabled source id: {source_id}")

    results: list[SourceVerification] = []
    for source in sources:
        try:
            kwargs = {
                "request_get": request_get,
                "delay_s": delay_s,
            }
            if sleep_fn is not None:
                kwargs["sleep_fn"] = sleep_fn
            discovered = discover_source_live(registry, source["id"], **kwargs)
            candidate_count = sum(item.candidate_count for item in discovered)
            results.append(
                SourceVerification(
                    source["id"],
                    "PASS",
                    candidate_count,
                    f"{len(discovered)} entrypoints reachable under current policy",
                )
            )
        except (DiscoveryPolicyError, NetworkPolicyError, requests.RequestException, RuntimeError) as exc:
            results.append(
                SourceVerification(
                    source["id"],
                    _verification_status(exc),
                    0,
                    str(exc),
                )
            )

    overall = "PASS"
    if any(item.status == "FAIL" for item in results):
        overall = "FAIL"
    elif any(item.status == "BLOCKED" for item in results):
        overall = "BLOCKED"

    return {
        "ok": overall == "PASS",
        "status": overall,
        "sources": [asdict(item) for item in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("doctor", "status", "verify-live"))
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--source", help="verify only one enabled source")
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_S,
        help="minimum polite delay for live verification",
    )
    args = parser.parse_args()

    try:
        if args.command == "doctor":
            payload = doctor(registry_path=args.registry, state_path=args.state)
        elif args.command == "status":
            payload = status(registry_path=args.registry, state_path=args.state)
        else:
            payload = verify_live(
                registry_path=args.registry,
                source_id=args.source,
                delay_s=args.delay,
            )
    except (RegistryError, DiscoveryStateError, DiscoveryPolicyError, ValueError) as exc:
        payload = {"ok": False, "error": str(exc)}

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
