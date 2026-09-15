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
discovery + local state
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

V2 is still under active development, but the source-trust, discovery, local-state,
operator-assurance, exact-byte ingestion and deterministic HTML-normalization layers are
executable.

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

By default, discovery keeps a local SQLite ledger at `.state/discovery.sqlite3`. That
file is gitignored. Repeated runs surface top-level `new_count` and `known_count` values,
so an operator can see what changed without opening SQLite or reading internal logs. A
custom local state path can be supplied with `--state PATH`.

Run deterministic local readiness checks without touching the network:

```bash
python -m research_pipeline.assurance doctor
```

`doctor` validates the registry, local-state readiness, configured entrypoints and the
exact pinned normalization extractor version (`trafilatura==2.2.0`).

See the latest discovery, ingestion and normalization outcome for every enabled source
without opening SQLite:

```bash
python -m research_pipeline.assurance status
```

The original top-level discovery fields remain stable for compatibility. Each source now
also exposes concise `ingestion` and `normalization` stage summaries, including the latest
classification, evidence hash, timestamp and error where applicable.

Explicitly smoke-test one official source against the real network:

```bash
python -m research_pipeline.assurance verify-live --source anthropic-engineering
```

Or omit `--source` to verify all enabled sources sequentially. Live verification reuses
the same robots, redirect, timeout and response-size policy as discovery and reports
`PASS`, `FAIL` or `BLOCKED` per source. It is a manual operator check, not a
network-dependent normal CI test, and it does not mutate discovery state or ingest
article bodies.

After discovery has populated the local candidate ledger, ingest a bounded number of
previously discovered HTML documents:

```bash
python -m research_pipeline.ingestion --source anthropic-engineering --limit 1
```

Phase 2A revalidates the current allowlist and the candidate's own `robots.txt` rules,
fetches only HTML under the same bounded network policy, preserves the **exact response
bytes** under the gitignored `.state/objects/sha256/` content-addressed store, computes
SHA-256, and records provenance in the same local SQLite state. The default limit is 1
so a first run cannot unexpectedly ingest an entire source.

The ingestion result is classified as:

- `NEW` — no earlier successful raw observation exists for that source URL;
- `UNCHANGED` — the exact fetched HTML bytes have the same SHA-256 as the prior success;
- `CHANGED` — the exact fetched HTML bytes have a different SHA-256.

**Important:** raw `CHANGED` is a transport fact, not a semantic conclusion. Dynamic
timestamps, scripts or page chrome can change raw HTML while the research content stays
equivalent.

`requested_url` and redirect-resolved `final_url` are stored separately. The final
transport URL is not mislabeled as document-canonical metadata.

Normalize the latest successful locally stored HTML without making another network
request:

```bash
python -m research_pipeline.normalization --source anthropic-engineering --limit 1
```

Phase 3A first re-reads the local raw object and verifies both its recorded byte count and
raw SHA-256. It then uses the exactly pinned `trafilatura==2.2.0` extractor to produce a
stable structured artifact containing declared metadata, normalized Markdown and ordered
citation blocks with deterministic block references. Normalized artifact bodies remain
local and gitignored under `.state/normalized/sha256/`.

The normalized artifact has its **own SHA-256**, separate from the immutable raw-object
hash. Normalization observations are classified as `NEW`, `UNCHANGED` or `CHANGED` only
against prior successes for the same URL **and the same extractor version**. Upgrading the
extractor therefore creates a new normalization baseline instead of pretending every
article changed.

This separation lets the pipeline represent facts such as:

```text
raw HTML SHA changed       → raw CHANGED
normalized artifact same   → normalized UNCHANGED
```

That means page chrome or scripts changed while the extracted research artifact remained
stable. Conversely, normalized `CHANGED` means the deterministic extracted artifact
changed; it is still **not yet a semantic-change judgment**.

Declared metadata such as title, author, dates, language or canonical URL is preserved as
source data. It does not widen the network allowlist or automatically become trusted
agent guidance.

Available source IDs currently live in [`sources/registry.json`](sources/registry.json).
All normal automated tests remain offline and deterministic.

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
normalization and dedup; train 260 / test 87, stratified, seed=42.

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

research_pipeline/          v2 trust, discovery, ingestion and normalization code
docs/                       v2 project policies and architecture notes
sources/registry.json       v2 allowlisted official-source registry
.state/                     local SQLite state + raw/normalized objects (gitignored)
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
