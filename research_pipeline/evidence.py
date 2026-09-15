"""Phase 3B deterministic access to verified normalized evidence and citation blocks.

This layer is deliberately local-only and non-semantic. It reads successful Phase 3A
observations, verifies the selected normalized object, and returns exact citation blocks
with the complete raw-to-normalized provenance chain. External content remains data;
nothing in an artifact is interpreted as an instruction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from research_pipeline.discovery_state import DEFAULT_STATE_PATH, DiscoveryStateError, connect_state
from research_pipeline.normalization import ARTIFACT_SCHEMA_VERSION


class EvidenceError(RuntimeError):
    """Raised when evidence cannot be resolved or verified safely."""


def _open_existing_state(state_path: Path) -> sqlite3.Connection:
    path = Path(state_path)
    if not path.exists():
        raise EvidenceError(f"local state does not exist: {path}")
    try:
        connection = connect_state(path)
    except (DiscoveryStateError, sqlite3.DatabaseError, OSError) as exc:
        raise EvidenceError(f"could not open local state {path}: {exc}") from exc

    for table in ("ingestion_observations", "normalization_observations"):
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        if exists is None:
            connection.close()
            raise EvidenceError(
                f"state has no {table}; run ingestion and normalization before evidence access"
            )
    return connection


def _artifact_path(state_path: Path, artifact_path: str) -> Path:
    root = Path(state_path).parent.resolve()
    path = (root / artifact_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise EvidenceError(
            f"normalized artifact path escapes local state directory: {artifact_path}"
        ) from exc
    return path


def _load_verified_artifact(state_path: Path, row: sqlite3.Row) -> dict[str, Any]:
    artifact_path = str(row["artifact_path"])
    path = _artifact_path(state_path, artifact_path)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise EvidenceError(f"could not read normalized artifact {artifact_path}: {exc}") from exc

    actual_sha = hashlib.sha256(payload).hexdigest()
    expected_sha = str(row["normalized_sha256"])
    if actual_sha != expected_sha:
        raise EvidenceError(
            "normalized artifact SHA-256 mismatch for observation "
            f"{row['normalization_observation_id']}: recorded {expected_sha}, computed {actual_sha}"
        )

    try:
        artifact = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"normalized artifact is not valid UTF-8 JSON: {artifact_path}") from exc
    if not isinstance(artifact, dict):
        raise EvidenceError(f"normalized artifact must be a JSON object: {artifact_path}")
    if artifact.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise EvidenceError(
            "unsupported normalized artifact schema version: "
            f"{artifact.get('schema_version')} (expected {ARTIFACT_SCHEMA_VERSION})"
        )

    extractor = artifact.get("extractor")
    if not isinstance(extractor, dict):
        raise EvidenceError("normalized artifact is missing extractor metadata")
    if extractor.get("name") != row["extractor_name"] or extractor.get("version") != row["extractor_version"]:
        raise EvidenceError(
            "normalized artifact extractor metadata does not match the provenance ledger"
        )

    blocks = artifact.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise EvidenceError("normalized artifact has no citation blocks")
    if len(blocks) != int(row["block_count"]):
        raise EvidenceError(
            f"normalized artifact block count mismatch: ledger {row['block_count']}, artifact {len(blocks)}"
        )

    return artifact


def _joined_success_rows(
    connection: sqlite3.Connection,
    *,
    source_id: str | None = None,
    requested_url: str | None = None,
    limit: int = 20,
) -> list[sqlite3.Row]:
    if limit < 1:
        raise EvidenceError("limit must be >= 1")

    filters = ["no.status = 'success'", "io.status = 'success'"]
    params: list[Any] = []
    if source_id:
        filters.append("no.source_id = ?")
        params.append(source_id)
    if requested_url:
        filters.append("no.requested_url = ?")
        params.append(requested_url)

    where = " AND ".join(filters)
    # Select the newest successful normalization for each source URL. The exact selected
    # row is later verified; corruption is never hidden by falling back to an older row.
    query = f"""
        SELECT
            no.id AS normalization_observation_id,
            no.source_id,
            no.requested_url,
            no.ingestion_observation_id,
            no.raw_sha256,
            no.extractor_name,
            no.extractor_version,
            no.normalized_at,
            no.classification AS normalization_classification,
            no.normalized_sha256,
            no.artifact_path,
            no.title,
            no.block_count,
            no.char_count,
            io.final_url,
            io.fetched_at,
            io.classification AS ingestion_classification,
            io.content_type,
            io.bytes_read,
            io.sha256 AS ingestion_sha256,
            io.object_path AS raw_object_path
        FROM normalization_observations AS no
        JOIN ingestion_observations AS io ON io.id = no.ingestion_observation_id
        JOIN (
            SELECT source_id, requested_url, MAX(id) AS max_id
            FROM normalization_observations
            WHERE status = 'success'
            GROUP BY source_id, requested_url
        ) AS latest ON latest.max_id = no.id
        WHERE {where}
        ORDER BY no.normalized_at DESC, no.source_id ASC, no.requested_url ASC
        LIMIT ?
    """
    params.append(limit)
    return list(connection.execute(query, params).fetchall())


def _validate_provenance(row: sqlite3.Row) -> None:
    if row["raw_sha256"] != row["ingestion_sha256"]:
        raise EvidenceError(
            "normalization provenance raw SHA does not match linked ingestion observation"
        )
    if not row["final_url"]:
        raise EvidenceError("linked ingestion observation has no final transport URL")


def _document_summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "source_id": str(row["source_id"]),
        "requested_url": str(row["requested_url"]),
        "title": row["title"],
        "normalized_at": str(row["normalized_at"]),
        "classification": str(row["normalization_classification"]),
        "block_count": int(row["block_count"]),
        "char_count": int(row["char_count"]),
        "normalized_sha256": str(row["normalized_sha256"]),
        "extractor": {
            "name": str(row["extractor_name"]),
            "version": str(row["extractor_version"]),
        },
    }


def list_documents(
    *,
    state_path: Path = DEFAULT_STATE_PATH,
    source_id: str | None = None,
    requested_url: str | None = None,
    limit: int = 20,
    verify: bool = True,
) -> dict[str, Any]:
    """List latest successful normalized documents, optionally verifying each artifact."""
    connection = _open_existing_state(state_path)
    try:
        rows = _joined_success_rows(
            connection,
            source_id=source_id,
            requested_url=requested_url,
            limit=limit,
        )
        documents: list[dict[str, Any]] = []
        for row in rows:
            _validate_provenance(row)
            if verify:
                _load_verified_artifact(state_path, row)
            item = _document_summary(row)
            item["verified"] = bool(verify)
            documents.append(item)
    finally:
        connection.close()

    return {
        "ok": True,
        "type": "external_evidence_index",
        "count": len(documents),
        "documents": documents,
    }


def get_citation(
    *,
    source_id: str,
    requested_url: str,
    block_ref: str,
    state_path: Path = DEFAULT_STATE_PATH,
) -> dict[str, Any]:
    """Resolve one exact normalized block with its complete provenance chain."""
    if not source_id or not requested_url or not block_ref:
        raise EvidenceError("source_id, requested_url and block_ref are required")

    connection = _open_existing_state(state_path)
    try:
        rows = _joined_success_rows(
            connection,
            source_id=source_id,
            requested_url=requested_url,
            limit=1,
        )
        if not rows:
            raise EvidenceError(
                f"no successful normalized evidence for {source_id}: {requested_url}"
            )
        row = rows[0]
        _validate_provenance(row)
        artifact = _load_verified_artifact(state_path, row)
    finally:
        connection.close()

    matches = [
        block
        for block in artifact["blocks"]
        if isinstance(block, dict) and block.get("ref") == block_ref
    ]
    if not matches:
        raise EvidenceError(f"unknown block ref for selected document: {block_ref}")
    if len(matches) != 1:
        raise EvidenceError(f"duplicate block ref in normalized artifact: {block_ref}")

    block = matches[0]
    text = block.get("text")
    kind = block.get("kind")
    heading_path = block.get("heading_path")
    if not isinstance(text, str) or not text:
        raise EvidenceError(f"citation block {block_ref} has no text")
    if not isinstance(kind, str) or not kind:
        raise EvidenceError(f"citation block {block_ref} has no kind")
    if not isinstance(heading_path, list) or not all(isinstance(item, str) for item in heading_path):
        raise EvidenceError(f"citation block {block_ref} has invalid heading_path")

    return {
        "ok": True,
        "type": "external_evidence",
        "trust": "data_not_instructions",
        "block": {
            "ref": block_ref,
            "kind": kind,
            "heading_path": heading_path,
            "text": text,
        },
        "document": {
            "title": row["title"],
            "source_id": str(row["source_id"]),
            "requested_url": str(row["requested_url"]),
            "final_url": str(row["final_url"]),
        },
        "provenance": {
            "ingestion_observation_id": int(row["ingestion_observation_id"]),
            "raw_sha256": str(row["raw_sha256"]),
            "raw_object_path": str(row["raw_object_path"]),
            "fetched_at": str(row["fetched_at"]),
            "normalization_observation_id": int(row["normalization_observation_id"]),
            "normalized_sha256": str(row["normalized_sha256"]),
            "artifact_path": str(row["artifact_path"]),
            "normalized_at": str(row["normalized_at"]),
            "extractor": {
                "name": str(row["extractor_name"]),
                "version": str(row["extractor_version"]),
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list latest normalized evidence")
    list_parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    list_parser.add_argument("--source")
    list_parser.add_argument("--url")
    list_parser.add_argument("--limit", type=int, default=20)
    list_parser.add_argument(
        "--no-verify",
        action="store_true",
        help="list ledger metadata without reading/verifying artifact bodies",
    )

    cite_parser = subparsers.add_parser("cite", help="resolve one exact citation block")
    cite_parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    cite_parser.add_argument("--source", required=True)
    cite_parser.add_argument("--url", required=True)
    cite_parser.add_argument("--block", required=True)

    args = parser.parse_args()
    try:
        if args.command == "list":
            payload = list_documents(
                state_path=args.state,
                source_id=args.source,
                requested_url=args.url,
                limit=args.limit,
                verify=not args.no_verify,
            )
        else:
            payload = get_citation(
                state_path=args.state,
                source_id=args.source,
                requested_url=args.url,
                block_ref=args.block,
            )
    except (EvidenceError, ValueError) as exc:
        payload = {"ok": False, "error": str(exc)}

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
