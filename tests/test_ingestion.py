import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_pipeline.discovery_state import connect_state, record_success as record_discovery_success, start_run
from research_pipeline.ingestion import (
    IngestionError,
    ingest_candidate,
    ingest_source,
    object_relative_path,
    sha256_bytes,
    store_exact_object,
)


REGISTRY = json.loads(Path("sources/registry.json").read_text(encoding="utf-8"))
SOURCE_ID = "openai-research"
CANDIDATE = "https://openai.com/index/example/"


class FakeResponse:
    def __init__(self, status_code=200, body=b"", headers=None, encoding="utf-8"):
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}
        self.encoding = encoding
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]

    def close(self):
        self.closed = True


def fake_get_sequence(responses, seen=None):
    queue = list(responses)
    seen = seen if seen is not None else []

    def fake_get(url, **kwargs):
        seen.append(url)
        if not queue:
            raise AssertionError("unexpected extra HTTP request")
        return queue.pop(0)

    return fake_get


def seed_candidates(tmp_path, urls):
    state_path = tmp_path / "state.sqlite3"
    connection = connect_state(state_path)
    run_id = start_run(connection, SOURCE_ID, started_at="2026-09-15T00:00:00+00:00")
    record_discovery_success(
        connection,
        run_id,
        [SimpleNamespace(entrypoint="https://openai.com/research/", candidates=list(urls))],
        seen_at="2026-09-15T00:00:01+00:00",
    )
    return state_path, connection


def test_sha_and_object_path_are_deterministic():
    body = b"<html>evidence</html>"
    digest = hashlib.sha256(body).hexdigest()

    assert sha256_bytes(body) == digest
    assert object_relative_path(digest) == Path("objects/sha256") / digest[:2] / digest


def test_content_addressed_store_reuses_identical_bytes_and_never_overwrites(tmp_path):
    state_path = tmp_path / "state.sqlite3"
    body = b"same bytes"
    digest = sha256_bytes(body)

    relative = store_exact_object(state_path, digest, body)
    assert (tmp_path / relative).read_bytes() == body
    assert store_exact_object(state_path, digest, body) == relative

    (tmp_path / relative).write_bytes(b"corrupt local object")
    with pytest.raises(IngestionError, match="different bytes"):
        store_exact_object(state_path, digest, body)
    assert (tmp_path / relative).read_bytes() == b"corrupt local object"


def test_ingestion_classifies_new_unchanged_and_changed_and_preserves_objects(tmp_path):
    state_path, connection = seed_candidates(tmp_path, [CANDIDATE])
    try:
        first_body = b"<html>version one</html>"
        first = ingest_candidate(
            REGISTRY,
            SOURCE_ID,
            CANDIDATE,
            connection,
            state_path=state_path,
            robots_text="User-agent: *\nAllow: /\n",
            request_get=fake_get_sequence(
                [FakeResponse(body=first_body, headers={"Content-Type": "text/html"})]
            ),
            delay_s=0,
        )
        second = ingest_candidate(
            REGISTRY,
            SOURCE_ID,
            CANDIDATE,
            connection,
            state_path=state_path,
            robots_text="User-agent: *\nAllow: /\n",
            request_get=fake_get_sequence(
                [FakeResponse(body=first_body, headers={"Content-Type": "text/html"})]
            ),
            delay_s=0,
        )

        changed_body = b"<html>version two</html>"
        third = ingest_candidate(
            REGISTRY,
            SOURCE_ID,
            CANDIDATE,
            connection,
            state_path=state_path,
            robots_text="User-agent: *\nAllow: /\n",
            request_get=fake_get_sequence(
                [FakeResponse(body=changed_body, headers={"Content-Type": "text/html"})]
            ),
            delay_s=0,
        )

        assert [first.classification, second.classification, third.classification] == [
            "NEW",
            "UNCHANGED",
            "CHANGED",
        ]
        assert first.sha256 == second.sha256
        assert third.sha256 != first.sha256
        assert (tmp_path / first.object_path).read_bytes() == first_body
        assert (tmp_path / third.object_path).read_bytes() == changed_body
        assert len(list((tmp_path / "objects/sha256").glob("*/*"))) == 2
    finally:
        connection.close()


