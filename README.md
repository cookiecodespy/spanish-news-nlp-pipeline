# spanish-news-nlp-pipeline

A small, **fully reproducible** Spanish-language NLP pipeline: collect news headlines
from public RSS feeds, clean and deduplicate them, build a stratified dataset, train
baseline classifiers and report honest metrics.

> **Why this exists** — most of my work is agent systems on top of LLMs; this repo is
> me practicing the layer underneath: the dataset discipline that Spanish-language LLM
> work actually runs on — collection, weak supervision, cleaning, leakage-safe splits,
> baselines and honest metrics — at a size anyone can run on a laptop in under a minute.

## Project evolution

This repository is now evolving **in public** from that original NLP experiment into a
research/knowledge pipeline for AI-agent engineering.

The existing implementation remains the preserved **v1 baseline**. The new **v2** is
being built incrementally in small, reviewable commits rather than replacing v1 in one
large rewrite.

The direction for v2 is:

```text
allowlisted official sources
        ↓
discovery
        ↓
ingestion + provenance
        ↓
normalized research artifacts
        ↓
knowledge cards
        ↓
human-reviewed doctrine candidates
        ↓
Obsidian / agent consumption
```

Key principles:

- primary and official sources first;
- default-deny source allowlist;
- external content is data, never instructions;
- provenance from every derived artifact back to original evidence;
- downloaded source documents stay local by default unless redistribution is clearly permitted;
- no automatic promotion from research note to canonical agent guidance;
- add infrastructure only when a real need justifies it.

See [`docs/SOURCE_POLICY.md`](docs/SOURCE_POLICY.md) for the trust model and
[`sources/registry.json`](sources/registry.json) for the initial official-source registry.
Development is tracked publicly in GitHub issues and small feature branches.

## V2 current commands

V2 is still under active development, but the source-trust and first discovery layers
are executable.

Validate the committed official-source registry entirely offline:

```bash
python -m research_pipeline.registry
```

Run one **live, shallow discovery** against an explicitly allowlisted source:

```bash
python -m research_pipeline.live_discovery --source anthropic-engineering
```

Live discovery checks `robots.txt`, uses bounded timeouts and response sizes, validates
every redirect, stays inside the source allowlist, and prints candidate URLs as JSON.
It does **not** recursively crawl or download the discovered documents.

Available source IDs currently live in [`sources/registry.json`](sources/registry.json).
All automated tests remain offline.

## V1 pipeline

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

# Reproduce v1 results from the committed snapshot (no network needed):
SKIP_FETCH=1 ./run_all.sh

# Or refresh the snapshot with today's headlines first:
./run_all.sh

# Offline tests:
pytest
```

All commands run from the repo root.

## V1 results

Committed snapshot (fetched 2026-06-12 UTC): **360 headlines → 347 unique** after
normalization and dedup; train 260 / test 87, stratified, seed 42.

| model | accuracy | precision (macro) | recall (macro) | F1 (macro) |
|---|---:|---:|---:|---:|
| majority (floor) | 0.195 | 0.033 | 0.167 | 0.054 |
| TF-IDF + LogReg | **0.517** | 0.417 | 0.453 | **0.432** |

**Honest read:** short headlines, overlapping sections (`salud` vs `ciencia`) and only
260 training examples make this genuinely hard — the TF-IDF baseline beats the majority
floor by ~2.6× accuracy, and that gap (not the absolute score) is the meaningful signal
at this scale. The value of v1 is the **pipeline discipline**: reproducible snapshot,
leakage-safe splits, balanced class weights and macro metrics on an imbalanced label set.
Full per-class breakdown and confusion matrix live in
[`outputs/metrics.json`](outputs/metrics.json).

## V1 design decisions

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
feeds.json                  v1 feed list (label ↔ RSS url)
src/                        v1 NLP implementation
tests/                      offline tests for v1 and v2 foundations
data/                       v1 snapshot + data documentation
outputs/metrics.json        committed v1 example results

research_pipeline/          v2 trust, discovery and future ingestion code
docs/                       v2 project policies and architecture notes
sources/registry.json       v2 allowlisted official-source registry
```

## V1 limitations

- Small snapshot (~350 headlines).
- Labels are weak: editorial sections overlap.
- Baselines only, by design.
- The original experiment is intentionally small and laptop-friendly.

Those limitations are preserved rather than hidden. New development is focused on the
v2 research/knowledge pipeline instead of expanding v1 into a larger classifier project.

## Author

**Tomás Sotz** — [portfolio](https://cookiecodespy.github.io) ·
[GitHub](https://github.com/cookiecodespy) — Santiago, Chile.

Code under [MIT](LICENSE); headline copyright remains with each publisher
(see [data/README.md](data/README.md)).
