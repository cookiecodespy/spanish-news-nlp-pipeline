import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import research_pipeline.normalization as normalization
from research_pipeline.discovery_state import connect_state, record_success as record_discovery_success, start_run
from research_pipeline.ingestion import sha256_bytes, store_exact_object
from research_pipeline.ingestion_state import ensure_ingestion_schema, record_success as record_ingestion_success
from research_pipeline.normalization import (
    EXTRACTOR_NAME,
    EXTRACTOR_VERSION,
    NormalizationError,
    artifact_sha256,
    build_blocks,
    extract_artifact,
    normalize_ingestion_row,
    normalize_markdown,
)
from research_pipeline.normalization_state import ensure_normalization_schema


SOURCE_ID = "source-a"
URL = "https://example.com/research/example"


def article_html(*, nav: str, script: str, finding: str) -> bytes:
    paragraph = (
        "This synthetic research article exists to test deterministic extraction. "
        "It contains enough prose for main-content extraction to distinguish the article "
        "from navigation and application chrome while preserving headings and paragraphs. "
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <title>Example Research</title>
  <link rel="canonical" href="/research/example" />
  <meta property="article:published_time" content="2026-09-01T10:00:00Z" />
  <meta property="article:modified_time" content="2026-09-02T11:00:00Z" />
  <script type="application/ld+json">{{
    "@context": "https://schema.org",
    "@type": "TechArticle",
    "headline": "Example Research",
    "author": [{{"@type":"Person","name":"Ada Example"}}],
    "datePublished": "2026-09-01T10:00:00Z",
    "dateModified": "2026-09-02T11:00:00Z",
    "inLanguage": "en"
  }}</script>
</head>
<body>
  <nav>{nav}</nav>
  <main>
    <article>
      <h1>Example Research</h1>
      <p>{paragraph}</p>
      <p>{paragraph}</p>
      <h2>Finding</h2>
      <p>{finding}</p>
      <h2>Method</h2>
      <p>{paragraph}</p>
    </article>
  </main>
  <footer>changing footer chrome</footer>
  <script>{script}</script>
</body>
</html>""".encode()


def seed_connection(tmp_path):
    state_path = tmp_path / "state.sqlite3"
    connection = connect_state(state_path)
    ensure_ingestion_schema(connection)
    ensure_normalization_schema(connection)
    run_id = start_run(connection, SOURCE_ID, started_at="2026-09-15T00:00:00+00:00")
    record_discovery_success(
        connection,
        run_id,
        [SimpleNamespace(entrypoint="https://example.com/research/", candidates=[URL])],
        seen_at="2026-09-15T00:00:01+00:00",
    )
    return state_path, connection


def ingest_local(connection, state_path, body: bytes, fetched_at: str):
    digest = sha256_bytes(body)
    object_path = store_exact_object(state_path, digest, body)
    observation = record_ingestion_success(
        connection,
        source_id=SOURCE_ID,
        requested_url=URL,
        final_url=URL,
        content_type="text/html",
        bytes_read=len(body),
        sha256=digest,
        object_path=object_path,
        fetched_at=fetched_at,
    )
    return connection.execute(
        "SELECT * FROM ingestion_observations WHERE id = ?",
        (observation.observation_id,),
    ).fetchone()


def test_extractor_builds_metadata_markdown_and_citable_blocks():
    body = article_html(
        nav="menu v1",
        script="window.build='one'",
        finding="Scoped context reduces irrelevant information presented to workers.",
    )
    artifact = extract_artifact(body, URL)

    assert artifact["schema_version"] == 1
    assert artifact["extractor"]["name"] == EXTRACTOR_NAME
    assert artifact["extractor"]["version"] == EXTRACTOR_VERSION
    assert artifact["metadata"]["title"] == "Example Research"
    assert artifact["metadata"]["authors"] == ["Ada Example"]
    assert artifact["metadata"]["published_at"] == "2026-09-01T10:00:00Z"
    assert artifact["metadata"]["modified_at"] == "2026-09-02T11:00:00Z"
    assert artifact["metadata"]["language"].lower().startswith("en")
    assert artifact["metadata"]["declared_canonical_url"] == URL
    assert "menu v1" not in artifact["markdown"]
    assert "window.build" not in artifact["markdown"]
    assert "Scoped context reduces" in artifact["markdown"]
    assert len(artifact["blocks"]) >= 4
    assert all(block["ref"].startswith("b") for block in artifact["blocks"])
    assert len({block["ref"] for block in artifact["blocks"]}) == len(artifact["blocks"])


def test_chrome_changes_do_not_change_normalized_artifact_but_content_does():
    first = article_html(
        nav="navigation build one",
        script="window.deploy='abc'",
        finding="Scoped context reduces irrelevant information presented to workers.",
    )
    chrome_changed = article_html(
        nav="navigation build two with a new menu",
        script="window.deploy='xyz'; window.timestamp=123456",
        finding="Scoped context reduces irrelevant information presented to workers.",
    )
    content_changed = article_html(
        nav="navigation build three",
        script="window.deploy='xyz'",
        finding="Scoped context reduces irrelevant information and improves worker focus.",
    )

    assert sha256_bytes(first) != sha256_bytes(chrome_changed)
    assert artifact_sha256(extract_artifact(first, URL)) == artifact_sha256(
        extract_artifact(chrome_changed, URL)
    )
    assert artifact_sha256(extract_artifact(first, URL)) != artifact_sha256(
        extract_artifact(content_changed, URL)
    )


def test_block_refs_and_heading_context_are_deterministic():
    markdown = normalize_markdown(
        "# Research\n\nIntro paragraph.\n\n## Finding\n\nImportant result.\n\n- one\n- two\n"
    )
    first = build_blocks(markdown)
    second = build_blocks(markdown)

    assert first == second
    assert first[0]["kind"] == "heading"
    assert first[1]["heading_path"] == ["Research"]
    finding = next(block for block in first if block["text"] == "Important result.")
    assert finding["heading_path"] == ["Research", "Finding"]
    assert finding["ref"].startswith("b0004-")


def test_raw_new_changed_changed_can_normalize_to_new_unchanged_changed(tmp_path):
    state_path, connection = seed_connection(tmp_path)
    try:
        raw_one = article_html(
            nav="menu one",
            script="window.version=1",
            finding="Scoped context reduces irrelevant information presented to workers.",
        )
        raw_chrome_change = article_html(
            nav="menu two totally different",
            script="window.version=2; window.now=999",
            finding="Scoped context reduces irrelevant information presented to workers.",
        )
        raw_content_change = article_html(
            nav="menu three",
            script="window.version=3",
            finding="Scoped context reduces irrelevant information and improves worker focus.",
        )

        row1 = ingest_local(connection, state_path, raw_one, "2026-09-15T01:00:00+00:00")
        row2 = ingest_local(
            connection, state_path, raw_chrome_change, "2026-09-15T02:00:00+00:00"
        )
        row3 = ingest_local(
            connection, state_path, raw_content_change, "2026-09-15T03:00:00+00:00"
        )

        assert [row1["classification"], row2["classification"], row3["classification"]] == [
            "NEW",
            "CHANGED",
            "CHANGED",
        ]

        normalized1 = normalize_ingestion_row(connection, row1, state_path=state_path)
        normalized2 = normalize_ingestion_row(connection, row2, state_path=state_path)
        normalized3 = normalize_ingestion_row(connection, row3, state_path=state_path)

        assert [
            normalized1.classification,
            normalized2.classification,
            normalized3.classification,
        ] == ["NEW", "UNCHANGED", "CHANGED"]
        assert normalized1.normalized_sha256 == normalized2.normalized_sha256
        assert normalized3.normalized_sha256 != normalized1.normalized_sha256
    finally:
        connection.close()


def test_corrupt_raw_object_fails_without_normalized_identity(tmp_path):
    state_path, connection = seed_connection(tmp_path)
    try:
        body = article_html(
            nav="menu",
            script="window.version=1",
            finding="Scoped context reduces irrelevant information presented to workers.",
        )
        row = ingest_local(connection, state_path, body, "2026-09-15T01:00:00+00:00")
        (tmp_path / row["object_path"]).write_bytes(b"tampered")

        result = normalize_ingestion_row(connection, row, state_path=state_path)
        stored = connection.execute(
            "SELECT * FROM normalization_observations ORDER BY id DESC LIMIT 1"
        ).fetchone()

        assert result.status == "ERROR"
        assert "SHA-256 mismatch" in result.error
        assert result.normalized_sha256 is None
        assert result.artifact_path is None
        assert stored["status"] == "error"
        assert stored["normalized_sha256"] is None
        assert stored["artifact_path"] is None
    finally:
        connection.close()


def test_extractor_version_mismatch_fails_closed(monkeypatch):
    monkeypatch.setattr(normalization, "package_version", lambda name: "9.9.9")
    body = article_html(
        nav="menu",
        script="window.version=1",
        finding="Scoped context reduces irrelevant information presented to workers.",
    )

    with pytest.raises(NormalizationError, match="unsupported trafilatura version"):
        extract_artifact(body, URL)


def test_artifact_payload_does_not_embed_raw_provenance():
    artifact = extract_artifact(
        article_html(
            nav="menu",
            script="window.version=1",
            finding="Scoped context reduces irrelevant information presented to workers.",
        ),
        URL,
    )
    encoded = json.dumps(artifact)

    assert "raw_sha256" not in encoded
    assert "ingestion_observation_id" not in encoded
    assert "object_path" not in encoded
