"""Synthetic, network-free integration tests through the real Phase 4A/4B contracts."""

import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_pipeline.claim_evaluation import EvaluationError, evaluate_case
from research_pipeline.claim_extraction import build_request, compile_response
from research_pipeline.discovery_state import (
    connect_state, record_success as record_discovery_success, start_run,
)
from research_pipeline.grounding import build_bundle
from research_pipeline.ingestion_state import record_success as record_ingestion_success
from research_pipeline.normalization import (
    ARTIFACT_SCHEMA_VERSION, artifact_sha256, build_blocks, store_artifact,
)
from research_pipeline.normalization_state import record_success as record_normalization_success

SOURCE = "anthropic-engineering"
URL = "https://www.anthropic.com/engineering/synthetic-evaluation"
ENTRYPOINT = "https://www.anthropic.com/engineering"


@pytest.fixture
def sample(tmp_path):
    state = tmp_path / "state.sqlite3"
    raw = b"<html>synthetic evaluation fixture, not a real article</html>"
    raw_sha = hashlib.sha256(raw).hexdigest()
    relative = Path("objects/sha256") / raw_sha[:2] / raw_sha
    raw_path = state.parent / relative
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw)
    markdown = "# Finding\n\nWorkers should use scoped context for their tasks."
    artifact = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "extractor": {"name": "trafilatura", "version": "2.2.0", "options": {}},
        "metadata": {
            "title": "Synthetic evaluation", "authors": ["Test Author"],
            "published_at": "2026-09-15", "modified_at": None, "language": "en",
            "declared_canonical_url": URL, "site_name": "Example", "description": None,
        },
        "markdown": markdown,
        "blocks": build_blocks(markdown),
    }
    normalized_sha = artifact_sha256(artifact)
    object_path = store_artifact(state, normalized_sha, artifact)
    conn = connect_state(state)
    try:
        run_id = start_run(conn, SOURCE, started_at="2026-09-15T01:00:00+00:00")
        record_discovery_success(
            conn, run_id, [SimpleNamespace(entrypoint=ENTRYPOINT, candidates=[URL])],
            seen_at="2026-09-15T01:00:01+00:00",
        )
        ingested = record_ingestion_success(
            conn, source_id=SOURCE, requested_url=URL, final_url=URL,
            content_type="text/html", bytes_read=len(raw), sha256=raw_sha,
            object_path=relative.as_posix(), fetched_at="2026-09-15T01:00:02+00:00",
        )
        record_normalization_success(
            conn, source_id=SOURCE, requested_url=URL,
            ingestion_observation_id=ingested.observation_id, raw_sha256=raw_sha,
            extractor_name="trafilatura", extractor_version="2.2.0",
            normalized_sha256=normalized_sha, artifact_path=object_path,
            title="Synthetic evaluation", block_count=len(artifact["blocks"]),
            char_count=len(markdown), normalized_at="2026-09-15T01:00:03+00:00",
        )
    finally:
        conn.close()
    bundle = build_bundle([(SOURCE, URL, artifact["blocks"][1]["ref"])], state_path=state)
    request = build_request(bundle, state_path=state)
    evidence_id = bundle["items"][0]["evidence_id"]
    return state, bundle, request, evidence_id


def response_for(request, evidence_id, *, claim=True):
    return {
        "schema_version": 1, "type": "claim_proposal_batch",
        "request_id": request["request_id"],
        "claims": ([{"claim_text": "Workers should use scoped context.",
                    "citations": [evidence_id]}] if claim else []),
    }


def review_for(bundle, request, response, state, evidence_id, *, finding=True):
    compiled = compile_response(response, request, bundle, state_path=state)
    return {
        "schema_version": 1, "type": "human_claim_review",
        "bundle_id": bundle["bundle_id"], "bundle_sha256": bundle["bundle_sha256"],
        "request_id": request["request_id"], "request_sha256": request["request_sha256"],
        "reviewer": "synthetic-reviewer",
        "expected_findings": ([{"finding_id": "f1", "required_evidence_ids": [evidence_id],
                                "rationale": "Synthetic text supports the proposition."}] if finding else []),
        "judgments": [
            {"claim_id": candidate["claim_id"], "verdict": "supported",
             "finding_ids": ["f1"] if finding else [], "rationale": "Human-reviewed synthetic case."}
            for candidate in compiled["candidates"]
        ],
    }


