# spanish-news-nlp-pipeline

A small, **fully reproducible** Spanish-language NLP pipeline: collect news headlines
from public RSS feeds, clean and deduplicate them, build a stratified dataset, train
baseline classifiers and report honest metrics.

> **Why this exists** — built in the open as a compact evidence piece for my application
> to CENIA's **LatamGPT** internship: it mirrors the day-to-day discipline of dataset
> work for LLM projects — collection, weak supervision, cleaning, leakage-safe splits,
> baselines and metrics — at a size anyone can run on a laptop in under a minute.

## Pipeline

```text
Google News RSS (es-419 / CL, 6 sections)
        │
        ▼
src/fetch_data.py      → data/raw/headlines_snapshot.jsonl   (committed snapshot)
        ▼
src/build_dataset.py   → normalize · dedupe · stratified 75/25 split (seed=42)
        ▼
src/train_baseline.py  → majority baseline · TF-IDF (1-2 grams) + LogisticRegression
        ▼
src/evaluate.py        → accuracy · macro P/R/F1 · per-class · confusion matrix
                         → outputs/metrics.json
```

The classification label is the editorial section of the source feed (**weak
supervision** — no manual annotation), across 6 classes: `nacional`, `economia`,
`tecnologia`, `deportes`, `salud`, `ciencia`.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Reproduce results from the committed snapshot (no network needed):
SKIP_FETCH=1 ./run_all.sh

# Or refresh the snapshot with today's headlines first:
./run_all.sh

# Unit tests (text normalization / dedup):
pytest
```

All commands run from the repo root.

## Results

Committed snapshot (fetched 2026-06-12 UTC): **360 headlines → 347 unique** after
normalization and dedup; train 260 / test 87, stratified, seed 42.

| model | accuracy | precision (macro) | recall (macro) | F1 (macro) |
|---|---:|---:|---:|---:|
| majority (floor) | 0.195 | 0.033 | 0.167 | 0.054 |
| TF-IDF + LogReg | **0.517** | 0.417 | 0.453 | **0.432** |

**Honest read:** short headlines, overlapping sections (`salud` vs `ciencia`) and only
260 training examples make this genuinely hard — the TF-IDF baseline beats the majority
floor by ~2.6× accuracy, and that gap (not the absolute score) is the meaningful signal
at this scale. The value of the repo is the **pipeline discipline**: reproducible
snapshot, leakage-safe splits, balanced class weights and macro metrics on an imbalanced
label set. Full per-class breakdown and confusion matrix in
[`outputs/metrics.json`](outputs/metrics.json).

## Design decisions

- **Weak supervision** (feed section = label): cheap, scalable, and honest about its
  noise — section overlap is reported, not hidden.
- **Accent/case-insensitive dedup** before splitting, because Google News repeats
  headlines across sections; duplicates would otherwise leak between train and test.
- **Split before any fitting** — the vectorizer only ever sees training data.
- **`class_weight="balanced"`** because section sizes are uneven (`economia` n=20).
- **Macro-averaged metrics** so minority classes count as much as majority ones.
- **Committed snapshot** so a fresh clone reproduces the exact numbers above without
  network access; `./run_all.sh` re-fetches for a current run.

## Repo structure

```text
feeds.json                  feed list (label ↔ RSS url)
src/fetch_data.py           RSS → JSONL snapshot
src/clean_text.py           pure normalization helpers (unit-tested)
src/build_dataset.py        clean + dedupe + stratified split
src/train_baseline.py       majority + TF-IDF/LogReg models
src/evaluate.py             metrics → outputs/metrics.json
tests/                      pytest suite for clean_text
data/                       snapshot + data documentation (see data/README.md)
outputs/metrics.json        committed example results
```

## Limitations & next steps

- Small snapshot (~350 headlines) — accumulate snapshots over time for a real corpus.
- Labels are weak: editorial sections overlap; a manually-audited eval slice would
  quantify that noise.
- Baselines only, by design. Natural next step: fine-tune a Spanish transformer
  (e.g. BETO) with PyTorch and compare against this floor, plus probability
  calibration and a minimal serving endpoint.

## Author

**Tomás Sotz** — [portfolio](https://cookiecodespy.github.io) ·
[GitHub](https://github.com/cookiecodespy) — Santiago, Chile.

Code under [MIT](LICENSE); headline copyright remains with each publisher
(see [data/README.md](data/README.md)).
