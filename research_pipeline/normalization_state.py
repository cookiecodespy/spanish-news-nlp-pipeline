"""Local provenance ledger for deterministic normalized research artifacts."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from research_pipeline.discovery_state import utc_now

NORMALIZATION_SCHEMA_VERSION = 1


class NormalizationStateError(RuntimeError):
    """Raised when normalization state cannot be validated or recorded safely."""


@dataclass(frozen=True)
class NormalizationObservation:
    observation_id: int
    source_id: str
    requested_url: str
    ingestion_observation_id: int
    raw_sha256: str
    extractor_name: str
    extractor_version: str
    status: str
    classification: str | None
    normalized_sha256: str | None
    artifact_path: str | None
    title: str | None
    block_count: int | None
    char_count: int | None
    normalized_at: str
    error: str | None


def ensure_normalization_schema(connection: sqlite3.Connection) -> None:
    """Create and validate the independent Phase 3A normalization schema."""
    try:
        with connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS normalization_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    requested_url TEXT NOT NULL,
                    ingestion_observation_id INTEGER NOT NULL,
                    raw_sha256 TEXT NOT NULL,
                    extractor_name TEXT NOT NULL,
                    extractor_version TEXT NOT NULL,
                    normalized_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('success', 'error')),
                    classification TEXT CHECK (
                        classification IS NULL OR
                        classification IN ('NEW', 'UNCHANGED', 'CHANGED')
                    ),
                    normalized_sha256 TEXT,
                    artifact_path TEXT,
                    title TEXT,
                    block_count INTEGER,
                    char_count INTEGER,
                    error TEXT,
                    FOREIGN KEY (ingestion_observation_id)
                        REFERENCES ingestion_observations(id) ON DELETE RESTRICT,
                    CHECK (
                        (status = 'success' AND classification IS NOT NULL AND
                         normalized_sha256 IS NOT NULL AND artifact_path IS NOT NULL AND
                         block_count IS NOT NULL AND block_count > 0 AND
                         char_count IS NOT NULL AND char_count > 0 AND error IS NULL)
                        OR
                        (status = 'error' AND classification IS NULL AND
                         normalized_sha256 IS NULL AND artifact_path IS NULL AND
                         block_count IS NULL AND char_count IS NULL AND error IS NOT NULL)
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_normalization_source_url
                ON normalization_observations(
                    source_id, requested_url, extractor_name, extractor_version, id DESC
                );
                """
            )

            key = "normalization_schema_version"
            existing = connection.execute(
                "SELECT value FROM state_meta WHERE key = ?", (key,)
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO state_meta(key, value) VALUES(?, ?)",
                    (key, str(NORMALIZATION_SCHEMA_VERSION)),
                )
            elif existing["value"] != str(NORMALIZATION_SCHEMA_VERSION):
                raise NormalizationStateError(
                    "unsupported normalization state schema version: "
                    f"{existing['value']} (expected {NORMALIZATION_SCHEMA_VERSION})"
                )
    except sqlite3.DatabaseError as exc:
        raise NormalizationStateError(
            f"failed to initialize normalization state: {exc}"
        ) from exc


def latest_success(
    connection: sqlite3.Connection,
    source_id: str,
    requested_url: str,
    extractor_name: str,
    extractor_version: str,
) -> sqlite3.Row | None:
    """Return the prior success for the same URL and exact extractor version."""
    ensure_normalization_schema(connection)
    return connection.execute(
        """
        SELECT * FROM normalization_observations
        WHERE source_id = ? AND requested_url = ? AND status = 'success'
          AND extractor_name = ? AND extractor_version = ?
        ORDER BY id DESC LIMIT 1
        """,
        (source_id, requested_url, extractor_name, extractor_version),
    ).fetchone()


def classify_normalized(previous_sha: str | None, current_sha: str) -> str:
    if not current_sha:
        raise NormalizationStateError("current normalized SHA-256 is required")
    if previous_sha is None:
        return "NEW"
    return "UNCHANGED" if previous_sha == current_sha else "CHANGED"


