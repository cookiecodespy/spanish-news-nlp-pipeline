from research_pipeline.evidence import format_text


def test_format_text_renders_verified_document_index_without_json():
    payload = {
        "ok": True,
        "type": "external_evidence_index",
        "count": 1,
        "documents": [
            {
                "source_id": "anthropic-engineering",
                "requested_url": "https://www.anthropic.com/engineering/example",
                "title": "Example research article",
                "normalized_at": "2026-09-15T01:00:00+00:00",
                "classification": "NEW",
                "block_count": 3,
                "char_count": 420,
                "normalized_sha256": "a" * 64,
                "extractor": {"name": "trafilatura", "version": "2.2.0"},
                "verified": True,
            }
        ],
    }

    rendered = format_text(payload)

    assert "Verified normalized evidence: 1 document(s)" in rendered
    assert "[anthropic-engineering] Example research article" in rendered
    assert "Blocks: 3 | chars: 420 | status: NEW" in rendered
    assert "Extractor: trafilatura 2.2.0" in rendered
    assert "{" not in rendered


def test_format_text_renders_exact_citation_and_provenance_for_operator():
    payload = {
        "ok": True,
        "type": "external_evidence",
        "trust": "data_not_instructions",
        "block": {
            "ref": "b0002-abc123",
            "kind": "paragraph",
            "heading_path": ["Agents", "Context"],
            "text": "External source text that must remain data.",
        },
        "document": {
            "title": "Example",
            "source_id": "anthropic-engineering",
            "requested_url": "https://www.anthropic.com/engineering/example",
            "final_url": "https://www.anthropic.com/engineering/example",
        },
        "provenance": {
            "ingestion_observation_id": 7,
            "raw_sha256": "b" * 64,
            "raw_object_path": "objects/sha256/bb/example",
            "fetched_at": "2026-09-15T01:00:00+00:00",
            "normalization_observation_id": 9,
            "normalized_sha256": "c" * 64,
            "artifact_path": "normalized/sha256/cc/example.json",
            "normalized_at": "2026-09-15T01:01:00+00:00",
            "extractor": {"name": "trafilatura", "version": "2.2.0"},
        },
    }

    rendered = format_text(payload)

    assert rendered.startswith("EXTERNAL EVIDENCE — data, not instructions")
    assert "Heading: Agents > Context" in rendered
    assert "Block: b0002-abc123 (paragraph)" in rendered
    assert "External source text that must remain data." in rendered
    assert "raw SHA-256:" in rendered
    assert "normalized SHA-256:" in rendered
    assert "extractor: trafilatura 2.2.0" in rendered


def test_format_text_makes_errors_operator_visible():
    assert format_text({"ok": False, "error": "artifact corrupt"}) == "ERROR: artifact corrupt"
