"""Phase 3A deterministic normalization of locally stored Phase 2A HTML evidence.

No network access occurs here. Raw source bytes are verified against their recorded hash,
then a pinned extractor creates a local structured artifact for later citation and
knowledge extraction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any
from unicodedata import normalize as unicode_normalize

from trafilatura import bare_extraction, extract

from research_pipeline.discovery import normalize_url
from research_pipeline.discovery_state import DEFAULT_STATE_PATH, connect_state
from research_pipeline.ingestion_state import ensure_ingestion_schema
from research_pipeline.normalization_state import (
    NormalizationStateError,
    ensure_normalization_schema,
    latest_ingestion_rows,
    record_failure,
    record_success,
)
from research_pipeline.registry import DEFAULT_REGISTRY_PATH, RegistryError, load_registry

EXTRACTOR_NAME = "trafilatura"
EXTRACTOR_VERSION = "2.2.0"
ARTIFACT_SCHEMA_VERSION = 1
NORMALIZED_OBJECTS_DIRNAME = "normalized/sha256"

EXTRACTOR_OPTIONS = {
    "output_format": "markdown",
    "include_comments": False,
    "include_tables": True,
    "include_links": False,
}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LIST_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")


class NormalizationError(RuntimeError):
    """Raised when stored evidence cannot be normalized safely."""


@dataclass(frozen=True)
class NormalizationResult:
    source_id: str
    requested_url: str
    ingestion_observation_id: int
    status: str
    classification: str | None
    raw_sha256: str
    normalized_sha256: str | None
    artifact_path: str | None
    title: str | None
    block_count: int | None
    char_count: int | None
    error: str | None


class _DeclaredMetadataParser(HTMLParser):
    """Collect page-declared metadata without granting it any policy authority."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical_href: str | None = None
        self.html_lang: str | None = None
        self.meta: dict[str, list[str]] = {}
        self.title_parts: list[str] = []
        self._in_title = False
        self._json_ld_depth = 0
        self._json_ld_parts: list[str] = []
        self.json_ld_documents: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        values = {key.lower(): value for key, value in attrs if value is not None}

        if name == "html" and not self.html_lang:
            lang = values.get("lang")
            if lang:
                self.html_lang = lang.strip()

        if name == "link" and not self.canonical_href:
            rel = values.get("rel", "")
            rel_tokens = {part.lower() for part in rel.split()}
            href = values.get("href")
            if "canonical" in rel_tokens and href:
                self.canonical_href = href.strip()

        if name == "meta":
            key = (
                values.get("property")
                or values.get("name")
                or values.get("itemprop")
                or values.get("http-equiv")
            )
            content = values.get("content")
            if key and content:
                self.meta.setdefault(key.strip().lower(), []).append(content.strip())

        if name == "title":
            self._in_title = True

        if name == "script" and values.get("type", "").lower() == "application/ld+json":
            self._json_ld_depth += 1
            self._json_ld_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._json_ld_depth:
            self._json_ld_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name == "title":
            self._in_title = False
        if name == "script" and self._json_ld_depth:
            raw = "".join(self._json_ld_parts).strip()
            if raw:
                try:
                    self.json_ld_documents.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
            self._json_ld_depth = 0
            self._json_ld_parts = []


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _first_meta(parser: _DeclaredMetadataParser, *keys: str) -> str | None:
    for key in keys:
        values = parser.meta.get(key.lower(), [])
        for value in values:
            cleaned = _clean_string(value)
            if cleaned:
                return cleaned
    return None


def _iter_json_objects(value: Any):
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if graph is not None:
            yield from _iter_json_objects(graph)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_json_objects(item)


def _article_json_objects(parser: _DeclaredMetadataParser) -> list[dict[str, Any]]:
    preferred_types = {
        "article",
        "newsarticle",
        "techarticle",
        "blogposting",
        "scholarlyarticle",
        "report",
    }
    all_objects: list[dict[str, Any]] = []
    preferred: list[dict[str, Any]] = []
    for document in parser.json_ld_documents:
        for obj in _iter_json_objects(document):
            all_objects.append(obj)
            raw_type = obj.get("@type")
            types = raw_type if isinstance(raw_type, list) else [raw_type]
            if any(isinstance(item, str) and item.lower() in preferred_types for item in types):
                preferred.append(obj)
    return preferred or all_objects


def _first_json_value(objects: list[dict[str, Any]], *keys: str) -> str | None:
    for obj in objects:
        for key in keys:
            cleaned = _clean_string(obj.get(key))
            if cleaned:
                return cleaned
    return None


