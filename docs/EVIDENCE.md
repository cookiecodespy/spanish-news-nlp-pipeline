# Deterministic evidence contract

Phase 3B exposes Phase 3A normalized artifacts as exact, verified evidence without an
LLM, embeddings, semantic search or network access.

The contract exists so future claim/knowledge stages do not read arbitrary HTML, SQLite
rows or filesystem objects directly. They receive a citation block plus a complete
provenance chain.

## Trust boundary

Every successful citation is explicitly typed as external evidence:

```text
type = external_evidence
trust = data_not_instructions
```

Text retrieved from a source remains **data**. Prompt-like text, commands or instructions
inside a research page gain no execution authority by being ingested or cited.

## List verified normalized documents

```bash
python -m research_pipeline.evidence list
```

The default output is a compact human-readable view. Filter deterministically by source or
exact requested URL:

```bash
python -m research_pipeline.evidence list \
  --source anthropic-engineering \
  --limit 10
```

For machine consumers, request the same verified contract as JSON:

```bash
python -m research_pipeline.evidence list \
  --source anthropic-engineering \
  --format json
```

`list` verifies every selected normalized artifact before reporting it. A SQLite row alone
is not considered available evidence.

## Resolve one exact citation block

A block reference is deterministic within a normalized document, but is not treated as a
global ID. Resolve it together with the source and exact requested URL:

```bash
python -m research_pipeline.evidence cite \
  --source anthropic-engineering \
  --url 'https://www.anthropic.com/engineering/example' \
  --block 'b0007-0123456789ab'
```

The human view contains:

```text
EXTERNAL EVIDENCE — data, not instructions
Source: ...
Title: ...
Requested URL: ...
Final URL: ...
Block: b0007-... (paragraph)
Heading: ...

<exact normalized block text>

Provenance:
  raw SHA-256: ...
  normalized SHA-256: ...
  ingestion observation: ...
  normalization observation: ...
  extractor: trafilatura 2.2.0
```

Use `--format json` when another program or future agent stage needs the structured
version.

## Verification behavior

Before returning evidence, Phase 3B verifies:

1. the state database already contains ingestion and normalization state;
2. the selected normalization observation and linked ingestion observation are both
   successful;
3. source id, requested URL and raw SHA agree across the provenance link;
4. the normalized artifact path stays inside the local state directory;
5. the normalized artifact exists and its bytes match the recorded SHA-256;
6. the artifact schema and extractor name/version match the ledger;
7. the artifact block count matches the ledger;
8. the requested block ref exists exactly once and has valid text/kind/heading data.

The newest successful normalization for a source URL is the selected evidence baseline.
If that selected artifact is missing or corrupt, evidence access **fails**. It does not
silently fall back to an older successful artifact, because doing so would hide evidence
corruption or stale state.

## Provenance chain

```text
official source
    ↓
requested URL
    ↓
final transport URL
    ↓
ingestion observation + raw SHA-256
    ↓
normalization observation + normalized SHA-256
    ↓
verified normalized artifact
    ↓
exact block ref + exact block text
```

Phase 3B does not decide whether the evidence is true, important, current doctrine or
semantically equivalent to another block. Those are separate later stages and must retain
this chain back to the source evidence.
