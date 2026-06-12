"""Pure text-normalization helpers for news headlines.

Dependency-free on purpose: trivial to unit-test and to reuse outside the pipeline.
"""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")
# Google News appends the outlet to every title ("Headline - Outlet Name").
# Known limitation: a headline that legitimately ends in " - <words>" would also
# lose that tail; acceptable here because the source feeds always append the outlet.
_TRAILING_SOURCE_RE = re.compile(r"\s+-\s+[^-]{2,60}$")


def normalize_title(raw: str) -> str:
    """Normalize a headline: NFC unicode, outlet suffix removed, single-spaced, trimmed."""
    text = unicodedata.normalize("NFC", raw)
    text = _TRAILING_SOURCE_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def dedupe_key(title: str) -> str:
    """Accent- and case-insensitive identity used for near-duplicate detection."""
    decomposed = unicodedata.normalize("NFD", title.casefold())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return _WHITESPACE_RE.sub(" ", stripped).strip()


def dedupe(records: list[dict]) -> list[dict]:
    """Drop records whose normalized title was already seen (keeps the first occurrence)."""
    seen: set[str] = set()
    unique: list[dict] = []
    for record in records:
        key = dedupe_key(record["title"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique
