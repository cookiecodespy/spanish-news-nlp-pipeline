# Phase 4C-1 — offline claim-quality evaluation

**Status:** a human-label evaluation harness; not an automatic truth checker, live model benchmark, or Jev integration. Inputs are a saved Phase 4A bundle, Phase 4B request and provider-format proposal batch, plus a local annotation JSON file. The evaluator must invoke Phase 4B's existing response compiler before scoring; structural citation integrity is different from semantic support.

A reviewer inspects the *exact* evidence and the compiled response, then writes a strict, versioned annotation. This schematic example uses placeholders (not actual evidence IDs):

```json
{
  "schema_version": 1,
  "type": "human_claim_review",
  "bundle_id": "<exact bundle_id>",
  "bundle_sha256": "<exact bundle_sha256>",
  "request_id": "<exact request_id>",
  "request_sha256": "<exact request_sha256>",
  "reviewer": "reviewer-1",
  "expected_findings": [
    {"finding_id": "finding-1", "required_evidence_ids": ["<evidence_id>"], "rationale": "Why the finding matters and what supports it."}
  ],
  "judgments": [
    {"claim_id": "<exact compiled claim_id>", "verdict": "supported", "finding_ids": ["finding-1"], "rationale": "What the cited text does or does not establish."}
  ]
}
```

`expected_findings: []` means abstention (`NO_CLAIMS`) is expected. The `judgments` array must cover **every** compiled claim exactly once, with no additional claim IDs. Verdicts: `supported`, `partially_supported`, `unsupported`, `unassessable`. A finding counts as covered only when a reviewer explicitly marks a claim `supported`, links that finding, and the claim cites *every* required evidence ID. Only `supported` judgments may link findings. **This does not prove support:** the human reviewer must check actual meaning, context, negation and qualification; text matching never grants a verdict.

Run locally with the four JSON files:

```bash
python -m research_pipeline.claim_evaluation bundle.json request.json response.json review.json --format json
```

Use `--state PATH` for another local pipeline SQLite state. The default output is concise human-readable text. Malformed responses, stale or fabricated IDs, invalid annotations and missing judgments fail closed (nonzero exit, no partial scores). No network, model call, SDK or upload is involved.

Per-case metrics: `supported_claim_precision = supported / assessable` and `unsupported_claim_rate = unsupported / assessable`, where `assessable = supported + partially_supported + unsupported`; unassessable claims are counted separately. `finding_coverage = covered / expected` is **undefined (`null`)** when no findings are expected. Abstention is `APPROPRIATE` only for zero claims and zero expected findings, `INAPPROPRIATE` for zero claims despite expected findings, and `NOT_APPLICABLE` otherwise. These are per-case descriptive counts, **not provider scores or launch criteria**.

Real third-party text, full model inputs/outputs, private notes, human labels containing excerpts and API credentials must remain local and gitignored. Only synthetic or redistribution-cleared cases may be committed. See [evaluation protocol](PHASE_4C_EVALUATION.md) and [Phase 4B contract](CLAIM_EXTRACTION.md).
