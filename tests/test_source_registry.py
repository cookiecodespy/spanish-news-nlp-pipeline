import copy
import json
from pathlib import Path

import pytest

from research_pipeline.registry import RegistryError, validate_registry


REGISTRY_PATH = Path("sources/registry.json")


def load_raw_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_committed_registry_is_valid():
    validate_registry(load_raw_registry())


def test_duplicate_source_ids_are_rejected():
    registry = load_raw_registry()
    duplicate = copy.deepcopy(registry["sources"][0])
    registry["sources"].append(duplicate)

    with pytest.raises(RegistryError, match="duplicate source id"):
        validate_registry(registry)


def test_enabled_source_must_be_official():
    registry = load_raw_registry()
    registry["sources"][0]["official"] = False

    with pytest.raises(RegistryError, match="enabled sources must be official"):
        validate_registry(registry)


def test_entrypoints_must_use_https():
    registry = load_raw_registry()
    registry["sources"][0]["entrypoints"] = ["http://openai.com/research/"]

    with pytest.raises(RegistryError, match="absolute HTTPS URL"):
        validate_registry(registry)


def test_entrypoint_host_must_be_allowlisted():
    registry = load_raw_registry()
    registry["sources"][0]["entrypoints"] = ["https://example.com/research/"]

    with pytest.raises(RegistryError, match="is not in domains"):
        validate_registry(registry)
