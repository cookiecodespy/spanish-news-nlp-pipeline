# Evidence bundles and claim-candidate contract

Phase 4A creates the deterministic boundary between verified Phase 3B evidence and future
model-based claim extraction. It still makes **no LLM calls**.

The purpose of this layer is not to decide what is true. Its job is narrower and easier to
audit: a future claim candidate cannot enter the pipeline unless it points to exact,
verified evidence with immutable provenance.

## Semantic boundary

A successful validation may report:

```text
citation_integrity = VALID
provenance_integrity = VALID
review_status = UNREVIEWED
semantic_support = UNASSESSED
semantic_truth = UNASSESSED
```

`VALID` therefore means the citation contract is intact. It does **not** mean that the cited
text entails the claim, that the claim is correct, or that it should become knowledge or
doctrine.

## Immutable evidence references

Phase 3B human lookup uses:

```text
source_id + requested_url + block_ref
```

That is appropriate for asking for the current evidence baseline. A stored claim needs a
stronger identity because the source can change later.

Every Phase 4A bundle item is therefore pinned by:

```text
source_id
requested_url
normalization_observation_id
normalized_sha256
block_ref
```

The resulting `evidence_id` is deterministic over that immutable identity. If a page is
renormalized tomorrow, an old bundle still resolves its original observation. The verifier
never substitutes a newer or older observation silently.

## Trust boundary

Every external block retains:

```text
type = external_evidence
trust = data_not_instructions
```

A bundle itself is marked:

```text
type = evidence_bundle
trust = external_data_only
```

Text inside official research remains data even if it contains prompt-like prose, commands,
or text that resembles instructions. Phase 4A also rejects unexpected schema fields instead
of carrying arbitrary model/source-provided keys forward.

## Build a bounded evidence bundle

Start from exact Phase 3B block references:

```bash
python -m research_pipeline.grounding bundle \
  --citation anthropic-engineering \
    'https://www.anthropic.com/engineering/example' \
    'b0007-0123456789ab' \
  --format json > bundle.json
```

Repeat `--citation SOURCE URL BLOCK` to add more evidence.

Defaults are intentionally conservative:

- maximum 8 unique evidence blocks per bundle;
- maximum 12,000 evidence characters.

The CLI allows smaller/custom limits, but hard ceilings prevent accidental oversized
contexts:

- hard maximum 32 evidence blocks;
- hard maximum 50,000 evidence characters.

Duplicate immutable evidence references are deduplicated deterministically. Bundle items are
sorted deterministically before the canonical bundle SHA-256 is computed.

The bundle receives:

```text
bundle_sha256 = SHA-256(canonical bundle content)
bundle_id     = eb-<first 20 hex characters>
```

## Reverify a saved bundle

```bash
python -m research_pipeline.grounding verify-bundle bundle.json
```

Verification checks both the bundle's own canonical identity and every exact pinned local
evidence observation. It fails if:

- the bundle hash/id is wrong;
- an item schema contains unexpected/missing fields;
- an evidence id no longer matches its immutable identity;
- a pinned normalization observation is unavailable;
- its normalized artifact is missing or corrupt;
- the normalized SHA-256 differs;
- provenance no longer matches the linked ingestion observation;
- the block ref is missing/duplicated;
- the bundled block differs from the exact pinned evidence.

No stale fallback is allowed.

## Create an unreviewed claim candidate

Once a bundle exists, a future model (or a human during testing) may propose a claim that
cites one or more `evidence_id` values from that bundle.

For deterministic testing today:

```bash
python -m research_pipeline.grounding make-claim bundle.json \
  --text 'Workers should receive only the context required for their task.' \
  --cite ev-0123456789abcdef0123 \
  --format json > claim.json
```

The generated object is always:

```text
type = claim_candidate
status = UNREVIEWED
semantic_support = UNASSESSED
```

It also pins the exact `bundle_id` and `bundle_sha256`, carries explicit citation ids, and
gets a deterministic `claim_sha256` / `claim_id`.

Phase 4A refuses duplicate citation ids, unknown citation ids, empty claims, arbitrary extra
fields, attempts to mark semantic support as verified, or attempts to promote the candidate
past `UNREVIEWED`.

## Validate a claim candidate

```bash
python -m research_pipeline.grounding validate-claim bundle.json claim.json
```

The validator first reverifies the complete evidence bundle, then validates the candidate's
schema, bundle identity, claim identity and citation membership.

A success proves only:

1. the exact cited source evidence is locally present and cryptographically consistent;
2. the provenance chain remains intact;
3. the claim candidate names real evidence ids from that exact bundle;
4. the claim object itself has not changed since its canonical hash was produced.

It does **not** prove semantic entailment or truth.

## Why no model yet

Adding a model before this contract would make it possible to generate plausible summaries
whose relationship to source evidence was hard to audit. Phase 4A deliberately solves the
mechanical grounding problem first.

A later phase may let a model propose `claim_candidate` objects. That model will receive a
small bounded evidence bundle rather than arbitrary HTML or an entire knowledge vault, and
its output will still have to pass this deterministic gate before human/model semantic
review can begin.

## Out of scope

Phase 4A has no:

- LLM/provider integration;
- automatic claim extraction;
- entailment/truth scoring;
- semantic search or reranking;
- embeddings/vector database;
- knowledge graph;
- Obsidian export;
- MCP server;
- scheduler/background daemon;
- automatic knowledge or doctrine promotion.
