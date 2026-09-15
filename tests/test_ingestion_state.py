from types import SimpleNamespace

import pytest

from research_pipeline.discovery_state import connect_state, record_success as record_discovery_success, start_run
from research_pipeline.ingestion_state import (
    IngestionStateError,
    candidate_urls,
    ensure_ingestion_schema,
    latest_success,
    record_failure,
    record_success,
)


def discovered_connection(tmp_path, urls):
    connection = connect_state(tmp_path / "state.sqlite3")
    run_id = start_run(connection, "source-a", started_at="2026-09-15T00:00:00+00:00")
    record_discovery_success(
        connection,
        run_id,
        [SimpleNamespace(entrypoint="https://example.com/research/", candidates=list(urls))],
        seen_at="2026-09-15T00:00:01+00:00",
    )
    ensure_ingestion_schema(connection)
    return connection


def test_first_same_and_changed_hashes_are_classified_deterministically(tmp_path):
    connection = discovered_connection(tmp_path, ["https://example.com/research/a"])
    try:
        first = record_success(
            connection,
            source_id="source-a",
            requested_url="https://example.com/research/a",
            final_url="https://example.com/research/a",
            content_type="text/html",
            bytes_read=3,
            sha256="a" * 64,
            object_path="objects/aa/" + "a" * 64,
            fetched_at="2026-09-15T01:00:00+00:00",
        )
        second = record_success(
            connection,
            source_id="source-a",
            requested_url="https://example.com/research/a",
            final_url="https://example.com/research/a",
            content_type="text/html",
            bytes_read=3,
            sha256="a" * 64,
            object_path="objects/aa/" + "a" * 64,
            fetched_at="2026-09-15T02:00:00+00:00",
        )
        third = record_success(
            connection,
            source_id="source-a",
            requested_url="https://example.com/research/a",
            final_url="https://example.com/research/a",
            content_type="text/html",
            bytes_read=4,
            sha256="b" * 64,
            object_path="objects/bb/" + "b" * 64,
            fetched_at="2026-09-15T03:00:00+00:00",
        )

        assert first.classification == "NEW"
        assert second.classification == "UNCHANGED"
        assert third.classification == "CHANGED"
        assert latest_success(
            connection, "source-a", "https://example.com/research/a"
        )["sha256"] == "b" * 64
    finally:
        connection.close()


def test_undiscovered_url_is_rejected(tmp_path):
    connection = discovered_connection(tmp_path, ["https://example.com/research/a"])
    try:
        with pytest.raises(IngestionStateError, match="was not discovered"):
            record_success(
                connection,
                source_id="source-a",
                requested_url="https://example.com/research/not-seen",
                final_url="https://example.com/research/not-seen",
                content_type="text/html",
                bytes_read=1,
                sha256="c" * 64,
                object_path="objects/cc/" + "c" * 64,
            )
    finally:
        connection.close()


def test_failure_has_no_hash_or_change_classification(tmp_path):
    connection = discovered_connection(tmp_path, ["https://example.com/research/a"])
    try:
        failed = record_failure(
            connection,
            source_id="source-a",
            requested_url="https://example.com/research/a",
            error="simulated timeout",
            fetched_at="2026-09-15T04:00:00+00:00",
        )
        row = connection.execute(
            "SELECT * FROM ingestion_observations WHERE id = ?",
            (failed.observation_id,),
        ).fetchone()

        assert failed.status == "error"
        assert failed.classification is None
        assert failed.sha256 is None
        assert failed.object_path is None
        assert row["classification"] is None
        assert row["sha256"] is None
        assert row["object_path"] is None
        assert row["error"] == "simulated timeout"
    finally:
        connection.close()


def test_failure_does_not_replace_latest_success(tmp_path):
    connection = discovered_connection(tmp_path, ["https://example.com/research/a"])
    try:
        record_success(
            connection,
            source_id="source-a",
            requested_url="https://example.com/research/a",
            final_url="https://example.com/research/a",
            content_type="text/html",
            bytes_read=1,
            sha256="d" * 64,
            object_path="objects/dd/" + "d" * 64,
        )
        record_failure(
            connection,
            source_id="source-a",
            requested_url="https://example.com/research/a",
            error="later error",
        )

        assert latest_success(
            connection, "source-a", "https://example.com/research/a"
        )["sha256"] == "d" * 64
    finally:
        connection.close()


def test_candidates_are_returned_in_stable_order_and_can_be_limited(tmp_path):
    connection = discovered_connection(
        tmp_path,
        [
            "https://example.com/research/c",
            "https://example.com/research/a",
            "https://example.com/research/b",
        ],
    )
    try:
        assert candidate_urls(connection, "source-a") == [
            "https://example.com/research/a",
            "https://example.com/research/b",
            "https://example.com/research/c",
        ]
        assert candidate_urls(connection, "source-a", limit=2) == [
            "https://example.com/research/a",
            "https://example.com/research/b",
        ]
        with pytest.raises(IngestionStateError, match="limit must be"):
            candidate_urls(connection, "source-a", limit=0)
    finally:
        connection.close()


def test_ingestion_schema_version_fails_closed(tmp_path):
    connection = connect_state(tmp_path / "state.sqlite3")
    try:
        ensure_ingestion_schema(connection)
        with connection:
            connection.execute(
                "UPDATE state_meta SET value = '999' WHERE key = 'ingestion_schema_version'"
            )
        with pytest.raises(IngestionStateError, match="unsupported ingestion state schema"):
            ensure_ingestion_schema(connection)
    finally:
        connection.close()
