"""Local state for exact-byte HTML ingestion observations.

Ingestion state lives in the same SQLite database as discovery state, but keeps its own
schema marker so the two subsystems can evolve without pretending they are one migration
unit. Observations are evidence only; a raw-byte change is not a semantic change.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from research_pipeline.discovery_state import DiscoveryStateError, utc_now

INGESTION_SCHEMA_VERSION = 1


class IngestionStateError(RuntimeError):
    """Raised when ingestion state cannot be validated or recorded safely."""


@dataclass(frozen=True)
class IngestionObservation:
    observation_id: int
    source_id: str
    requested_url: str
    final_url: str | None
    status: str
    classification: str | None
    content_type: str | None
    bytes_read: int | None
    sha256: str | None
    object_path: str | None
    fetched_at: str
    error: str | None


def ensure_ingestion_schema(connection: sqlite3.Connection) -> None:
    """Create and validate the Phase 2A ingestion tables in an existing state DB."""
    try:
        with connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ingestion_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    requested_url TEXT NOT NULL,
                    final_url TEXT,
                    fetched_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('success', 'error')),
                    classification TEXT CHECK (
                        classification IS NULL OR
                        classification IN ('NEW', 'UNCHANGED', 'CHANGED')
                    ),
                    content_type TEXT,
                    bytes_read INTEGER,
                    sha256 TEXT,
                    object_path TEXT,
                    error TEXT,
                    CHECK (
                        (status = 'success' AND classification IS NOT NULL AND
                         final_url IS NOT NULL AND content_type IS NOT NULL AND
                         bytes_read IS NOT NULL AND bytes_read >= 0 AND
                         sha256 IS NOT NULL AND object_path IS NOT NULL AND error IS NULL)
                        OR
                        (status = 'error' AND classification IS NULL AND
                         sha256 IS NULL AND object_path IS NULL AND error IS NOT NULL)
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_ingestion_source_url
                ON ingestion_observations(source_id, requested_url, id DESC);
                """
            )

            key = "ingestion_schema_version"
            existing = connection.execute(
                "SELECT value FROM state_meta WHERE key = ?", (key,)
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO state_meta(key, value) VALUES(?, ?)",
                    (key, str(INGESTION_SCHEMA_VERSION)),
                )
            elif existing["value"] != str(INGESTION_SCHEMA_VERSION):
                raise IngestionStateError(
                    "unsupported ingestion state schema version: "
                    f"{existing['value']} (expected {INGESTION_SCHEMA_VERSION})"
                )
    except sqlite3.DatabaseError as exc:
        raise IngestionStateError(f"failed to initialize ingestion state: {exc}") from exc


def require_discovered_candidate(
    connection: sqlite3.Connection,
    source_id: str,
    requested_url: str,
) -> None:
    """Fail closed unless discovery previously observed this URL for this source."""
    row = connection.execute(
        """
        SELECT 1 FROM candidate_documents
        WHERE source_id = ? AND url = ?
        """,
        (source_id, requested_url),
    ).fetchone()
    if row is None:
        raise IngestionStateError(
            f"URL was not discovered for source {source_id}: {requested_url}"
        )


def latest_success(
    connection: sqlite3.Connection,
    source_id: str,
    requested_url: str,
) -> sqlite3.Row | None:
    """Return the latest successful raw observation for one discovered source URL."""
    ensure_ingestion_schema(connection)
    return connection.execute(
        """
        SELECT * FROM ingestion_observations
        WHERE source_id = ? AND requested_url = ? AND status = 'success'
        ORDER BY id DESC
        LIMIT 1
        """,
        (source_id, requested_url),
    ).fetchone()


def classify_sha(previous_sha: str | None, current_sha: str) -> str:
    """Classify exact-byte change status without claiming semantic equivalence."""
    if not current_sha:
        raise IngestionStateError("current SHA-256 is required")
    if previous_sha is None:
        return "NEW"
    return "UNCHANGED" if previous_sha == current_sha else "CHANGED"


def record_success(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    requested_url: str,
    final_url: str,
    content_type: str,
    bytes_read: int,
    sha256: str,
    object_path: str,
    fetched_at: str | None = None,
) -> IngestionObservation:
    """Record one successful exact-byte fetch and classify it vs the prior success."""
    ensure_ingestion_schema(connection)
    require_discovered_candidate(connection, source_id, requested_url)
    previous = latest_success(connection, source_id, requested_url)
    classification = classify_sha(previous["sha256"] if previous else None, sha256)
    timestamp = fetched_at or utc_now()

    try:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO ingestion_observations(
                    source_id, requested_url, final_url, fetched_at, status,
                    classification, content_type, bytes_read, sha256, object_path, error
                ) VALUES (?, ?, ?, ?, 'success', ?, ?, ?, ?, ?, NULL)
                """,
                (
                    source_id,
                    requested_url,
                    final_url,
                    timestamp,
                    classification,
                    content_type,
                    bytes_read,
                    sha256,
                    object_path,
                ),
            )
    except sqlite3.DatabaseError as exc:
        raise IngestionStateError(f"failed to record ingestion success: {exc}") from exc

    return IngestionObservation(
        observation_id=int(cursor.lastrowid),
        source_id=source_id,
        requested_url=requested_url,
        final_url=final_url,
        status="success",
        classification=classification,
        content_type=content_type,
        bytes_read=bytes_read,
        sha256=sha256,
        object_path=object_path,
        fetched_at=timestamp,
        error=None,
    )


def record_failure(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    requested_url: str,
    error: str,
    final_url: str | None = None,
    content_type: str | None = None,
    bytes_read: int | None = None,
    fetched_at: str | None = None,
) -> IngestionObservation:
    """Record an honest failed ingestion without fabricating a hash/classification."""
    ensure_ingestion_schema(connection)
    require_discovered_candidate(connection, source_id, requested_url)
    timestamp = fetched_at or utc_now()
    message = str(error).strip() or "unknown ingestion error"

    try:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO ingestion_observations(
                    source_id, requested_url, final_url, fetched_at, status,
                    classification, content_type, bytes_read, sha256, object_path, error
                ) VALUES (?, ?, ?, ?, 'error', NULL, ?, ?, NULL, NULL, ?)
                """,
                (
                    source_id,
                    requested_url,
                    final_url,
                    timestamp,
                    content_type,
                    bytes_read,
                    message,
                ),
            )
    except sqlite3.DatabaseError as exc:
        raise IngestionStateError(f"failed to record ingestion failure: {exc}") from exc

    return IngestionObservation(
        observation_id=int(cursor.lastrowid),
        source_id=source_id,
        requested_url=requested_url,
        final_url=final_url,
        status="error",
        classification=None,
        content_type=content_type,
        bytes_read=bytes_read,
        sha256=None,
        object_path=None,
        fetched_at=timestamp,
        error=message,
    )


def candidate_urls(
    connection: sqlite3.Connection,
    source_id: str,
    *,
    limit: int | None = None,
) -> list[str]:
    """Return discovered candidates deterministically, oldest first then URL."""
    if limit is not None and limit < 1:
        raise IngestionStateError("limit must be >= 1")
    sql = """
        SELECT url FROM candidate_documents
        WHERE source_id = ?
        ORDER BY first_seen_at ASC, url ASC
    """
    params: tuple[object, ...] = (source_id,)
    if limit is not None:
        sql += " LIMIT ?"
        params += (limit,)
    return [str(row["url"]) for row in connection.execute(sql, params).fetchall()]
