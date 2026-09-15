"""Phase 4A deterministic evidence bundles and claim-candidate validation.

No model is called here. This module packages already verified Phase 3B citation blocks into
bounded, immutable evidence bundles and defines the structural contract a future model must
satisfy when proposing a claim. Citation/provenance integrity is deterministic; semantic
support is deliberately left UNASSESSED.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from research_pipeline.discovery_state import DEFAULT_STATE_PATH
from research_pipeline.evidence import (
    EvidenceError,
    _load_verified_artifact,
    _open_existing_state,
    _validate_provenance,
    get_citation,
)

BUNDLE_SCHEMA_VERSION = 1
CLAIM_SCHEMA_VERSION = 1
DEFAULT_MAX_ITEMS = 8
HARD_MAX_ITEMS = 32
DEFAULT_MAX_CHARS = 12_000
HARD_MAX_CHARS = 50_000

_BUNDLE_KEYS = {
    "schema_version",
    "type",
    "trust",
    "item_count",
    "total_chars",
    "items",
    "bundle_sha256",
    "bundle_id",
}
_ITEM_KEYS = {"evidence_id", "type", "trust", "document", "block", "provenance"}
_DOCUMENT_KEYS = {"title", "source_id", "requested_url", "final_url"}
_BLOCK_KEYS = {"ref", "kind", "heading_path", "text"}
_PROVENANCE_KEYS = {
    "ingestion_observation_id",
    "raw_sha256",
    "raw_object_path",
    "fetched_at",
    "normalization_observation_id",
    "normalized_sha256",
    "artifact_path",
    "normalized_at",
    "extractor",
}
_CLAIM_KEYS = {
    "schema_version",
    "type",
    "status",
    "semantic_support",
    "claim_text",
    "bundle_id",
    "bundle_sha256",
    "citations",
    "claim_sha256",
    "claim_id",
}


class GroundingError(RuntimeError):
    """Raised when an evidence bundle or claim contract is invalid."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_exact_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    extra = set(value) - allowed
    missing = allowed - set(value)
    if extra:
        raise GroundingError(f"{label} has unexpected fields: {sorted(extra)}")
    if missing:
        raise GroundingError(f"{label} is missing fields: {sorted(missing)}")


def _require_hex_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise GroundingError(f"{field} must be a 64-character SHA-256 hex digest")
    if any(ch not in "0123456789abcdef" for ch in value):
        raise GroundingError(f"{field} must be lowercase hexadecimal")
    return value


def _validate_limits(max_items: int, max_chars: int) -> None:
    if not 1 <= max_items <= HARD_MAX_ITEMS:
        raise GroundingError(f"max_items must be between 1 and {HARD_MAX_ITEMS}")
    if not 1 <= max_chars <= HARD_MAX_CHARS:
        raise GroundingError(f"max_chars must be between 1 and {HARD_MAX_CHARS}")


def _evidence_identity(citation: dict[str, Any]) -> dict[str, Any]:
    try:
        document = citation["document"]
        block = citation["block"]
        provenance = citation["provenance"]
        source_id = document["source_id"]
        requested_url = document["requested_url"]
        block_ref = block["ref"]
        observation_id = provenance["normalization_observation_id"]
        normalized_sha256 = provenance["normalized_sha256"]
    except (KeyError, TypeError) as exc:
        raise GroundingError("citation is missing immutable evidence identity fields") from exc

    if not isinstance(source_id, str) or not source_id:
        raise GroundingError("citation source_id is required")
    if not isinstance(requested_url, str) or not requested_url:
        raise GroundingError("citation requested_url is required")
    if not isinstance(block_ref, str) or not block_ref:
        raise GroundingError("citation block ref is required")
    if not isinstance(observation_id, int) or observation_id < 1:
        raise GroundingError("normalization_observation_id must be a positive integer")

    return {
        "source_id": source_id,
        "requested_url": requested_url,
        "normalization_observation_id": observation_id,
        "normalized_sha256": _require_hex_sha256(normalized_sha256, "normalized_sha256"),
        "block_ref": block_ref,
    }


def _evidence_id(citation: dict[str, Any]) -> str:
    return f"ev-{_sha256(_evidence_identity(citation))[:20]}"


def _bundle_item(citation: dict[str, Any]) -> dict[str, Any]:
    if citation.get("ok") is not True:
        raise GroundingError("only successful verified citations can enter a bundle")
    if citation.get("type") != "external_evidence":
        raise GroundingError("bundle input must be typed external_evidence")
    if citation.get("trust") != "data_not_instructions":
        raise GroundingError("external evidence must remain data_not_instructions")
    return {
        "evidence_id": _evidence_id(citation),
        "type": "external_evidence",
        "trust": "data_not_instructions",
        "document": citation["document"],
        "block": citation["block"],
        "provenance": citation["provenance"],
    }