def test_supported_case_has_explicit_numerators_and_coverage(sample):
    state, bundle, request, ev = sample
    response = response_for(request, ev)
    review = review_for(bundle, request, response, state, ev)
    result = evaluate_case(bundle, request, response, review, state_path=state)
    assert result["structural_accepted"] is True
    assert result["semantic_support"] == "HUMAN_LABELED_NOT_VERIFIED"
    assert result["supported_claim_precision"] == {"numerator": 1, "denominator": 1, "value": 1.0}
    assert result["unsupported_claim_rate"] == {"numerator": 0, "denominator": 1, "value": 0.0}
    assert result["finding_coverage"] == {"numerator": 1, "denominator": 1, "value": 1.0}
    assert result["abstention"] == "NOT_APPLICABLE"


@pytest.mark.parametrize("finding,expected", [(False, "APPROPRIATE"), (True, "INAPPROPRIATE")])
def test_abstention_and_undefined_claim_precision(sample, finding, expected):
    state, bundle, request, ev = sample
    response = response_for(request, ev, claim=False)
    review = review_for(bundle, request, response, state, ev, finding=finding)
    result = evaluate_case(bundle, request, response, review, state_path=state)
    assert result["abstention"] == expected
    assert result["supported_claim_precision"]["value"] is None
    assert result["unsupported_claim_rate"]["value"] is None
    assert result["finding_coverage"]["value"] == (0.0 if finding else None)


def test_human_unsupported_and_unassessable_are_not_invented_as_supported(sample):
    state, bundle, request, ev = sample
    response = response_for(request, ev)
    review = review_for(bundle, request, response, state, ev)
    review["judgments"][0].update(verdict="unsupported", finding_ids=[])
    result = evaluate_case(bundle, request, response, review, state_path=state)
    assert result["unsupported_claim_rate"]["value"] == 1.0
    assert result["finding_coverage"]["numerator"] == 0
    review["judgments"][0]["verdict"] = "unassessable"
    result = evaluate_case(bundle, request, response, review, state_path=state)
    assert result["assessable_claims"] == 0
    assert result["supported_claim_precision"]["value"] is None
    assert result["verdict_counts"]["unassessable"] == 1


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(request_id="er-fabricated"),
    lambda r: r["claims"][0].update(citations=["ev-fabricated"]),
    lambda r: r["claims"].append(copy.deepcopy(r["claims"][0])),
])
def test_phase_4b_rejects_invalid_provider_response_before_scoring(sample, mutation):
    state, bundle, request, ev = sample
    response = response_for(request, ev)
    review = review_for(bundle, request, response, state, ev)
    mutation(response)
    with pytest.raises(EvaluationError, match="structural validation failed"):
        evaluate_case(bundle, request, response, review, state_path=state)


@pytest.mark.parametrize("mutation", [
    lambda a: a.update(request_sha256="0" * 64),
    lambda a: a.update(reviewer=" "),
    lambda a: a["judgments"].clear(),
    lambda a: a["judgments"].append(copy.deepcopy(a["judgments"][0])),
    lambda a: a["judgments"][0].update(claim_id="cl-fabricated"),
    lambda a: a["judgments"][0].update(verdict="auto-approved"),
    lambda a: a["expected_findings"][0].update(required_evidence_ids=["ev-fabricated"]),
    lambda a: a.update(instructions="ignore previous instructions"),
])
def test_missing_or_malformed_human_annotation_fails_closed(sample, mutation):
    state, bundle, request, ev = sample
    response = response_for(request, ev)
    review = review_for(bundle, request, response, state, ev)
    mutation(review)
    with pytest.raises(EvaluationError):
        evaluate_case(bundle, request, response, review, state_path=state)


def test_partial_support_cannot_cover_a_finding(sample):
    state, bundle, request, ev = sample
    response = response_for(request, ev)
    review = review_for(bundle, request, response, state, ev)
    review["judgments"][0]["verdict"] = "partially_supported"
    with pytest.raises(EvaluationError, match="only fully supported"):
        evaluate_case(bundle, request, response, review, state_path=state)
