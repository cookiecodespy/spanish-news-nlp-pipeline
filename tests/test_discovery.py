import json
from pathlib import Path

import pytest

from research_pipeline.discovery import DiscoveryPolicyError, discover_links, normalize_url


REGISTRY = json.loads(Path("sources/registry.json").read_text(encoding="utf-8"))


def test_normalize_url_resolves_relative_and_strips_fragment():
    assert normalize_url(
        "https://www.anthropic.com/engineering",
        "/engineering/building-effective-agents#section",
    ) == "https://www.anthropic.com/engineering/building-effective-agents"


def test_discovery_keeps_only_allowlisted_anthropic_links():
    html = """
    <a href="/engineering/effective-context-engineering-for-ai-agents#intro">A</a>
    <a href="https://www.anthropic.com/engineering/building-effective-agents">B</a>
    <a href="/engineering/building-effective-agents#duplicate">B2</a>
    <a href="/news/company-update">outside allowed prefix</a>
    <a href="https://evil.example/engineering/fake">outside domain</a>
    <a href="mailto:hello@example.com">mail</a>
    <a href="javascript:alert(1)">js</a>
    """

    links = discover_links(
        REGISTRY,
        "anthropic-engineering",
        "https://www.anthropic.com/engineering",
        html,
    )

    assert links == [
        "https://www.anthropic.com/engineering/building-effective-agents",
        "https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents",
    ]


def test_openai_research_entrypoint_can_discover_index_destinations():
    html = """
    <a href="https://openai.com/index/research-acceleration-view-inside-openai/">research</a>
    <a href="https://openai.com/pricing/">pricing</a>
    <a href="http://openai.com/index/insecure/">http</a>
    """

    links = discover_links(
        REGISTRY,
        "openai-research",
        "https://openai.com/research/",
        html,
    )

    assert links == [
        "https://openai.com/index/research-acceleration-view-inside-openai/"
    ]


def test_discovery_rejects_unconfigured_entrypoint():
    with pytest.raises(DiscoveryPolicyError, match="Entrypoint is not configured"):
        discover_links(
            REGISTRY,
            "openai-research",
            "https://openai.com/pricing/",
            "<a href='/index/example/'>x</a>",
        )