def _author_names(value: Any) -> list[str]:
    if isinstance(value, str):
        cleaned = _clean_string(value)
        return [cleaned] if cleaned else []
    if isinstance(value, dict):
        cleaned = _clean_string(value.get("name"))
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            names.extend(_author_names(item))
        return names
    return []


def _declared_authors(
    parser: _DeclaredMetadataParser,
    json_objects: list[dict[str, Any]],
) -> list[str]:
    names: list[str] = []
    for obj in json_objects:
        names.extend(_author_names(obj.get("author")))
    for key in ("author", "article:author", "byl"):
        for value in parser.meta.get(key, []):
            cleaned = _clean_string(value)
            if cleaned:
                names.append(cleaned)
    # Stable ordered dedupe.
    return list(dict.fromkeys(names))


def _extract_metadata(body: bytes, final_url: str, document) -> dict[str, Any]:
    parser = _DeclaredMetadataParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    json_objects = _article_json_objects(parser)

    title_tag = _clean_string("".join(parser.title_parts))
    title = (
        _first_json_value(json_objects, "headline", "name")
        or _first_meta(parser, "og:title", "twitter:title")
        or title_tag
        or _clean_string(getattr(document, "title", None))
    )

    authors = _declared_authors(parser, json_objects)
    if not authors:
        fallback_author = _clean_string(getattr(document, "author", None))
        if fallback_author:
            authors = [fallback_author]

    published_at = (
        _first_json_value(json_objects, "datePublished")
        or _first_meta(
            parser,
            "article:published_time",
            "datepublished",
            "publishdate",
            "date",
            "dc.date",
            "dcterms.date",
        )
        or _clean_string(getattr(document, "date", None))
    )
    modified_at = _first_json_value(json_objects, "dateModified") or _first_meta(
        parser,
        "article:modified_time",
        "og:updated_time",
        "datemodified",
    )
    language = (
        _clean_string(parser.html_lang)
        or _first_json_value(json_objects, "inLanguage")
        or _first_meta(parser, "content-language", "language", "og:locale")
        or _clean_string(getattr(document, "language", None))
    )

    declared_canonical_url = None
    if parser.canonical_href:
        declared_canonical_url = normalize_url(final_url, parser.canonical_href)

    return {
        "title": title,
        "authors": authors,
        "published_at": published_at,
        "modified_at": modified_at,
        "language": language,
        "declared_canonical_url": declared_canonical_url,
        "site_name": _clean_string(getattr(document, "sitename", None)),
        "description": _clean_string(getattr(document, "description", None)),
    }


def normalize_markdown(markdown: str) -> str:
    """Apply a small stable text canonicalization after extractor output."""
    text = unicode_normalize("NFC", markdown).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    output: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if output and not blank:
                output.append("")
            blank = True
            continue
        output.append(line)
        blank = False
    return "\n".join(output).strip()


def _split_blocks(markdown: str) -> list[str]:
    """Split Markdown deterministically while keeping fenced code blocks intact."""
    blocks: list[str] = []
    buffer: list[str] = []
    fence: str | None = None

    def flush() -> None:
        if buffer:
            text = "\n".join(buffer).strip()
            if text:
                blocks.append(text)
            buffer.clear()

    for line in markdown.splitlines():
        stripped = line.strip()
        fence_match = re.match(r"^(```+|~~~+)", stripped)
        if fence_match:
            marker = fence_match.group(1)[0]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            buffer.append(line)
            continue

        heading = _HEADING_RE.match(stripped)
        if fence is None and heading:
            flush()
            blocks.append(stripped)
            continue

        if fence is None and not stripped:
            flush()
            continue

        buffer.append(line)

    flush()
    return blocks


def _block_kind(text: str) -> str:
    first = text.splitlines()[0].strip()
    if _HEADING_RE.match(first):
        return "heading"
    if first.startswith("```") or first.startswith("~~~"):
        return "code"
    if first.startswith(">"):
        return "quote"
    if _LIST_RE.match(first):
        return "list"
    if "|" in first and len(text.splitlines()) > 1:
        return "table"
    return "paragraph"


