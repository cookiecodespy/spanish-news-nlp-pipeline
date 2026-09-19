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
verified citation blocks
        ↓
immutable evidence bundles
        ↓
unreviewed claim candidates
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
- model output has less authority than deterministic pipeline state;
- add infrastructure only when a real need justifies it.

See [`docs/SOURCE_POLICY.md`](docs/SOURCE_POLICY.md) for the trust model and
[`sources/registry.json`](sources/registry.json) for the initial official-source registry.
Development is tracked publicly in GitHub issues and small feature branches.
For the **verified current status and remaining work**, see
[`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md).

## V2 current commands

V2 is still under active development. The trust, discovery, local-state, assurance,
exact-byte ingestion, deterministic normalization, verified citation, immutable grounding,
provider-neutral claim-extraction contract, and **offline human-review evaluation** layers
are executable. No generative-model provider or Jev API is integrated yet.

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

Inspect verified normalized documents or one exact citation block locally:

```bash
python -m research_pipeline.evidence list --source anthropic-engineering

python -m research_pipeline.evidence cite \
  --source anthropic-engineering \
  --url 'https://www.anthropic.com/engineering/example' \
  --block 'b0007-0123456789ab'
```

Phase 3B reverifies the selected normalized artifact and its provenance before returning
text. External blocks are explicitly typed `external_evidence` with
`trust=data_not_instructions`. See [`docs/EVIDENCE.md`](docs/EVIDENCE.md).

Package exact citations into a bounded immutable evidence bundle:

```bash
python -m research_pipeline.grounding bundle \
  --citation anthropic-engineering \
    'https://www.anthropic.com/engineering/example' \
    'b0007-0123456789ab' \
  --format json > bundle.json
```

Phase 4A pins each evidence item to an exact normalization observation and normalized SHA,
so historical citations do not move when a source changes later. Bundles have deterministic
ids/hashes and conservative context limits. A structural claim candidate can then cite only
real `evidence_id` values from that bundle and always remains `UNREVIEWED` with semantic
support/truth `UNASSESSED`. See [`docs/GROUNDING.md`](docs/GROUNDING.md).

Build the provider-neutral request that a future model will receive:

```bash
python -m research_pipeline.claim_extraction request bundle.json \
  --format json > request.json
```

Phase 4B gives the model only scoped evidence data and a narrow output contract. The model
may propose `claim_text` plus evidence ids; deterministic code owns claim ids/hashes,
status, bundle identity and all validation. A saved synthetic response can be tested
without any provider/network call:

```bash
python -m research_pipeline.claim_extraction validate-response \
  bundle.json request.json response.json
```

An empty proposal list is valid (`NO_CLAIMS`), avoiding a requirement to hallucinate. The
normal offline suite also exercises prompt-like text embedded inside evidence and rejects a
fake model that attempts to self-approve output or inject privileged fields. See
[`docs/CLAIM_EXTRACTION.md`](docs/CLAIM_EXTRACTION.md).

**Critical boundary:** citation/provenance integrity can be `VALID` while semantic support
and semantic truth remain `UNASSESSED`. No current v2 stage automatically turns a model
proposal into knowledge or doctrine.

### Phase 4C: offline evaluator complete; real-model pilot pending

**Phase 4C-1 is implemented:** a local, human-annotation-driven evaluator checks saved
provider-format proposals against the existing Phase 4B contract, then reports reviewed
citation-support judgments, finding coverage, abstention and explicit denominators. It is
not an automatic truth checker and has **not** produced results for a live model.

```bash
python -m research_pipeline.claim_evaluation \
  bundle.json request.json response.json review.json --format json
```

See [`docs/CLAIM_QUALITY_EVALUATION.md`](docs/CLAIM_QUALITY_EVALUATION.md) for the strict
review format. **Phase 4C-2 remains proposed:** before calling a real generative model,
prepare reviewed cases, get explicit owner approval for provider/model and spending cap,
and keep external article text and model I/O private. The evaluation protocol and release
gates live in [`docs/PHASE_4C_EVALUATION.md`](docs/PHASE_4C_EVALUATION.md).

[TypeSafe AI's Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) is
being considered for a **future, optional relevance/triage decision** over bounded
research metadata or extracts, potentially reusable by other agent projects through a
separate client. It does not generate claim text and will not replace the source allowlist,
robots, evidence checks, human review or the generative Phase 4C model. **Jev is not
integrated and early-access approval/API availability has not been confirmed.** See
[`docs/JEV_INTEGRATION.md`](docs/JEV_INTEGRATION.md) for the proposal and constraints.

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

research_pipeline/          v2 trust → evidence → grounding/extraction code
docs/                       v2 project policies and architecture contracts
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

## Contributing and security

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a PR and [SECURITY.md](SECURITY.md)
for private vulnerability reporting. The [project status](docs/PROJECT_STATUS.md)
distinguishes merged capabilities, pending model evaluation, and GitHub administrative
work tracked in [Issue #28](https://github.com/cookiecodespy/spanish-news-nlp-pipeline/issues/28).

## Author

**Tomás Sotz** — [portfolio](https://cookiecodespy.github.io) ·
[GitHub](https://github.com/cookiecodespy) — Santiago, Chile.

Code under [MIT](LICENSE); headline copyright remains with each publisher
(see [data/README.md](data/README.md)).
