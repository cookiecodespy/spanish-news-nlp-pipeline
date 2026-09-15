import json
from pathlib import Path

import pytest

from research_pipeline.discovery import DiscoveryPolicyError
from research_pipeline.discovery_state import connect_state, latest_run
from research_pipeline.live_discovery import (
    discover_entrypoint_live,
    discover_source_live,
    discover_source_with_state,
    robots_allows,
    robots_crawl_delay,
)


REGISTRY = json.loads(Path("sources/registry.json").read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, status_code=200, body=b"", headers=None, encoding="utf-8"):
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}
        self.encoding = encoding

    def iter_content(self, chunk_size=65536):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]


def fake_get_sequence(responses, seen):
    queue = list(responses)

    def fake_get(url, **kwargs):
        seen.append(url)
        if not queue:
            raise AssertionError("unexpected extra HTTP request")
        return queue.pop(0)

    return fake_get


def test_robots_rules_can_block_configured_entrypoint():
    assert not robots_allows(
        "User-agent: *\nDisallow: /research/\n",
        "https://openai.com/research/",
    )


def test_robots_crawl_delay_is_read_for_this_agent():
    assert robots_crawl_delay(
        "User-agent: *\nAllow: /\nCrawl-delay: 3\n",
        "https://openai.com/research/",
    ) == 3.0


def test_live_discovery_stops_before_html_when_robots_disallows():
    with pytest.raises(DiscoveryPolicyError, match="robots.txt disallows"):
        discover_entrypoint_live(
            REGISTRY,
            "openai-research",
            "https://openai.com/research/",
            robots_text="User-agent: *\nDisallow: /research/\n",
            request_get=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("HTML request should not run")
            ),
            delay_s=0,
        )


def test_live_discovery_returns_candidates_without_downloading_them():
    seen = []
    fake_get = fake_get_sequence(
        [
            FakeResponse(
                body=(
                    b'<html><a href="https://openai.com/index/a/">A</a>'
                    b'<a href="https://openai.com/pricing/">pricing</a></html>'
                ),
                headers={"Content-Type": "text/html"},
            )
        ],
        seen,
    )

    result = discover_entrypoint_live(
        REGISTRY,
        "openai-research",
        "https://openai.com/research/",
        robots_text=None,
        request_get=fake_get,
        delay_s=0,
    )

    assert result.candidates == ["https://openai.com/index/a/"]
    assert result.candidate_count == 1
    assert seen == ["https://openai.com/research/"]


def test_redirected_entrypoint_resolves_relative_links_against_final_url():
    seen = []
    fake_get = fake_get_sequence(
        [
            FakeResponse(status_code=302, headers={"Location": "/index/research-home/"}),
            FakeResponse(
                body=b'<a href="child/">child</a>',
                headers={"Content-Type": "text/html"},
            ),
        ],
        seen,
    )

    result = discover_entrypoint_live(
        REGISTRY,
        "openai-research",
        "https://openai.com/research/",
        robots_text=None,
        request_get=fake_get,
        delay_s=0,
    )

    assert result.final_url == "https://openai.com/index/research-home/"
    assert result.candidates == ["https://openai.com/index/research-home/child/"]


def test_source_discovery_fetches_robots_once_and_honors_crawl_delay():
    seen = []
    sleeps = []
    fake_get = fake_get_sequence(
        [
            FakeResponse(
                body=b"User-agent: *\nAllow: /\nCrawl-delay: 3\n",
                headers={"Content-Type": "text/plain"},
            ),
            FakeResponse(
                body=b'<a href="/research/paper-one/">one</a>',
                headers={"Content-Type": "text/html"},
            ),
            FakeResponse(
                body=b'<a href="/research/publications/paper-two/">two</a>',
                headers={"Content-Type": "text/html"},
            ),
        ],
        seen,
    )

    results = discover_source_live(
        REGISTRY,
        "google-deepmind-research",
        request_get=fake_get,
        delay_s=0.25,
        sleep_fn=sleeps.append,
    )

    assert len(results) == 2
    assert seen.count("https://deepmind.google/robots.txt") == 1
    assert len(seen) == 3
    assert sleeps == [3.0, 3.0]


def test_stateful_discovery_reports_new_then_known(tmp_path):
    connection = connect_state(tmp_path / "discovery.sqlite3")

    first_get = fake_get_sequence(
        [
            FakeResponse(
                body=b"User-agent: *\nAllow: /\n",
                headers={"Content-Type": "text/plain"},
            ),
            FakeResponse(
                body=b'<a href="/engineering/example/">example</a>',
                headers={"Content-Type": "text/html"},
            ),
        ],
        [],
    )
    _, first_summary = discover_source_with_state(
        REGISTRY,
        "anthropic-engineering",
        connection,
        request_get=first_get,
        delay_s=0,
    )
    assert first_summary.new_count == 1
    assert first_summary.known_count == 0

    second_get = fake_get_sequence(
        [
            FakeResponse(
                body=b"User-agent: *\nAllow: /\n",
                headers={"Content-Type": "text/plain"},
            ),
            FakeResponse(
                body=b'<a href="/engineering/example/">example</a>',
                headers={"Content-Type": "text/html"},
            ),
        ],
        [],
    )
    _, second_summary = discover_source_with_state(
        REGISTRY,
        "anthropic-engineering",
        connection,
        request_get=second_get,
        delay_s=0,
    )
    assert second_summary.new_count == 0
    assert second_summary.known_count == 1


def test_stateful_discovery_records_policy_failure(tmp_path):
    connection = connect_state(tmp_path / "discovery.sqlite3")
    fake_get = fake_get_sequence(
        [
            FakeResponse(
                body=b"User-agent: *\nDisallow: /engineering\n",
                headers={"Content-Type": "text/plain"},
            )
        ],
        [],
    )

    with pytest.raises(DiscoveryPolicyError, match="robots.txt disallows"):
        discover_source_with_state(
            REGISTRY,
            "anthropic-engineering",
            connection,
            request_get=fake_get,
            delay_s=0,
        )

    row = latest_run(connection, "anthropic-engineering")
    assert row is not None
    assert row["status"] == "error"
    assert row["candidate_count"] == 0
    assert "robots.txt disallows" in row["error"]
