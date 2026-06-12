"""Evaluate the trained models on the held-out test split and persist metrics.

Reports accuracy plus macro-averaged precision/recall/F1 — macro treats every
class equally, which is the honest choice for an imbalanced label set — and the
full per-class breakdown with the confusion matrix.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
)


def evaluate_model(model: object, X, y, labels: list[str]) -> dict:
    predictions = model.predict(X)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y, predictions, average="macro", zero_division=0
    )
    report = classification_report(
        y, predictions, labels=labels, output_dict=True, zero_division=0
    )
    return {
        "accuracy": round(accuracy_score(y, predictions), 4),
        "precision_macro": round(precision, 4),
        "recall_macro": round(recall, 4),
        "f1_macro": round(f1, 4),
        "per_class": {
            label: {
                "precision": round(report[label]["precision"], 4),
                "recall": round(report[label]["recall"], 4),
                "f1": round(report[label]["f1-score"], 4),
                "support": int(report[label]["support"]),
            }
            for label in labels
        },
        "confusion_matrix": confusion_matrix(y, predictions, labels=labels).tolist(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", type=Path, default=Path("data/processed/test.csv"))
    parser.add_argument("--models", type=Path, default=Path("outputs/models.joblib"))
    parser.add_argument("--out", type=Path, default=Path("outputs/metrics.json"))
    args = parser.parse_args()

    test_df = pd.read_csv(args.test)
    labels = sorted(test_df["label"].unique())
    models = joblib.load(args.models)

    results = {
        "n_test": len(test_df),
        "labels": labels,
        "models": {
            name: evaluate_model(model, test_df["title"], test_df["label"], labels)
            for name, model in models.items()
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{'model':<14} {'acc':>6} {'P-mac':>6} {'R-mac':>6} {'F1-mac':>6}")
    for name, metrics in results["models"].items():
        print(
            f"{name:<14} {metrics['accuracy']:>6.3f} {metrics['precision_macro']:>6.3f} "
            f"{metrics['recall_macro']:>6.3f} {metrics['f1_macro']:>6.3f}"
        )
    print(f"\nfull metrics -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