def record_success(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    requested_url: str,
    ingestion_observation_id: int,
    raw_sha256: str,
    extractor_name: str,
    extractor_version: str,
    normalized_sha256: str,
    artifact_path: str,
    title: str | None,
    block_count: int,
    char_count: int,
    normalized_at: str | None = None,
) -> NormalizationObservation:
    """Record normalized evidence and compare only against the same extractor version."""
    ensure_normalization_schema(connection)
    previous = latest_success(
        connection,
        source_id,
        requested_url,
        extractor_name,
        extractor_version,
    )
    classification = classify_normalized(
        previous["normalized_sha256"] if previous else None,
        normalized_sha256,
    )
    timestamp = normalized_at or utc_now()

    try:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO normalization_observations(
                    source_id, requested_url, ingestion_observation_id, raw_sha256,
                    extractor_name, extractor_version, normalized_at, status,
                    classification, normalized_sha256, artifact_path, title,
                    block_count, char_count, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'success', ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    source_id,
                    requested_url,
                    ingestion_observation_id,
                    raw_sha256,
                    extractor_name,
                    extractor_version,
                    timestamp,
                    classification,
                    normalized_sha256,
                    artifact_path,
                    title,
                    block_count,
                    char_count,
                ),
            )
    except sqlite3.DatabaseError as exc:
        raise NormalizationStateError(
            f"failed to record normalization success: {exc}"
        ) from exc

    return NormalizationObservation(
        observation_id=int(cursor.lastrowid),
        source_id=source_id,
        requested_url=requested_url,
        ingestion_observation_id=ingestion_observation_id,
        raw_sha256=raw_sha256,
        extractor_name=extractor_name,
        extractor_version=extractor_version,
        status="success",
        classification=classification,
        normalized_sha256=normalized_sha256,
        artifact_path=artifact_path,
        title=title,
        block_count=block_count,
        char_count=char_count,
        normalized_at=timestamp,
        error=None,
    )


def record_failure(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    requested_url: str,
    ingestion_observation_id: int,
    raw_sha256: str,
    extractor_name: str,
    extractor_version: str,
    error: str,
    normalized_at: str | None = None,
) -> NormalizationObservation:
    """Record a failed normalization without fabricating artifact identity."""
    ensure_normalization_schema(connection)
    timestamp = normalized_at or utc_now()
    message = str(error).strip() or "unknown normalization error"

    try:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO normalization_observations(
                    source_id, requested_url, ingestion_observation_id, raw_sha256,
                    extractor_name, extractor_version, normalized_at, status,
                    classification, normalized_sha256, artifact_path, title,
                    block_count, char_count, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'error', NULL, NULL, NULL, NULL, NULL, NULL, ?)
                """,
                (
                    source_id,
                    requested_url,
                    ingestion_observation_id,
                    raw_sha256,
                    extractor_name,
                    extractor_version,
                    timestamp,
                    message,
                ),
            )
    except sqlite3.DatabaseError as exc:
        raise NormalizationStateError(
            f"failed to record normalization failure: {exc}"
        ) from exc

    return NormalizationObservation(
        observation_id=int(cursor.lastrowid),
        source_id=source_id,
        requested_url=requested_url,
        ingestion_observation_id=ingestion_observation_id,
        raw_sha256=raw_sha256,
        extractor_name=extractor_name,
        extractor_version=extractor_version,
        status="error",
        classification=None,
        normalized_sha256=None,
        artifact_path=None,
        title=None,
        block_count=None,
        char_count=None,
        normalized_at=timestamp,
        error=message,
    )


def latest_ingestion_rows(
    connection: sqlite3.Connection,
    source_id: str,
    *,
    limit: int = 1,
) -> list[sqlite3.Row]:
    """Return the latest successful raw observation for each URL, deterministically."""
    if limit < 1:
        raise NormalizationStateError("limit must be >= 1")
    ensure_normalization_schema(connection)
    rows = connection.execute(
        """
        SELECT io.*
        FROM ingestion_observations AS io
        JOIN (
            SELECT requested_url, MAX(id) AS max_id
            FROM ingestion_observations
            WHERE source_id = ? AND status = 'success'
            GROUP BY requested_url
        ) AS latest ON latest.max_id = io.id
        WHERE io.source_id = ?
        ORDER BY io.fetched_at ASC, io.requested_url ASC
        LIMIT ?
        """,
        (source_id, source_id, limit),
    ).fetchall()
    return list(rows)