def test_redirect_final_url_is_transport_metadata_not_relabelled_canonical(tmp_path):
    state_path, connection = seed_candidates(tmp_path, [CANDIDATE])
    try:
        result = ingest_candidate(
            REGISTRY,
            SOURCE_ID,
            CANDIDATE,
            connection,
            state_path=state_path,
            robots_text="User-agent: *\nAllow: /\n",
            request_get=fake_get_sequence(
                [
                    FakeResponse(status_code=302, headers={"Location": "/index/final/"}),
                    FakeResponse(
                        body=b"<html>final</html>", headers={"Content-Type": "text/html"}
                    ),
                ]
            ),
            delay_s=0,
        )

        assert result.status == "SUCCESS"
        assert result.requested_url == CANDIDATE
        assert result.final_url == "https://openai.com/index/final/"
        row = connection.execute(
            "SELECT requested_url, final_url FROM ingestion_observations WHERE id = 1"
        ).fetchone()
        assert row["requested_url"] == CANDIDATE
        assert row["final_url"] == "https://openai.com/index/final/"
    finally:
        connection.close()


def test_stale_candidate_outside_current_allowlist_is_recorded_as_error(tmp_path):
    stale = "https://openai.com/pricing/"
    state_path, connection = seed_candidates(tmp_path, [stale])
    try:
        result = ingest_candidate(
            REGISTRY,
            SOURCE_ID,
            stale,
            connection,
            state_path=state_path,
            robots_text=None,
            request_get=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("network must not run")
            ),
            delay_s=0,
        )

        assert result.status == "ERROR"
        assert "no longer allowed" in result.error
        row = connection.execute(
            "SELECT status, classification, sha256, error FROM ingestion_observations"
        ).fetchone()
        assert row["status"] == "error"
        assert row["classification"] is None
        assert row["sha256"] is None
    finally:
        connection.close()


def test_candidate_robots_disallow_blocks_html_fetch_and_records_error(tmp_path):
    state_path, connection = seed_candidates(tmp_path, [CANDIDATE])
    try:
        result = ingest_candidate(
            REGISTRY,
            SOURCE_ID,
            CANDIDATE,
            connection,
            state_path=state_path,
            robots_text="User-agent: *\nDisallow: /index/\n",
            request_get=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("HTML request must not run")
            ),
            delay_s=0,
        )

        assert result.status == "ERROR"
        assert "robots.txt disallows" in result.error
        assert not (tmp_path / "objects").exists()
    finally:
        connection.close()


def test_network_failure_records_error_without_hash_or_object(tmp_path):
    state_path, connection = seed_candidates(tmp_path, [CANDIDATE])
    try:
        result = ingest_candidate(
            REGISTRY,
            SOURCE_ID,
            CANDIDATE,
            connection,
            state_path=state_path,
            robots_text=None,
            request_get=fake_get_sequence([FakeResponse(status_code=503)]),
            delay_s=0,
        )

        assert result.status == "ERROR"
        assert result.sha256 is None
        assert result.object_path is None
        assert not (tmp_path / "objects").exists()
    finally:
        connection.close()


def test_source_ingestion_fetches_robots_once_per_host(tmp_path):
    urls = [
        "https://openai.com/index/a/",
        "https://openai.com/index/b/",
    ]
    state_path, connection = seed_candidates(tmp_path, urls)
    seen = []
    try:
        results = ingest_source(
            REGISTRY,
            SOURCE_ID,
            connection,
            state_path=state_path,
            limit=2,
            request_get=fake_get_sequence(
                [
                    FakeResponse(status_code=404),
                    FakeResponse(body=b"<html>a</html>", headers={"Content-Type": "text/html"}),
                    FakeResponse(body=b"<html>b</html>", headers={"Content-Type": "text/html"}),
                ],
                seen,
            ),
            delay_s=0,
        )

        assert [result.status for result in results] == ["SUCCESS", "SUCCESS"]
        assert seen == [
            "https://openai.com/robots.txt",
            "https://openai.com/index/a/",
            "https://openai.com/index/b/",
        ]
    finally:
        connection.close()


def test_source_ingestion_requires_discovery_first(tmp_path):
    state_path = tmp_path / "state.sqlite3"
    connection = connect_state(state_path)
    try:
        with pytest.raises(IngestionError, match="run live discovery first"):
            ingest_source(
                REGISTRY,
                SOURCE_ID,
                connection,
                state_path=state_path,
                limit=1,
                delay_s=0,
            )
    finally:
        connection.close()
