import sqlite3
from types import SimpleNamespace

import pytest

from research_pipeline.discovery_state import (
    DiscoveryStateError,
    connect_state,
    latest_run,
    record_failure,
    record_success,
    start_run,
)


def result(entrypoint, candidates):
    return SimpleNamespace(entrypoint=entrypoint, candidates=candidates)


def test_first_run_marks_candidates_new_and_preserves_origins(tmp_path):
    connection = connect_state(tmp_path / "state.sqlite3")
    run_id = start_run(
        connection,
        "example-source",
        started_at="2026-09-15T06:00:00+00:00",
    )

    summary = record_success(
        connection,
        run_id,
        [
            result("https://example.com/research/", ["https://example.com/a", "https://example.com/b"]),
            result("https://example.com/pubs/", ["https://example.com/a"]),
        ],
        seen_at="2026-09-15T06:01:00+00:00",
    )

    assert summary.candidate_count == 2
    assert summary.new_count == 2
    assert summary.known_count == 0
    assert summary.new_candidates == [
        "https://example.com/a",
        "https://example.com/b",
    ]

    origins = connection.execute(
        """
        SELECT url, entrypoint, seen_count
        FROM candidate_origins
        ORDER BY url, entrypoint
        """
    ).fetchall()
    assert [(row["url"], row["entrypoint"], row["seen_count"]) for row in origins] == [
        ("https://example.com/a", "https://example.com/pubs/", 1),
        ("https://example.com/a", "https://example.com/research/", 1),
        ("https://example.com/b", "https://example.com/research/", 1),
    ]


def test_repeated_run_marks_existing_candidates_known(tmp_path):
    connection = connect_state(tmp_path / "state.sqlite3")

    first = start_run(connection, "example-source")
    record_success(
        connection,
        first,
        [result("https://example.com/research/", ["https://example.com/a"])],
        seen_at="2026-09-15T06:01:00+00:00",
    )

    second = start_run(connection, "example-source")
    summary = record_success(
        connection,
        second,
        [result("https://example.com/research/", ["https://example.com/a"])],
        seen_at="2026-09-15T07:01:00+00:00",
    )

    assert summary.new_count == 0
    assert summary.known_count == 1
    assert summary.known_candidates == ["https://example.com/a"]

    document = connection.execute(
        """
        SELECT first_seen_at, last_seen_at, seen_count
        FROM candidate_documents
        WHERE source_id = ? AND url = ?
        """,
        ("example-source", "https://example.com/a"),
    ).fetchone()
    assert document["first_seen_at"] == "2026-09-15T06:01:00+00:00"
    assert document["last_seen_at"] == "2026-09-15T07:01:00+00:00"
    assert document["seen_count"] == 2


def test_failed_run_is_recorded_without_fabricating_candidates(tmp_path):
    connection = connect_state(tmp_path / "state.sqlite3")
    run_id = start_run(connection, "example-source")

    record_failure(
        connection,
        run_id,
        "robots.txt blocked entrypoint",
        finished_at="2026-09-15T06:02:00+00:00",
    )

    row = latest_run(connection, "example-source")
    assert row is not None
    assert row["status"] == "error"
    assert row["candidate_count"] == 0
    assert row["new_count"] == 0
    assert row["known_count"] == 0
    assert row["error"] == "robots.txt blocked entrypoint"
    assert connection.execute("SELECT COUNT(*) FROM candidate_documents").fetchone()[0] == 0


def test_finalized_run_cannot_be_recorded_twice(tmp_path):
    connection = connect_state(tmp_path / "state.sqlite3")
    run_id = start_run(connection, "example-source")
    record_success(connection, run_id, [])

    with pytest.raises(DiscoveryStateError, match="already finalized"):
        record_success(connection, run_id, [])


def test_schema_version_mismatch_fails_closed(tmp_path):
    path = tmp_path / "state.sqlite3"
    connection = connect_state(path)
    with connection:
        connection.execute(
            "UPDATE state_meta SET value = '999' WHERE key = 'schema_version'"
        )
    connection.close()

    with pytest.raises(DiscoveryStateError, match="unsupported discovery state schema version"):
        connect_state(path)
