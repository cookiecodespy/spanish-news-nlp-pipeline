import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_pipeline.discovery_state import (
    connect_state,
    record_success as record_discovery_success,
    start_run,
)
from research_pipeline.grounding import (
    GroundingError,
    build_bundle,
    format_text,
    make_claim_candidate,
    validate_claim_candidate,
    verify_bundle,
)
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


def _artifact(markdown: str, title: str) -> dict:
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
    raw_body: bytes,
    markdown: str,
    title: str,
    timestamp: str,
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
        artifact = _artifact(markdown, title)
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
            title=title,
            block_count=len(artifact["blocks"]),
            char_count=len(markdown),
            normalized_at=timestamp,
        )
    finally:
        connection.close()
    return {
        "artifact": artifact,
        "artifact_path": artifact_path,
        "normalization": normalization,
        "normalized_sha": normalized_sha,
    }


def _seed_base(state_path: Path):
    return _seed_document(
        state_path,
        raw_body=b"<html>raw v1</html>",
        markdown="# Context\n\nWorkers should receive scoped context.\n\n# Tools\n\nTools should return concise results.",
        title="Context engineering",
        timestamp="2026-09-15T01:00:03+00:00",
    )


def _selector(seeded, block_index: int = 1):
    block = seeded["artifact"]["blocks"][block_index]
    return (SOURCE_ID, REQUESTED_URL, block["ref"])