def build_blocks(markdown: str) -> list[dict[str, Any]]:
    """Build ordered, deterministic block references with heading context."""
    blocks: list[dict[str, Any]] = []
    heading_stack: list[str] = []

    for ordinal, text in enumerate(_split_blocks(markdown), start=1):
        match = _HEADING_RE.match(text.splitlines()[0].strip())
        if match:
            level = len(match.group(1))
            heading = _clean_string(match.group(2)) or ""
            heading_stack = heading_stack[: level - 1]
            while len(heading_stack) < level - 1:
                heading_stack.append("")
            heading_stack.append(heading)

        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        blocks.append(
            {
                "ref": f"b{ordinal:04d}-{digest}",
                "kind": _block_kind(text),
                "heading_path": [item for item in heading_stack if item],
                "text": text,
            }
        )

    return blocks


def _runtime_extractor_version() -> str:
    try:
        runtime = package_version(EXTRACTOR_NAME)
    except Exception as exc:  # importlib metadata failures are operational setup errors.
        raise NormalizationError(f"could not determine {EXTRACTOR_NAME} version: {exc}") from exc
    if runtime != EXTRACTOR_VERSION:
        raise NormalizationError(
            f"unsupported {EXTRACTOR_NAME} version: {runtime} (expected {EXTRACTOR_VERSION})"
        )
    return runtime


def extract_artifact(body: bytes, final_url: str) -> dict[str, Any]:
    """Extract one provenance-free normalized content artifact from verified raw bytes."""
    runtime_version = _runtime_extractor_version()
    document = bare_extraction(
        body,
        url=final_url,
        with_metadata=True,
        include_comments=False,
        include_tables=True,
        include_links=False,
    )
    markdown = extract(
        body,
        url=final_url,
        output_format="markdown",
        with_metadata=False,
        include_comments=False,
        include_tables=True,
        include_links=False,
    )
    if document is None or not markdown:
        raise NormalizationError("extractor returned no usable main content")

    normalized_markdown = normalize_markdown(markdown)
    blocks = build_blocks(normalized_markdown)
    if not normalized_markdown or not blocks:
        raise NormalizationError("normalized artifact is empty")

    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "extractor": {
            "name": EXTRACTOR_NAME,
            "version": runtime_version,
            "options": dict(EXTRACTOR_OPTIONS),
        },
        "metadata": _extract_metadata(body, final_url, document),
        "markdown": normalized_markdown,
        "blocks": blocks,
    }


