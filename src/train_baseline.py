"""Train two headline classifiers and persist them together.

Models:
- ``majority``: most-frequent-class baseline — the floor any real model must beat.
- ``tfidf_logreg``: TF-IDF (word 1-2 grams) + Logistic Regression with balanced
  class weights, because the section sizes are uneven.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

SEED = 42


def build_models() -> dict[str, object]:
    return {
        "majority": DummyClassifier(strategy="most_frequent"),
        "tfidf_logreg": Pipeline(
            [
                (
                    "tfidf",
                    TfidfVectorizer(
                        ngram_range=(1, 2),
                        min_df=1,
                        sublinear_tf=True,
                        strip_accents="unicode",
                        lowercase=True,
                    ),
                ),
                (
                    "clf",
                    LogisticRegression(
                        max_iter=1000,
                        class_weight="balanced",
                        random_state=SEED,
                    ),
                ),
            ]
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, default=Path("data/processed/train.csv"))
    parser.add_argument("--out", type=Path, default=Path("outputs/models.joblib"))
    args = parser.parse_args()

    train_df = pd.read_csv(args.train)
    models = build_models()
    for name, model in models.items():
        model.fit(train_df["title"], train_df["label"])
        print(f"trained {name} on {len(train_df)} examples")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(models, args.out)
    print(f"saved -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
