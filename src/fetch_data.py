"""Fetch Spanish-language news headlines from RSS feeds into a JSONL snapshot.

Each output line is one record:

    {"title": ..., "label": ..., "source": ..., "published": ..., "link": ..., "fetched_at": ...}

The label comes from the editorial section of the feed (weak supervision), so the
dataset needs no manual annotation. The committed snapshot keeps the rest of the
pipeline reproducible without network access.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

USER_AGENT = "spanish-news-nlp-pipeline/1.0 (research and educational use)"
TIMEOUT_S = 15


def fetch_feed(url: str) -> feedparser.FeedParserDict:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S)
    response.raise_for_status()
    return feedparser.parse(response.content)


def entry_source(entry: feedparser.FeedParserDict) -> str:
    # Google News nests the original outlet under <source>.
    source = getattr(entry, "source", None)
    if source is not None and getattr(source, "title", None):
        return source.title
    return "unknown"


def collect(feeds_config: dict) -> list[dict]:
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records: list[dict] = []
    for feed in feeds_config["feeds"]:
        parsed = fetch_feed(feed["url"])
        for entry in parsed.entries:
            title = getattr(entry, "title", "").strip()
            if not title:
                continue
            records.append(
                {
                    "title": title,
                    "label": feed["label"],
                    "source": entry_source(entry),
                    "published": getattr(entry, "published", ""),
                    "link": getattr(entry, "link", ""),
                    "fetched_at": fetched_at,
                }
            )
        print(f"{feed['label']:<12} {len(parsed.entries):>4} entries")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feeds", type=Path, default=Path("feeds.json"))
    parser.add_argument("--out", type=Path, default=Path("data/raw/headlines_snapshot.jsonl"))
    args = parser.parse_args()

    feeds_config = json.loads(args.feeds.read_text(encoding="utf-8"))
    records = collect(feeds_config)
    if not records:
        print("No records fetched — check network access or feed URLs.", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(records)} records -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
