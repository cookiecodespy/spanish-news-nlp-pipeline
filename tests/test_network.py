import json
from pathlib import Path

import pytest
import requests

from research_pipeline.network import (
    NetworkPolicyError,
    fetch_html,
    fetch_robots_txt,
    is_allowed_fetch_url,
)


REGISTRY = json.loads(Path("sources/registry.json").read_text(encoding="utf-8"))
OPENAI = next(source for source in REGISTRY["sources"] if source["id"] == "openai-research")


class FakeResponse:
    def __init__(
        self,
        status_code=200,
        body=b"",
        headers=None,
        encoding="utf-8",
        chunk_size=None,
    ):
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}
        self.encoding = encoding
        self.chunk_size = chunk_size
        self.closed = False

    def iter_content(self, chunk_size=65536):
        size = self.chunk_size or chunk_size
        for start in range(0, len(self.body), size):
            yield self.body[start : start + size]

    def close(self):
        self.closed = True


def fake_get_sequence(responses, seen):
    queue = list(responses)

    def fake_get(url, **kwargs):
        seen.append((url, kwargs))
        if not queue:
            raise AssertionError("unexpected extra HTTP request")
        return queue.pop(0)

    return fake_get


def test_configured_entrypoint_and_allowed_candidate_are_fetchable():
    assert is_allowed_fetch_url(OPENAI, "https://openai.com/research/")
    assert is_allowed_fetch_url(OPENAI, "https://openai.com/index/example/")
    assert not is_allowed_fetch_url(OPENAI, "https://openai.com/pricing/")


def test_fetch_html_uses_bounded_non_redirecting_request_and_closes_response():
    seen = []
    response = FakeResponse(
        body=b"<html>ok</html>",
        headers={"Content-Type": "text/html; charset=utf-8"},
    )
    fake_get = fake_get_sequence([response], seen)

    result = fetch_html(OPENAI, "https://openai.com/research/", request_get=fake_get)

    assert result.text == "<html>ok</html>"
    assert response.closed is True
    assert seen[0][0] == "https://openai.com/research/"
    assert seen[0][1]["allow_redirects"] is False
    assert seen[0][1]["stream"] is True
    assert "User-Agent" in seen[0][1]["headers"]


def test_fetch_html_allows_valid_redirect_and_revalidates_target():
    seen = []
    redirect = FakeResponse(status_code=302, headers={"Location": "/index/example/"})
    final = FakeResponse(body=b"<html>ok</html>", headers={"Content-Type": "text/html"})
    fake_get = fake_get_sequence([redirect, final], seen)

    result = fetch_html(OPENAI, "https://openai.com/research/", request_get=fake_get)

    assert result.url == "https://openai.com/index/example/"
    assert redirect.closed is True
    assert final.closed is True
    assert [item[0] for item in seen] == [
        "https://openai.com/research/",
        "https://openai.com/index/example/",
    ]


def test_fetch_html_rejects_redirect_outside_allowlist():
    fake_get = fake_get_sequence(
        [FakeResponse(status_code=302, headers={"Location": "https://evil.example/x"})],
        [],
    )

    with pytest.raises(NetworkPolicyError, match="redirect target is outside"):
        fetch_html(OPENAI, "https://openai.com/research/", request_get=fake_get)


def test_fetch_html_rejects_wrong_content_type():
    fake_get = fake_get_sequence(
        [FakeResponse(body=b"%PDF", headers={"Content-Type": "application/pdf"})],
        [],
    )

    with pytest.raises(NetworkPolicyError, match="unexpected content type"):
        fetch_html(OPENAI, "https://openai.com/research/", request_get=fake_get)


def test_fetch_html_enforces_streaming_size_limit_without_content_length():
    fake_get = fake_get_sequence(
        [
            FakeResponse(
                body=b"0123456789",
                headers={"Content-Type": "text/html"},
                chunk_size=4,
            )
        ],
        [],
    )

    with pytest.raises(NetworkPolicyError, match="response too large while streaming"):
        fetch_html(
            OPENAI,
            "https://openai.com/research/",
            request_get=fake_get,
            max_bytes=8,
        )


def test_fetch_html_rejects_declared_oversize_response_early():
    fake_get = fake_get_sequence(
        [
            FakeResponse(
                body=b"small",
                headers={"Content-Type": "text/html", "Content-Length": "999"},
            )
        ],
        [],
    )

    with pytest.raises(NetworkPolicyError, match="declared 999 bytes"):
        fetch_html(
            OPENAI,
            "https://openai.com/research/",
            request_get=fake_get,
            max_bytes=8,
        )


def test_request_exceptions_are_normalized_to_policy_error():
    def timeout(*args, **kwargs):
        raise requests.Timeout("simulated timeout")

    with pytest.raises(NetworkPolicyError, match="network request failed"):
        fetch_html(OPENAI, "https://openai.com/research/", request_get=timeout)


def test_missing_robots_txt_is_not_treated_as_an_error():
    fake_get = fake_get_sequence([FakeResponse(status_code=404)], [])

    assert (
        fetch_robots_txt(
            OPENAI,
            "https://openai.com/research/",
            request_get=fake_get,
        )
        is None
    )


def test_robots_redirect_must_remain_robots_on_allowlisted_host():
    fake_get = fake_get_sequence(
        [FakeResponse(status_code=302, headers={"Location": "/pricing/"})],
        [],
    )

    with pytest.raises(NetworkPolicyError, match="robots.txt redirect target is outside policy"):
        fetch_robots_txt(
            OPENAI,
            "https://openai.com/research/",
            request_get=fake_get,
        )