def test_build_bundle_is_verified_bounded_deduplicated_and_deterministic(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    seeded = _seed_base(state_path)
    first = _selector(seeded, 1)
    second = _selector(seeded, 3)

    bundle_a = build_bundle([second, first, first], state_path=state_path)
    bundle_b = build_bundle([first, second], state_path=state_path)

    assert bundle_a == bundle_b
    assert bundle_a["type"] == "evidence_bundle"
    assert bundle_a["trust"] == "external_data_only"
    assert bundle_a["item_count"] == 2
    assert bundle_a["bundle_id"].startswith("eb-")
    assert len(bundle_a["bundle_sha256"]) == 64
    assert all(item["trust"] == "data_not_instructions" for item in bundle_a["items"])
    assert all(item["evidence_id"].startswith("ev-") for item in bundle_a["items"])
    assert {
        item["provenance"]["normalization_observation_id"] for item in bundle_a["items"]
    } == {seeded["normalization"].observation_id}


def test_bundle_limits_are_enforced(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    seeded = _seed_base(state_path)

    with pytest.raises(GroundingError, match="configured limit"):
        build_bundle(
            [_selector(seeded, 1), _selector(seeded, 3)],
            state_path=state_path,
            max_items=1,
        )

    with pytest.raises(GroundingError, match="evidence characters"):
        build_bundle(
            [_selector(seeded, 1)],
            state_path=state_path,
            max_chars=5,
        )

    with pytest.raises(GroundingError, match="max_items"):
        build_bundle([_selector(seeded, 1)], state_path=state_path, max_items=33)


def test_bundle_remains_pinned_to_historical_observation_after_newer_normalization(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    older = _seed_base(state_path)
    bundle = build_bundle([_selector(older, 1)], state_path=state_path)
    pinned_id = bundle["items"][0]["provenance"]["normalization_observation_id"]

    newer = _seed_document(
        state_path,
        raw_body=b"<html>raw v2</html>",
        markdown="# Context\n\nNewer guidance replaces this paragraph.",
        title="Context engineering v2",
        timestamp="2026-09-15T02:00:03+00:00",
    )
    assert newer["normalization"].observation_id > pinned_id

    result = verify_bundle(bundle, state_path=state_path)
    assert result["ok"] is True
    assert result["citation_integrity"] == "VALID"
    assert result["provenance_integrity"] == "VALID"
    assert result["semantic_support"] == "UNASSESSED"
    assert bundle["items"][0]["block"]["text"] == "Workers should receive scoped context."


def test_bundle_verification_fails_on_corrupt_pinned_artifact_without_substitution(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    older = _seed_base(state_path)
    bundle = build_bundle([_selector(older, 1)], state_path=state_path)

    _seed_document(
        state_path,
        raw_body=b"<html>raw v2</html>",
        markdown="# Context\n\nA newer valid observation exists.",
        title="Newer",
        timestamp="2026-09-15T02:00:03+00:00",
    )
    pinned_path = state_path.parent / older["artifact_path"]
    pinned_path.write_bytes(b"corrupt pinned evidence")

    with pytest.raises(GroundingError, match="SHA-256 mismatch"):
        verify_bundle(bundle, state_path=state_path)


def test_bundle_tampering_is_detected_before_claim_use(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    seeded = _seed_base(state_path)
    bundle = build_bundle([_selector(seeded, 1)], state_path=state_path)
    bundle["items"][0]["block"]["text"] = "tampered text"

    with pytest.raises(GroundingError, match="bundle SHA-256"):
        verify_bundle(bundle, state_path=state_path)


def test_claim_candidate_requires_real_bundle_citations_and_stays_unreviewed(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    seeded = _seed_base(state_path)
    bundle = build_bundle(
        [_selector(seeded, 1), _selector(seeded, 3)],
        state_path=state_path,
    )
    evidence_id = bundle["items"][0]["evidence_id"]

    candidate = make_claim_candidate(
        "Scoped worker context can reduce unnecessary context exposure.",
        [evidence_id],
        bundle,
        state_path=state_path,
    )
    assert candidate["type"] == "claim_candidate"
    assert candidate["status"] == "UNREVIEWED"
    assert candidate["semantic_support"] == "UNASSESSED"
    assert candidate["claim_id"].startswith("cc-")

    validation = validate_claim_candidate(candidate, bundle, state_path=state_path)
    assert validation == {
        "ok": True,
        "type": "claim_candidate_validation",
        "claim_id": candidate["claim_id"],
        "bundle_id": bundle["bundle_id"],
        "citation_count": 1,
        "citation_integrity": "VALID",
        "provenance_integrity": "VALID",
        "review_status": "UNREVIEWED",
        "semantic_support": "UNASSESSED",
        "semantic_truth": "UNASSESSED",
    }


def test_claim_candidate_rejects_unknown_duplicate_or_missing_citations(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    seeded = _seed_base(state_path)
    bundle = build_bundle([_selector(seeded, 1)], state_path=state_path)
    evidence_id = bundle["items"][0]["evidence_id"]

    with pytest.raises(GroundingError, match="unknown evidence"):
        make_claim_candidate(
            "A claim.", ["ev-does-not-exist"], bundle, state_path=state_path
        )
    with pytest.raises(GroundingError, match="duplicate citation"):
        make_claim_candidate(
            "A claim.", [evidence_id, evidence_id], bundle, state_path=state_path
        )
    with pytest.raises(GroundingError, match="at least one"):
        make_claim_candidate("A claim.", [], bundle, state_path=state_path)


def test_claim_validation_refuses_semantic_promotion(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    seeded = _seed_base(state_path)
    bundle = build_bundle([_selector(seeded, 1)], state_path=state_path)
    evidence_id = bundle["items"][0]["evidence_id"]
    candidate = make_claim_candidate(
        "A structurally cited claim.", [evidence_id], bundle, state_path=state_path
    )

    candidate["semantic_support"] = "VERIFIED"
    with pytest.raises(GroundingError, match="must remain UNASSESSED"):
        validate_claim_candidate(candidate, bundle, state_path=state_path)

    candidate["semantic_support"] = "UNASSESSED"
    candidate["status"] = "APPROVED"
    with pytest.raises(GroundingError, match="must remain UNREVIEWED"):
        validate_claim_candidate(candidate, bundle, state_path=state_path)


def test_human_views_state_the_semantic_boundary(tmp_path):
    state_path = tmp_path / "pipeline.sqlite3"
    seeded = _seed_base(state_path)
    bundle = build_bundle([_selector(seeded, 1)], state_path=state_path)
    evidence_id = bundle["items"][0]["evidence_id"]
    candidate = make_claim_candidate(
        "A candidate statement.", [evidence_id], bundle, state_path=state_path
    )
    validation = validate_claim_candidate(candidate, bundle, state_path=state_path)

    bundle_text = format_text(bundle)
    claim_text = format_text(candidate)
    validation_text = format_text(validation)

    assert "external data only" in bundle_text
    assert "CLAIM CANDIDATE — UNREVIEWED" in claim_text
    assert "Semantic support: UNASSESSED" in claim_text
    assert "citation contract VALID" in validation_text
    assert "Semantic truth: UNASSESSED" in validation_text