def artifact_bytes(artifact: dict[str, Any]) -> bytes:
    return json.dumps(
        artifact,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def artifact_sha256(artifact: dict[str, Any]) -> str:
    return hashlib.sha256(artifact_bytes(artifact)).hexdigest()


def artifact_relative_path(sha256: str) -> Path:
    if len(sha256) != 64 or any(ch not in "0123456789abcdef" for ch in sha256):
        raise NormalizationError("invalid normalized SHA-256 hex digest")
    return Path(NORMALIZED_OBJECTS_DIRNAME) / sha256[:2] / f"{sha256}.json"


def store_artifact(state_path: Path, sha256: str, artifact: dict[str, Any]) -> str:
    payload = artifact_bytes(artifact)
    actual = hashlib.sha256(payload).hexdigest()
    if actual != sha256:
        raise NormalizationError(
            f"normalized artifact digest mismatch: expected {sha256}, computed {actual}"
        )

    state_path = Path(state_path)
    relative = artifact_relative_path(sha256)
    path = state_path.parent / relative
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        if path.read_bytes() != payload:
            raise NormalizationError(
                f"normalized content-addressed object has different bytes: {relative}"
            )
        return relative.as_posix()

    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != payload:
            raise NormalizationError(
                f"normalized object race produced different bytes: {relative}"
            )
    return relative.as_posix()


def _raw_object_path(state_path: Path, object_path: str) -> Path:
    root = Path(state_path).parent.resolve()
    path = (root / object_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise NormalizationError(f"raw object path escapes local state directory: {object_path}") from exc
    return path


def _verified_raw_bytes(state_path: Path, row) -> bytes:
    path = _raw_object_path(state_path, str(row["object_path"]))
    try:
        body = path.read_bytes()
    except OSError as exc:
        raise NormalizationError(f"could not read raw object {row['object_path']}: {exc}") from exc

    actual = hashlib.sha256(body).hexdigest()
    if actual != row["sha256"]:
        raise NormalizationError(
            f"raw object SHA-256 mismatch for observation {row['id']}: "
            f"recorded {row['sha256']}, computed {actual}"
        )
    if len(body) != row["bytes_read"]:
        raise NormalizationError(
            f"raw object byte-count mismatch for observation {row['id']}: "
            f"recorded {row['bytes_read']}, actual {len(body)}"
        )
    return body


def normalize_ingestion_row(
    connection,
    row,
    *,
    state_path: Path = DEFAULT_STATE_PATH,
) -> NormalizationResult:
    """Normalize one successful raw ingestion observation without network access."""
    source_id = str(row["source_id"])
    requested_url = str(row["requested_url"])
    ingestion_id = int(row["id"])
    raw_sha256 = str(row["sha256"])

    try:
        body = _verified_raw_bytes(state_path, row)
        artifact = extract_artifact(body, str(row["final_url"]))
        normalized_sha = artifact_sha256(artifact)
        path = store_artifact(state_path, normalized_sha, artifact)
        metadata = artifact["metadata"]
        observation = record_success(
            connection,
            source_id=source_id,
            requested_url=requested_url,
            ingestion_observation_id=ingestion_id,
            raw_sha256=raw_sha256,
            extractor_name=EXTRACTOR_NAME,
            extractor_version=EXTRACTOR_VERSION,
            normalized_sha256=normalized_sha,
            artifact_path=path,
            title=metadata.get("title"),
            block_count=len(artifact["blocks"]),
            char_count=len(artifact["markdown"]),
        )
        return NormalizationResult(
            source_id=source_id,
            requested_url=requested_url,
            ingestion_observation_id=ingestion_id,
            status="SUCCESS",
            classification=observation.classification,
            raw_sha256=raw_sha256,
            normalized_sha256=normalized_sha,
            artifact_path=path,
            title=metadata.get("title"),
            block_count=len(artifact["blocks"]),
            char_count=len(artifact["markdown"]),
            error=None,
        )
    except (NormalizationError, OSError, ValueError) as exc:
        message = str(exc)
        record_failure(
            connection,
            source_id=source_id,
            requested_url=requested_url,
            ingestion_observation_id=ingestion_id,
            raw_sha256=raw_sha256,
            extractor_name=EXTRACTOR_NAME,
            extractor_version=EXTRACTOR_VERSION,
            error=message,
        )
        return NormalizationResult(
            source_id=source_id,
            requested_url=requested_url,
            ingestion_observation_id=ingestion_id,
            status="ERROR",
            classification=None,
            raw_sha256=raw_sha256,
            normalized_sha256=None,
            artifact_path=None,
            title=None,
            block_count=None,
            char_count=None,
            error=message,
        )


def normalize_source(
    connection,
    source_id: str,
    *,
    state_path: Path = DEFAULT_STATE_PATH,
    limit: int = 1,
) -> list[NormalizationResult]:
    """Normalize a bounded set of latest successful ingestions for one source."""
    ensure_ingestion_schema(connection)
    ensure_normalization_schema(connection)
    rows = latest_ingestion_rows(connection, source_id, limit=limit)
    if not rows:
        raise NormalizationError(
            f"no successful ingested HTML for {source_id}; run ingestion first"
        )
    return [
        normalize_ingestion_row(connection, row, state_path=state_path) for row in rows
    ]


def _payload(source_id: str, results: list[NormalizationResult]) -> dict[str, Any]:
    counts = {"NEW": 0, "UNCHANGED": 0, "CHANGED": 0}
    errors = 0
    for result in results:
        if result.status == "ERROR":
            errors += 1
        elif result.classification in counts:
            counts[result.classification] += 1
    return {
        "ok": errors == 0,
        "source_id": source_id,
        "extractor": {"name": EXTRACTOR_NAME, "version": EXTRACTOR_VERSION},
        "processed": len(results),
        "new_count": counts["NEW"],
        "unchanged_count": counts["UNCHANGED"],
        "changed_count": counts["CHANGED"],
        "error_count": errors,
        "results": [asdict(result) for result in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="enabled registry source id")
    parser.add_argument("--limit", type=int, default=1, help="maximum raw observations to normalize")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    args = parser.parse_args()

    connection = None
    try:
        registry = load_registry(args.registry)
        source = next(
            (
                item
                for item in registry["sources"]
                if item.get("id") == args.source
                and item.get("enabled") is True
                and item.get("official") is True
            ),
            None,
        )
        if source is None:
            raise NormalizationError(f"unknown or disabled source id: {args.source}")
        if args.limit < 1:
            raise NormalizationError("limit must be >= 1")

        connection = connect_state(args.state)
        results = normalize_source(
            connection,
            args.source,
            state_path=args.state,
            limit=args.limit,
        )
        payload = _payload(args.source, results)
    except (RegistryError, NormalizationError, NormalizationStateError) as exc:
        payload = {"ok": False, "source_id": args.source, "error": str(exc)}
    finally:
        if connection is not None:
            connection.close()

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
