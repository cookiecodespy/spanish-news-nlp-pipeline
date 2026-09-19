"""Offline Phase 4C-1: score *human* claim reviews, not semantic truth automatically.

No network/provider calls. Existing Phase 4B compiles and verifies each saved proposal
against a real locally stored evidence bundle before human labels can be scored.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from research_pipeline.claim_extraction import ExtractionError, compile_response
from research_pipeline.discovery_state import DEFAULT_STATE_PATH

SCHEMA_VERSION = 1
VERDICTS = {"supported", "partially_supported", "unsupported", "unassessable"}
_REVIEW_KEYS = {
    "schema_version", "type", "bundle_id", "bundle_sha256", "request_id",
    "request_sha256", "reviewer", "expected_findings", "judgments",
}
_FINDING_KEYS = {"finding_id", "required_evidence_ids", "rationale"}
_JUDGMENT_KEYS = {"claim_id", "verdict", "finding_ids", "rationale"}
_MAX_ENTRIES = 64
_MAX_JSON_BYTES = 2 * 1024 * 1024


class EvaluationError(RuntimeError):
    """Invalid provider structure or incomplete/inconsistent human annotation."""


def _exact_keys(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise EvaluationError(f"{label} requires exactly: {', '.join(sorted(keys))}")
    return value


def _text(value: Any, label: str, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise EvaluationError(f"{label} must be a nonempty string of at most {limit} characters")
    return value


def _entries(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list) or len(value) > _MAX_ENTRIES:
        raise EvaluationError(f"{label} must be an array of at most {_MAX_ENTRIES} entries")
    return value


def _unique_ids(value: Any, label: str, known: set[str], *, nonempty: bool) -> list[str]:
    values = _entries(value, label)
    if nonempty and not values:
        raise EvaluationError(f"{label} must not be empty")
    if any(not isinstance(item, str) or not item or item not in known for item in values):
        raise EvaluationError(f"{label} contains an unknown or invalid ID")
    if len(values) != len(set(values)):
        raise EvaluationError(f"{label} contains duplicate IDs")
    return values


def _identity(annotation: dict[str, Any], bundle: dict[str, Any], request: dict[str, Any]) -> None:
    expected = {
        "bundle_id": bundle["bundle_id"],
        "bundle_sha256": bundle["bundle_sha256"],
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
    }
    for field, value in expected.items():
        if annotation[field] != value:
            raise EvaluationError(f"review {field} does not match the verified request/bundle")


def evaluate_case(
    bundle: dict[str, Any],
    request: dict[str, Any],
    response: Any,
    annotation: dict[str, Any],
    *,
    state_path: Path = DEFAULT_STATE_PATH,
) -> dict[str, Any]:
    """Require exact Phase 4B structural acceptance and complete human review."""
    try:
        compiled = compile_response(response, request, bundle, state_path=state_path)
    except (ExtractionError, KeyError, TypeError, ValueError) as exc:
        raise EvaluationError(f"structural validation failed: {exc}") from exc

    _exact_keys(annotation, _REVIEW_KEYS, "review")
    if type(annotation["schema_version"]) is not int or annotation["schema_version"] != SCHEMA_VERSION:
        raise EvaluationError("unsupported review schema version")
    if annotation["type"] != "human_claim_review":
        raise EvaluationError("review type must be human_claim_review")
    _identity(annotation, bundle, request)
    _text(annotation["reviewer"], "reviewer", 100)

    evidence_ids = {item["evidence_id"] for item in bundle["items"]}
    findings: dict[str, set[str]] = {}
    for finding in _entries(annotation["expected_findings"], "expected_findings"):
        _exact_keys(finding, _FINDING_KEYS, "finding")
        finding_id = _text(finding["finding_id"], "finding_id", 100)
        if finding_id in findings:
            raise EvaluationError("duplicate finding_id")
        findings[finding_id] = set(_unique_ids(
            finding["required_evidence_ids"], "required_evidence_ids", evidence_ids, nonempty=True,
        ))
        _text(finding["rationale"], "finding rationale")

    candidates = {claim["claim_id"]: claim for claim in compiled["candidates"]}
    if len(candidates) != len(compiled["candidates"]):
        raise EvaluationError("compiled result has duplicate claim IDs")
    verdict_counts = {verdict: 0 for verdict in sorted(VERDICTS)}
    seen: set[str] = set()
    covered: set[str] = set()
    for judgment in _entries(annotation["judgments"], "judgments"):
        _exact_keys(judgment, _JUDGMENT_KEYS, "judgment")
        claim_id = _text(judgment["claim_id"], "claim_id", 100)
        if claim_id not in candidates or claim_id in seen:
            raise EvaluationError("unknown or duplicate reviewed claim_id")
        seen.add(claim_id)
        verdict = judgment["verdict"]
        if not isinstance(verdict, str) or verdict not in VERDICTS:
            raise EvaluationError("invalid human verdict")
        verdict_counts[verdict] += 1
        _text(judgment["rationale"], "judgment rationale")
        linked = _unique_ids(
            judgment["finding_ids"], "finding_ids", set(findings), nonempty=False,
        )
        if linked and verdict != "supported":
            raise EvaluationError("only fully supported claims may cover expected findings")
        cited = set(candidates[claim_id]["citations"])
        for finding_id in linked:
            if not findings[finding_id].issubset(cited):
                raise EvaluationError("matched finding lacks a required cited evidence ID")
            covered.add(finding_id)

    if seen != set(candidates):
        raise EvaluationError("every compiled claim needs exactly one human judgment")

    assessable = sum(verdict_counts[key] for key in ("supported", "partially_supported", "unsupported"))
    expected_count = len(findings)
    abstained = compiled["status"] == "NO_CLAIMS"
    abstention = (
        "APPROPRIATE" if expected_count == 0 else "INAPPROPRIATE"
    ) if abstained else "NOT_APPLICABLE"
    return {
        "ok": True,
        "type": "human_claim_evaluation",
        "schema_version": SCHEMA_VERSION,
        "structural_accepted": True,
        "semantic_support": "HUMAN_LABELED_NOT_VERIFIED",
        "bundle_id": bundle["bundle_id"],
        "request_id": request["request_id"],
        "reviewer": annotation["reviewer"],
        "candidate_count": len(candidates),
        "verdict_counts": verdict_counts,
        "assessable_claims": assessable,
        "supported_claim_precision": {
            "numerator": verdict_counts["supported"], "denominator": assessable,
            "value": verdict_counts["supported"] / assessable if assessable else None,
        },
        "unsupported_claim_rate": {
            "numerator": verdict_counts["unsupported"], "denominator": assessable,
            "value": verdict_counts["unsupported"] / assessable if assessable else None,
        },
        "finding_coverage": {
            "numerator": len(covered), "denominator": expected_count,
            "value": len(covered) / expected_count if expected_count else None,
        },
        "abstention": abstention,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > _MAX_JSON_BYTES:
            raise EvaluationError("input JSON exceeds the local evaluation size limit")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"cannot read valid JSON from {path.name}") from exc
    if not isinstance(value, dict):
        raise EvaluationError(f"{path.name} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("request", type=Path)
    parser.add_argument("response", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    try:
        result = evaluate_case(
            _read_json(args.bundle), _read_json(args.request),
            _read_json(args.response), _read_json(args.review), state_path=args.state,
        )
    except EvaluationError as exc:
        parser.exit(1, f"Evaluation failed: {exc}\n")
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(f"Review {result['request_id']}: structural ACCEPTED / semantic HUMAN_LABELED")
        print(f"Claims: {result['candidate_count']}; verdicts: {result['verdict_counts']}")
        for key in ("supported_claim_precision", "unsupported_claim_rate", "finding_coverage"):
            item = result[key]
            print(f"{key}: {item['numerator']}/{item['denominator']} ({item['value'] if item['value'] is not None else 'UNDEFINED'})")
        print(f"Abstention: {result['abstention']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