def _bundle_core(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "type": "evidence_bundle",
        "trust": "external_data_only",
        "item_count": len(items),
        "total_chars": sum(len(item["block"]["text"]) for item in items),
        "items": items,
    }


def _with_bundle_identity(core: dict[str, Any]) -> dict[str, Any]:
    digest = _sha256(core)
    return {**core, "bundle_sha256": digest, "bundle_id": f"eb-{digest[:20]}"}


def build_bundle(
    citations: Iterable[tuple[str, str, str]],
    *,
    state_path: Path = DEFAULT_STATE_PATH,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """Build a bounded deterministic bundle from exact Phase 3B citation selectors."""
    _validate_limits(max_items, max_chars)
    by_id: dict[str, dict[str, Any]] = {}

    for source_id, requested_url, block_ref in citations:
        try:
            citation = get_citation(
                state_path=state_path,
                source_id=source_id,
                requested_url=requested_url,
                block_ref=block_ref,
            )
        except EvidenceError as exc:
            raise GroundingError(str(exc)) from exc
        item = _bundle_item(citation)
        evidence_id = item["evidence_id"]
        prior = by_id.get(evidence_id)
        if prior is not None and prior != item:
            raise GroundingError(f"evidence id collision: {evidence_id}")
        by_id[evidence_id] = item

    if not by_id:
        raise GroundingError("an evidence bundle requires at least one citation")

    items = sorted(
        by_id.values(),
        key=lambda item: (
            item["document"]["source_id"],
            item["document"]["requested_url"],
            item["provenance"]["normalization_observation_id"],
            item["block"]["ref"],
        ),
    )
    if len(items) > max_items:
        raise GroundingError(
            f"bundle contains {len(items)} unique items; configured limit is {max_items}"
        )

    core = _bundle_core(items)
    if core["total_chars"] > max_chars:
        raise GroundingError(
            f"bundle contains {core['total_chars']} evidence characters; configured limit is {max_chars}"
        )
    return _with_bundle_identity(core)


def _exact_row(connection, normalization_observation_id: int):
    return connection.execute(
        """
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
            io.source_id AS ingestion_source_id,
            io.requested_url AS ingestion_requested_url,
            io.final_url,
            io.fetched_at,
            io.classification AS ingestion_classification,
            io.content_type,
            io.bytes_read,
            io.sha256 AS ingestion_sha256,
            io.object_path AS raw_object_path
        FROM normalization_observations AS no
        JOIN ingestion_observations AS io ON io.id = no.ingestion_observation_id
        WHERE no.id = ? AND no.status = 'success' AND io.status = 'success'
        LIMIT 1
        """,
        (normalization_observation_id,),
    ).fetchone()


def _citation_from_exact_observation(
    *,
    state_path: Path,
    normalization_observation_id: int,
    block_ref: str,
) -> dict[str, Any]:
    connection = _open_existing_state(state_path)
    try:
        row = _exact_row(connection, normalization_observation_id)
        if row is None:
            raise GroundingError(
                "pinned normalization observation is missing or not successful: "
                f"{normalization_observation_id}"
            )
        _validate_provenance(row)
        artifact = _load_verified_artifact(state_path, row)
    except EvidenceError as exc:
        raise GroundingError(str(exc)) from exc
    finally:
        connection.close()

    matches = [
        block
        for block in artifact["blocks"]
        if isinstance(block, dict) and block.get("ref") == block_ref
    ]
    if not matches:
        raise GroundingError(
            f"pinned observation {normalization_observation_id} has no block ref {block_ref}"
        )
    if len(matches) != 1:
        raise GroundingError(
            f"pinned observation {normalization_observation_id} has duplicate block ref {block_ref}"
        )

    block = matches[0]
    text = block.get("text")
    kind = block.get("kind")
    heading_path = block.get("heading_path")
    if not isinstance(text, str) or not text:
        raise GroundingError(f"citation block {block_ref} has no text")
    if not isinstance(kind, str) or not kind:
        raise GroundingError(f"citation block {block_ref} has no kind")
    if not isinstance(heading_path, list) or not all(isinstance(item, str) for item in heading_path):
        raise GroundingError(f"citation block {block_ref} has invalid heading_path")

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


def _validate_item_shape(item: dict[str, Any]) -> int:
    _require_exact_keys(item, _ITEM_KEYS, "bundle item")
    if item.get("type") != "external_evidence":
        raise GroundingError("every bundle item must be external_evidence")
    if item.get("trust") != "data_not_instructions":
        raise GroundingError("every bundle item must remain data_not_instructions")

    document = item.get("document")
    block = item.get("block")
    provenance = item.get("provenance")
    if not isinstance(document, dict) or not isinstance(block, dict) or not isinstance(provenance, dict):
        raise GroundingError("bundle item document, block and provenance must be objects")
    _require_exact_keys(document, _DOCUMENT_KEYS, "bundle document")
    _require_exact_keys(block, _BLOCK_KEYS, "bundle block")
    _require_exact_keys(provenance, _PROVENANCE_KEYS, "bundle provenance")

    extractor = provenance.get("extractor")
    if not isinstance(extractor, dict) or set(extractor) != {"name", "version"}:
        raise GroundingError("bundle provenance extractor must contain only name and version")

    expected_id = _evidence_id({"ok": True, **item})
    if item.get("evidence_id") != expected_id:
        raise GroundingError("bundle evidence_id does not match immutable evidence identity")

    text = block.get("text")
    if not isinstance(text, str) or not text:
        raise GroundingError(f"bundle item {expected_id} has invalid block text")
    return len(text)


def _validate_bundle_shape(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(bundle, dict):
        raise GroundingError("bundle must be a JSON object")
    _require_exact_keys(bundle, _BUNDLE_KEYS, "bundle")
    if bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise GroundingError(f"unsupported bundle schema version: {bundle.get('schema_version')}")
    if bundle.get("type") != "evidence_bundle":
        raise GroundingError("bundle type must be evidence_bundle")
    if bundle.get("trust") != "external_data_only":
        raise GroundingError("bundle trust must be external_data_only")

    items = bundle.get("items")
    if not isinstance(items, list) or not items:
        raise GroundingError("bundle requires a non-empty items list")
    if len(items) > HARD_MAX_ITEMS:
        raise GroundingError(f"bundle exceeds hard item limit of {HARD_MAX_ITEMS}")
    if bundle.get("item_count") != len(items):
        raise GroundingError("bundle item_count does not match items")

    total_chars = 0
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise GroundingError("every bundle item must be an object")
        total_chars += _validate_item_shape(item)
        evidence_id = item["evidence_id"]
        if evidence_id in seen:
            raise GroundingError(f"duplicate evidence id in bundle: {evidence_id}")
        seen.add(evidence_id)

    if total_chars > HARD_MAX_CHARS:
        raise GroundingError(f"bundle exceeds hard character limit of {HARD_MAX_CHARS}")
    if bundle.get("total_chars") != total_chars:
        raise GroundingError("bundle total_chars does not match evidence text")

    core = {
        "schema_version": bundle["schema_version"],
        "type": bundle["type"],
        "trust": bundle["trust"],
        "item_count": bundle["item_count"],
        "total_chars": bundle["total_chars"],
        "items": items,
    }
    expected_sha = _sha256(core)
    actual_sha = _require_hex_sha256(bundle.get("bundle_sha256"), "bundle_sha256")
    if actual_sha != expected_sha:
        raise GroundingError("bundle SHA-256 does not match canonical bundle content")
    if bundle.get("bundle_id") != f"eb-{expected_sha[:20]}":
        raise GroundingError("bundle_id does not match bundle SHA-256")
    return items


def verify_bundle(
    bundle: dict[str, Any],
    *,
    state_path: Path = DEFAULT_STATE_PATH,
) -> dict[str, Any]:
    """Reverify every bundle item against its exact pinned normalization observation."""
    items = _validate_bundle_shape(bundle)
    for item in items:
        identity = _evidence_identity({"ok": True, **item})
        exact = _citation_from_exact_observation(
            state_path=state_path,
            normalization_observation_id=identity["normalization_observation_id"],
            block_ref=identity["block_ref"],
        )
        current = _bundle_item(exact)
        if current != item:
            raise GroundingError(
                f"bundled evidence no longer matches pinned local evidence: {item['evidence_id']}"
            )

    return {
        "ok": True,
        "type": "evidence_bundle_validation",
        "bundle_id": bundle["bundle_id"],
        "bundle_sha256": bundle["bundle_sha256"],
        "item_count": bundle["item_count"],
        "total_chars": bundle["total_chars"],
        "citation_integrity": "VALID",
        "provenance_integrity": "VALID",
        "semantic_support": "UNASSESSED",
    }


def _claim_core(
    *,
    claim_text: str,
    bundle: dict[str, Any],
    citation_ids: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": CLAIM_SCHEMA_VERSION,
        "type": "claim_candidate",
        "status": "UNREVIEWED",
        "semantic_support": "UNASSESSED",
        "claim_text": claim_text,
        "bundle_id": bundle["bundle_id"],
        "bundle_sha256": bundle["bundle_sha256"],
        "citations": citation_ids,
    }


def make_claim_candidate(
    claim_text: str,
    citation_ids: Iterable[str],
    bundle: dict[str, Any],
    *,
    state_path: Path = DEFAULT_STATE_PATH,
) -> dict[str, Any]:
    """Create an UNREVIEWED structurally grounded claim candidate."""
    verify_bundle(bundle, state_path=state_path)
    text = claim_text.strip() if isinstance(claim_text, str) else ""
    if not text:
        raise GroundingError("claim_text must be non-empty")

    ids = list(citation_ids)
    if not ids or not all(isinstance(item, str) and item for item in ids):
        raise GroundingError("a claim candidate requires at least one evidence citation id")
    if len(ids) != len(set(ids)):
        raise GroundingError("claim candidate contains duplicate citation ids")

    available = {item["evidence_id"] for item in bundle["items"]}
    unknown = [item for item in ids if item not in available]
    if unknown:
        raise GroundingError(f"claim candidate cites unknown evidence ids: {unknown}")

    core = _claim_core(claim_text=text, bundle=bundle, citation_ids=ids)
    digest = _sha256(core)
    return {**core, "claim_sha256": digest, "claim_id": f"cc-{digest[:20]}"}


def validate_claim_candidate(
    candidate: dict[str, Any],
    bundle: dict[str, Any],
    *,
    state_path: Path = DEFAULT_STATE_PATH,
) -> dict[str, Any]:
    """Validate citation/provenance integrity without claiming semantic entailment."""
    bundle_validation = verify_bundle(bundle, state_path=state_path)
    if not isinstance(candidate, dict):
        raise GroundingError("claim candidate must be a JSON object")
    _require_exact_keys(candidate, _CLAIM_KEYS, "claim candidate")
    if candidate.get("schema_version") != CLAIM_SCHEMA_VERSION:
        raise GroundingError(f"unsupported claim schema version: {candidate.get('schema_version')}")
    if candidate.get("type") != "claim_candidate":
        raise GroundingError("candidate type must be claim_candidate")
    if candidate.get("status") != "UNREVIEWED":
        raise GroundingError("Phase 4A claim candidates must remain UNREVIEWED")
    if candidate.get("semantic_support") != "UNASSESSED":
        raise GroundingError("Phase 4A semantic_support must remain UNASSESSED")
    if candidate.get("bundle_id") != bundle["bundle_id"]:
        raise GroundingError("claim candidate bundle_id does not match supplied bundle")
    if candidate.get("bundle_sha256") != bundle["bundle_sha256"]:
        raise GroundingError("claim candidate bundle SHA-256 does not match supplied bundle")

    claim_text = candidate.get("claim_text")
    if not isinstance(claim_text, str) or not claim_text.strip():
        raise GroundingError("claim_text must be non-empty")
    citations = candidate.get("citations")
    if not isinstance(citations, list) or not citations:
        raise GroundingError("claim candidate requires at least one citation")
    if not all(isinstance(item, str) and item for item in citations):
        raise GroundingError("claim citations must be non-empty evidence ids")
    if len(citations) != len(set(citations)):
        raise GroundingError("claim candidate contains duplicate citation ids")

    available = {item["evidence_id"] for item in bundle["items"]}
    unknown = [item for item in citations if item not in available]
    if unknown:
        raise GroundingError(f"claim candidate cites unknown evidence ids: {unknown}")

    core = _claim_core(claim_text=claim_text, bundle=bundle, citation_ids=citations)
    expected_sha = _sha256(core)
    actual_sha = _require_hex_sha256(candidate.get("claim_sha256"), "claim_sha256")
    if actual_sha != expected_sha:
        raise GroundingError("claim SHA-256 does not match canonical claim content")
    if candidate.get("claim_id") != f"cc-{expected_sha[:20]}":
        raise GroundingError("claim_id does not match claim SHA-256")

    return {
        "ok": True,
        "type": "claim_candidate_validation",
        "claim_id": candidate["claim_id"],
        "bundle_id": bundle_validation["bundle_id"],
        "citation_count": len(citations),
        "citation_integrity": "VALID",
        "provenance_integrity": "VALID",
        "review_status": "UNREVIEWED",
        "semantic_support": "UNASSESSED",
        "semantic_truth": "UNASSESSED",
    }


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GroundingError(f"could not read {label} file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GroundingError(f"{label} file is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise GroundingError(f"{label} file must contain a JSON object: {path}")
    return value


def format_text(payload: dict[str, Any]) -> str:
    """Render artifacts and validation results without confusing artifacts with errors."""
    if payload.get("ok") is False:
        return f"ERROR: {payload.get('error', 'unknown grounding error')}"

    if payload.get("type") == "evidence_bundle":
        lines = [
            "EVIDENCE BUNDLE — external data only",
            f"Bundle: {payload['bundle_id']}",
            f"SHA-256: {payload['bundle_sha256']}",
            f"Items: {payload['item_count']} | chars: {payload['total_chars']}",
        ]
        for item in payload["items"]:
            heading = " > ".join(item["block"]["heading_path"]) or "(root)"
            lines.extend(
                [
                    "",
                    f"[{item['evidence_id']}] {item['document'].get('title') or '(untitled)'}",
                    f"Source: {item['document']['source_id']}",
                    f"Block: {item['block']['ref']} ({item['block']['kind']})",
                    f"Heading: {heading}",
                    item["block"]["text"],
                ]
            )
        return "\n".join(lines)

    if payload.get("type") == "evidence_bundle_validation":
        return "\n".join(
            [
                f"Bundle {payload['bundle_id']}: VALID",
                f"Items: {payload['item_count']} | chars: {payload['total_chars']}",
                "Citation integrity: VALID",
                "Provenance integrity: VALID",
                "Semantic support: UNASSESSED",
            ]
        )

    if payload.get("type") == "claim_candidate":
        return "\n".join(
            [
                "CLAIM CANDIDATE — UNREVIEWED",
                f"Claim: {payload['claim_text']}",
                f"Claim id: {payload['claim_id']}",
                f"Bundle: {payload['bundle_id']}",
                f"Citations: {', '.join(payload['citations'])}",
                "Semantic support: UNASSESSED",
            ]
        )

    if payload.get("type") == "claim_candidate_validation":
        return "\n".join(
            [
                f"Claim {payload['claim_id']}: citation contract VALID",
                f"Citations: {payload['citation_count']}",
                "Citation integrity: VALID",
                "Provenance integrity: VALID",
                "Review status: UNREVIEWED",
                "Semantic support: UNASSESSED",
                "Semantic truth: UNASSESSED",
            ]
        )

    raise GroundingError(f"unsupported grounding payload type: {payload.get('type')}")


def _add_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="human-readable text (default) or structured JSON",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    bundle_parser = subparsers.add_parser("bundle", help="build a verified evidence bundle")
    bundle_parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    bundle_parser.add_argument(
        "--citation",
        nargs=3,
        action="append",
        metavar=("SOURCE", "URL", "BLOCK"),
        required=True,
        help="repeatable exact Phase 3B citation selector",
    )
    bundle_parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    bundle_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    _add_format(bundle_parser)

    verify_parser = subparsers.add_parser("verify-bundle", help="reverify a saved bundle")
    verify_parser.add_argument("bundle", type=Path)
    verify_parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    _add_format(verify_parser)

    make_parser = subparsers.add_parser("make-claim", help="create an unreviewed claim candidate")
    make_parser.add_argument("bundle", type=Path)
    make_parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    make_parser.add_argument("--text", required=True)
    make_parser.add_argument("--cite", action="append", required=True, dest="citation_ids")
    _add_format(make_parser)

    validate_parser = subparsers.add_parser(
        "validate-claim", help="validate a claim candidate against a verified bundle"
    )
    validate_parser.add_argument("bundle", type=Path)
    validate_parser.add_argument("claim", type=Path)
    validate_parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    _add_format(validate_parser)

    args = parser.parse_args()
    try:
        if args.command == "bundle":
            payload = build_bundle(
                [tuple(value) for value in args.citation],
                state_path=args.state,
                max_items=args.max_items,
                max_chars=args.max_chars,
            )
        elif args.command == "verify-bundle":
            payload = verify_bundle(_read_json(args.bundle, "bundle"), state_path=args.state)
        elif args.command == "make-claim":
            payload = make_claim_candidate(
                args.text,
                args.citation_ids,
                _read_json(args.bundle, "bundle"),
                state_path=args.state,
            )
        else:
            payload = validate_claim_candidate(
                _read_json(args.claim, "claim"),
                _read_json(args.bundle, "bundle"),
                state_path=args.state,
            )
    except (GroundingError, EvidenceError, ValueError) as exc:
        payload = {"ok": False, "error": str(exc)}

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_text(payload))
    return 1 if payload.get("ok") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
