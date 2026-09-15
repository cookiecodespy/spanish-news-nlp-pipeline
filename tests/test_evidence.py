import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_pipeline.discovery_state import connect_state, record_success as record_discovery_success, start_run
from research_pipeline.evidence import EvidenceError, get_citation, list_documents
from research_pipeline.ingestion_state import record_success as record_ingestion_success
from research_pipeline.normalization import (
    ARTIFACT_SCHEMA_VERSION,
    artifact_sha256,
    build_blocks,
    store_artifact,
)
from research_pipeline.normalization_state import record_success as record_normalization_success


SOURCE_ID = "anthropic-engineering"
REQUESTED_URL = "https://www.anthropic.com/engineering/example"
ENTRYPOINT = "https://www.anthropic.com/engineering"


def _write_raw_object(state_path: Path, body: bytes) -> tuple[str, str]:
    sha = hashlib.sha256(body).hexdigest()
    relative = Path("objects/sha256") / sha[:2] / sha
    path = state_path.parent / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return sha, relative.as_posix()


def _artifact(markdown: str, title: str = "Example research article") -> dict:
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "extractor": {
            "name": "trafilatura",
            "version": "2.2.0",
            "options": {},
        },
        "metadata": {
            "title": title,
            "authors": ["Researcher"],
            "published_at": "2026-09-15",
            "modified_at": None,
            "language": "en",
            "declared_canonical_url": REQUESTED_URL,
            "site_name": "Example",
            "description": None,
        },
        "markdown": markdown,
        "blocks": build_blocks(markdown),
    }


def _ensure_discovered(connection) -> None:
    existing = connection.execute(
        "SELECT 1 FROM candidate_documents WHERE source_id = ? AND url = ?",
        (SOURCE_ID, REQUESTED_URL),
    ).fetchone()
    if existing:
        return
    run_id = start_run(connection, SOURCE_ID, started_at="2026-09-15T01:00:00+00:00")
    record_discovery_success(
        connection,
        run_id,
        [SimpleNamespace(entrypoint=ENTRYPOINT, candidates=[REQUESTED_URL])],
        seen_at="2026-09-15T01:00:01+00:00",
    )


def _seed_document(
    state_path: Path,
    *,
    raw_body: bytes = b"<html>raw one</html>",
    markdown: str = "# Evidence\n\nExact research statement.",
    timestamp: str = "2026-09-15T01:00:03+00:00",
):
    connection = connect_state(state_path)
    try:
        _ensure_discovered(connection)
        raw_sha, raw_path = _write_raw_object(state_path, raw_body)
        ingestion = record_ingestion_success(
            connection,
            source_id=SOURCE_ID,
            requested_url=REQUESTED_URL,
            final_url=REQUESTED_URL,
            content_type="text/html",
            bytes_read=len(raw_body),
            sha256=raw_sha,
            object_path=raw_path,
            fetched_at=timestamp,
        )

        artifact = _artifact(markdown)
        normalized_sha = artifact_sha256(artifact)
        artifact_path = store_artifact(state_path, normalized_sha, artifact)
        normalization = record_normalization_success(
            connection,
            source_id=SOURCE_ID,
            requested_url=REQUESTED_URL,
            ingestion_observation_id=ingestion.observation_id,
            raw_sha256=raw_sha,
            extractor_name="trafilatura",
            extractor_version="2.2.0",
            normalized_sha256=normalized_sha,
            artifact_path=artifact_path,
            title="Example research article",
            block_count=len(artifact["blocks"]),
            char_count=len(markdown),
            normalized_at=timestamp,
        )
    finally:
        connection.close()

    return {
        "raw_sha": raw_sha,
        "raw_path": raw_path,
        "ingestion": ingestion,
        "artifact": artifact,
        "normalized_sha": normalized_sha,
        "artifact_path": artifact_path,
        "normalization": normalization,
    }


