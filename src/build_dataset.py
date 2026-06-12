"""Build a clean, stratified train/test dataset from the raw headlines snapshot.

Steps: normalize titles -> drop near-duplicates -> drop under-represented classes ->
stratified split with a fixed seed, so every run over the same snapshot yields the
same dataset.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

from src.clean_text import dedupe, normalize_title

SEED = 42
TEST_SIZE = 0.25


def load_records(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=Path("data/raw/headlines_snapshot.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--min-per-class", type=int, default=15)
    args = parser.parse_args()

    records = load_records(args.raw)
    for record in records:
        record["title"] = normalize_title(record["title"])
    records = [r for r in records if r["title"]]
    records = dedupe(records)

    counts = Counter(r["label"] for r in records)
    kept_labels = {label for label, n in counts.items() if n >= args.min_per_class}
    dropped = {label: n for label, n in counts.items() if label not in kept_labels}
    if dropped:
        print(f"Dropped classes below {args.min_per_class} examples: {dropped}")

    df = pd.DataFrame([r for r in records if r["label"] in kept_labels])
    train_df, test_df = train_test_split(
        df, test_size=TEST_SIZE, random_state=SEED, stratify=df["label"]
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    train_df.to_csv(args.out_dir / "train.csv", index=False)
    test_df.to_csv(args.out_dir / "test.csv", index=False)

    print(f"\nClass distribution after cleaning ({len(df)} unique headlines):")
    for label, n in sorted(counts.items(), key=lambda item: -item[1]):
        marker = "" if label in kept_labels else "  (dropped)"
        print(f"  {label:<12} {n:>4}{marker}")
    print(f"\ntrain: {len(train_df)} rows | test: {len(test_df)} rows (seed={SEED})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
