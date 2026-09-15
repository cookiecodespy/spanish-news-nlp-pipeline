"""Local SQLite state for v2 discovery runs.

The ledger records observations only. It does not download source documents, promote
knowledge, or grant authority to discovered content.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_STATE_PATH = Path(".state/discovery.sqlite3")
SCHEMA_VERSION = 1


class DiscoveryStateError(RuntimeError):
    """Raised when discovery state cannot be recorded safely."""


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    source_id: str
    candidate_count: int
    new_count: int
    known_count: int
    new_candidates: list[str]
    known_candidates: list[str]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_state(path: Path = DEFAULT_STATE_PATH) -> sqlite3.Connection:
    """Open a local state database and ensure the v1 schema exists."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    _ensure_schema(connection)
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    with connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS state_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS discovery_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL CHECK (status IN ('running', 'success', 'error')),
                candidate_count INTEGER NOT NULL DEFAULT 0,
                new_count INTEGER NOT NULL DEFAULT 0,
                known_count INTEGER NOT NULL DEFAULT 0,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS candidate_documents (
                source_id TEXT NOT NULL,
                url TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                seen_count INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (source_id, url)
            );

            CREATE TABLE IF NOT EXISTS candidate_origins (
                source_id TEXT NOT NULL,
                url TEXT NOT NULL,
                entrypoint TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                seen_count INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (source_id, url, entrypoint),
                FOREIGN KEY (source_id, url)
                    REFERENCES candidate_documents(source_id, url)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS run_candidates (
                run_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                classification TEXT NOT NULL CHECK (classification IN ('new', 'known')),
                PRIMARY KEY (run_id, url),
                FOREIGN KEY (run_id) REFERENCES discovery_runs(id) ON DELETE CASCADE
            );
            """
        )

        existing = connection.execute(
            "SELECT value FROM state_meta WHERE key = 'schema_version'"
        ).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO state_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
        elif existing["value"] != str(SCHEMA_VERSION):
            raise DiscoveryStateError(
                "unsupported discovery state schema version: "
                f"{existing['value']} (expected {SCHEMA_VERSION})"
            )


def start_run(
    connection: sqlite3.Connection,
    source_id: str,
    *,
    started_at: str | None = None,
) -> int:
    """Create a running ledger entry and return its numeric run id."""
    if not source_id:
        raise DiscoveryStateError("source_id is required")
    with connection:
        cursor = connection.execute(
            """
            INSERT INTO discovery_runs(source_id, started_at, status)
            VALUES (?, ?, 'running')
            """,
            (source_id, started_at or utc_now()),
        )
    return int(cursor.lastrowid)


def _run_source(connection: sqlite3.Connection, run_id: int) -> str:
    row = connection.execute(
        "SELECT source_id, status FROM discovery_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None:
        raise DiscoveryStateError(f"unknown discovery run: {run_id}")
    if row["status"] != "running":
        raise DiscoveryStateError(
            f"discovery run {run_id} is already finalized as {row['status']}"
        )
    return str(row["source_id"])


def record_success(
    connection: sqlite3.Connection,
    run_id: int,
    results: Iterable[object],
    *,
    seen_at: str | None = None,
) -> RunSummary:
    """Record one successful source discovery run.

    ``results`` may be any objects exposing ``entrypoint`` and ``candidates`` attributes,
    including ``live_discovery.DiscoveryResult``. Candidate counts are per unique URL per
    run; origin counts are per URL+entrypoint per run.
    """
    source_id = _run_source(connection, run_id)
    timestamp = seen_at or utc_now()

    origins_by_url: dict[str, set[str]] = {}
    for result in results:
        entrypoint = getattr(result, "entrypoint", None)
        candidates = getattr(result, "candidates", None)
        if not isinstance(entrypoint, str) or not entrypoint:
            raise DiscoveryStateError("discovery result is missing entrypoint")
        if candidates is None:
            raise DiscoveryStateError("discovery result is missing candidates")
        for candidate in candidates:
            if not isinstance(candidate, str) or not candidate:
                raise DiscoveryStateError("candidate URL must be a non-empty string")
            origins_by_url.setdefault(candidate, set()).add(entrypoint)

    new_candidates: list[str] = []
    known_candidates: list[str] = []

    try:
        with connection:
            for url in sorted(origins_by_url):
                existing = connection.execute(
                    """
                    SELECT 1 FROM candidate_documents
                    WHERE source_id = ? AND url = ?
                    """,
                    (source_id, url),
                ).fetchone()

                if existing is None:
                    classification = "new"
                    new_candidates.append(url)
                    connection.execute(
                        """
                        INSERT INTO candidate_documents(
                            source_id, url, first_seen_at, last_seen_at, seen_count
                        ) VALUES (?, ?, ?, ?, 1)
                        """,
                        (source_id, url, timestamp, timestamp),
                    )
                else:
                    classification = "known"
                    known_candidates.append(url)
                    connection.execute(
                        """
                        UPDATE candidate_documents
                        SET last_seen_at = ?, seen_count = seen_count + 1
                        WHERE source_id = ? AND url = ?
                        """,
                        (timestamp, source_id, url),
                    )

                connection.execute(
                    """
                    INSERT INTO run_candidates(run_id, url, classification)
                    VALUES (?, ?, ?)
                    """,
                    (run_id, url, classification),
                )

                for entrypoint in sorted(origins_by_url[url]):
                    origin = connection.execute(
                        """
                        SELECT 1 FROM candidate_origins
                        WHERE source_id = ? AND url = ? AND entrypoint = ?
                        """,
                        (source_id, url, entrypoint),
                    ).fetchone()
                    if origin is None:
                        connection.execute(
                            """
                            INSERT INTO candidate_origins(
                                source_id, url, entrypoint,
                                first_seen_at, last_seen_at, seen_count
                            ) VALUES (?, ?, ?, ?, ?, 1)
                            """,
                            (source_id, url, entrypoint, timestamp, timestamp),
                        )
                    else:
                        connection.execute(
                            """
                            UPDATE candidate_origins
                            SET last_seen_at = ?, seen_count = seen_count + 1
                            WHERE source_id = ? AND url = ? AND entrypoint = ?
                            """,
                            (timestamp, source_id, url, entrypoint),
                        )

            candidate_count = len(origins_by_url)
            connection.execute(
                """
                UPDATE discovery_runs
                SET finished_at = ?, status = 'success', candidate_count = ?,
                    new_count = ?, known_count = ?, error = NULL
                WHERE id = ?
                """,
                (
                    timestamp,
                    candidate_count,
                    len(new_candidates),
                    len(known_candidates),
                    run_id,
                ),
            )
    except sqlite3.DatabaseError as exc:
        raise DiscoveryStateError(f"failed to record discovery run {run_id}: {exc}") from exc

    return RunSummary(
        run_id=run_id,
        source_id=source_id,
        candidate_count=len(origins_by_url),
        new_count=len(new_candidates),
        known_count=len(known_candidates),
        new_candidates=new_candidates,
        known_candidates=known_candidates,
    )


def record_failure(
    connection: sqlite3.Connection,
    run_id: int,
    error: str,
    *,
    finished_at: str | None = None,
) -> None:
    """Finalize a running discovery run as an honest failure."""
    _run_source(connection, run_id)
    message = str(error).strip() or "unknown discovery error"
    with connection:
        connection.execute(
            """
            UPDATE discovery_runs
            SET finished_at = ?, status = 'error', error = ?,
                candidate_count = 0, new_count = 0, known_count = 0
            WHERE id = ?
            """,
            (finished_at or utc_now(), message, run_id),
        )


def latest_run(
    connection: sqlite3.Connection,
    source_id: str | None = None,
) -> sqlite3.Row | None:
    """Return the newest run, optionally limited to one source."""
    if source_id is None:
        return connection.execute(
            "SELECT * FROM discovery_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return connection.execute(
        """
        SELECT * FROM discovery_runs
        WHERE source_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (source_id,),
    ).fetchone()
