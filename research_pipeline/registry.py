"""Load and validate the v2 official-source registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_REGISTRY_PATH = Path("sources/registry.json")


class RegistryError(ValueError):
    """Raised when the source registry violates the v2 trust contract."""


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _is_https(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.hostname)


def validate_registry(registry: dict) -> None:
    """Validate structural and trust invariants for the source registry."""
    errors: list[str] = []

    if registry.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if registry.get("default") != "deny":
        errors.append("default trust policy must be 'deny'")

    discovery_defaults = registry.get("discovery_defaults", {})
    if discovery_defaults.get("scope") != "entrypoint_links_only":
        errors.append("discovery_defaults.scope must be 'entrypoint_links_only'")
    if discovery_defaults.get("same_domain_only") is not True:
        errors.append("discovery_defaults.same_domain_only must be true")

    sources = registry.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources must be a non-empty list")
        sources = []

    seen_ids: set[str] = set()

    for index, source in enumerate(sources):
        prefix = f"sources[{index}]"
        source_id = source.get("id")

        if not isinstance(source_id, str) or not source_id.strip():
            errors.append(f"{prefix}.id must be a non-empty string")
        elif source_id in seen_ids:
            errors.append(f"duplicate source id: {source_id}")
        else:
            seen_ids.add(source_id)

        if source.get("enabled") is True and source.get("official") is not True:
            errors.append(f"{source_id or prefix}: enabled sources must be official")

        domains = source.get("domains")
        if not isinstance(domains, list) or not domains:
            errors.append(f"{source_id or prefix}: domains must be a non-empty list")
            domains = []
        normalized_domains = {str(domain).lower() for domain in domains}

        entrypoints = source.get("entrypoints")
        if not isinstance(entrypoints, list) or not entrypoints:
            errors.append(f"{source_id or prefix}: entrypoints must be a non-empty list")
            entrypoints = []

        allowed_prefixes = source.get("allowed_url_prefixes")
        if not isinstance(allowed_prefixes, list) or not allowed_prefixes:
            errors.append(
                f"{source_id or prefix}: allowed_url_prefixes must be a non-empty list"
            )
            allowed_prefixes = []

        for label, urls in (
            ("entrypoint", entrypoints),
            ("allowed_url_prefix", allowed_prefixes),
        ):
            for url in urls:
                if not isinstance(url, str) or not _is_https(url):
                    errors.append(
                        f"{source_id or prefix}: {label} must be an absolute HTTPS URL: {url!r}"
                    )
                    continue
                if _host(url) not in normalized_domains:
                    errors.append(
                        f"{source_id or prefix}: {label} host {_host(url)!r} is not in domains"
                    )

    if errors:
        raise RegistryError("Invalid source registry:\n- " + "\n- ".join(errors))


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> dict:
    """Read a registry JSON file and return it only if it passes validation."""
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"Could not load registry {path}: {exc}") from exc

    if not isinstance(registry, dict):
        raise RegistryError("Registry root must be a JSON object")

    validate_registry(registry)
    return registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    args = parser.parse_args()

    try:
        registry = load_registry(args.registry)
    except RegistryError as exc:
        print(exc)
        return 1

    enabled = sum(1 for source in registry["sources"] if source.get("enabled"))
    print(f"registry OK: {len(registry['sources'])} sources ({enabled} enabled)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