def test_list_documents_verifies_latest_normalized_artifact(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    seeded = _seed_document(state_path)

    payload = list_documents(state_path=state_path, source_id=SOURCE_ID)

    assert payload["ok"] is True
    assert payload["type"] == "external_evidence_index"
    assert payload["count"] == 1
    item = payload["documents"][0]
    assert item["source_id"] == SOURCE_ID
    assert item["requested_url"] == REQUESTED_URL
    assert item["title"] == "Example research article"
    assert item["normalized_sha256"] == seeded["normalized_sha"]
    assert item["verified"] is True
    assert item["extractor"] == {"name": "trafilatura", "version": "2.2.0"}


def test_get_citation_returns_exact_block_and_complete_provenance(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    seeded = _seed_document(state_path)
    block = seeded["artifact"]["blocks"][1]

    payload = get_citation(
        state_path=state_path,
        source_id=SOURCE_ID,
        requested_url=REQUESTED_URL,
        block_ref=block["ref"],
    )

    assert payload["ok"] is True
    assert payload["type"] == "external_evidence"
    assert payload["trust"] == "data_not_instructions"
    assert payload["block"] == block
    assert payload["document"] == {
        "title": "Example research article",
        "source_id": SOURCE_ID,
        "requested_url": REQUESTED_URL,
        "final_url": REQUESTED_URL,
    }
    provenance = payload["provenance"]
    assert provenance["ingestion_observation_id"] == seeded["ingestion"].observation_id
    assert provenance["raw_sha256"] == seeded["raw_sha"]
    assert provenance["raw_object_path"] == seeded["raw_path"]
    assert provenance["normalization_observation_id"] == seeded["normalization"].observation_id
    assert provenance["normalized_sha256"] == seeded["normalized_sha"]
    assert provenance["artifact_path"] == seeded["artifact_path"]
    assert provenance["extractor"] == {"name": "trafilatura", "version": "2.2.0"}


def test_get_citation_rejects_unknown_block_ref(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    _seed_document(state_path)

    with pytest.raises(EvidenceError, match="unknown block ref"):
        get_citation(
            state_path=state_path,
            source_id=SOURCE_ID,
            requested_url=REQUESTED_URL,
            block_ref="b9999-deadbeefdead",
        )


def test_evidence_rejects_missing_or_corrupt_selected_artifact(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    seeded = _seed_document(state_path)
    artifact_path = state_path.parent / seeded["artifact_path"]
    artifact_path.write_bytes(b"corrupted")

    with pytest.raises(EvidenceError, match="SHA-256 mismatch"):
        list_documents(state_path=state_path, source_id=SOURCE_ID)

    artifact_path.unlink()
    with pytest.raises(EvidenceError, match="could not read normalized artifact"):
        list_documents(state_path=state_path, source_id=SOURCE_ID)


def test_evidence_does_not_fallback_to_older_artifact_when_latest_is_corrupt(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    older = _seed_document(
        state_path,
        raw_body=b"<html>old raw</html>",
        markdown="# Evidence\n\nOlder verified statement.",
        timestamp="2026-09-15T01:00:03+00:00",
    )
    newer = _seed_document(
        state_path,
        raw_body=b"<html>new raw</html>",
        markdown="# Evidence\n\nNewer verified statement.",
        timestamp="2026-09-15T02:00:03+00:00",
    )
    assert older["normalization"].observation_id < newer["normalization"].observation_id

    newest_path = state_path.parent / newer["artifact_path"]
    newest_path.write_bytes(b"corrupted latest artifact")
    newest_block_ref = newer["artifact"]["blocks"][1]["ref"]

    with pytest.raises(EvidenceError, match="SHA-256 mismatch"):
        get_citation(
            state_path=state_path,
            source_id=SOURCE_ID,
            requested_url=REQUESTED_URL,
            block_ref=newest_block_ref,
        )


def test_evidence_rejects_mismatched_raw_provenance(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    _seed_document(state_path)
    connection = connect_state(state_path)
    try:
        with connection:
            connection.execute(
                "UPDATE normalization_observations SET raw_sha256 = ?",
                ("f" * 64,),
            )
    finally:
        connection.close()

    with pytest.raises(EvidenceError, match="raw SHA"):
        list_documents(state_path=state_path, source_id=SOURCE_ID)


def test_evidence_rejects_mismatched_source_or_url_provenance(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    _seed_document(state_path)
    connection = connect_state(state_path)
    try:
        with connection:
            connection.execute(
                "UPDATE normalization_observations SET source_id = ?",
                ("other-source",),
            )
    finally:
        connection.close()

    with pytest.raises(EvidenceError, match="source id"):
        list_documents(state_path=state_path)


def test_evidence_requires_existing_initialized_state(tmp_path):
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(EvidenceError, match="does not exist"):
        list_documents(state_path=missing)

    state_path = tmp_path / "empty.sqlite3"
    connection = connect_state(state_path)
    connection.close()
    with pytest.raises(EvidenceError, match="run ingestion and normalization"):
        list_documents(state_path=state_path)
