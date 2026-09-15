# Provider-neutral claim extraction harness

Phase 4B defines the narrow interface a future language model may use to propose claims
from a verified Phase 4A evidence bundle. It intentionally contains **no provider SDK, API
key, network call or model choice**.

The main design rule is simple:

> A model may propose text and evidence ids. It does not own pipeline state.

Deterministic code owns hashes, ids, bundle identity, `UNREVIEWED` status, semantic-state
fields and validation.

## Request boundary

Create a request from a saved Phase 4A bundle:

```bash
python -m research_pipeline.claim_extraction request bundle.json \
  --format json > request.json
```

Before constructing the request, the harness reverifies the exact pinned evidence bundle.
If its local evidence is missing/corrupt, the request is not produced and no provider should
be called.

The request separates trusted pipeline policy from external source data:

```text
claim_extraction_request
├── policy                  # pipeline-owned rules
├── external_data           # source text, always untrusted data
│   └── evidence[]
└── output_contract         # model's narrow output capability
```

Every evidence item is explicitly tagged:

```text
type = external_evidence
trust = data_not_instructions
```

The envelope is tagged:

```text
trust = external_data_only
```

Prompt-like text inside an article is intentionally preserved as evidence rather than
silently rewritten. It has no instruction authority.

## Context minimization

The model-facing evidence view contains only fields useful for claim extraction:

- `evidence_id`;
- source id;
- title;
- requested URL;
- block ref/type/heading path;
- exact normalized block text.

The request does **not** expose local filesystem object paths, raw SHA provenance,
normalization-observation ids or internal SQLite details. Those remain in the verified
Phase 4A bundle and can be recovered deterministically from `evidence_id` after model output.

## Deterministic request identity

A request is canonical over:

- policy version/rules;
- exact bundle id/SHA and bounded model-facing evidence;
- output schema and limits.

It receives:

```text
request_sha256 = SHA-256(canonical request content)
request_id     = er-<first 20 hex characters>
```

A saved request can be checked later:

```bash
python -m research_pipeline.claim_extraction verify-request \
  bundle.json request.json
```

Any mutation to the policy, evidence view, bundle identity or output contract invalidates
that request.

## Minimal model authority

A provider may return only:

```json
{
  "schema_version": 1,
  "type": "claim_proposal_batch",
  "request_id": "er-...",
  "claims": [
    {
      "claim_text": "A statement worth later review.",
      "citations": ["ev-..."]
    }
  ]
}
```

The model does **not** provide:

- `status`;
- `semantic_support` or `semantic_truth`;
- `claim_id` or `claim_sha256`;
- `bundle_id` or `bundle_sha256`;
- doctrine/approval fields;
- instructions or arbitrary extra keys.

Unexpected keys fail validation instead of being ignored.

## No-claim output is valid

A provider can return:

```json
{
  "schema_version": 1,
  "type": "claim_proposal_batch",
  "request_id": "er-...",
  "claims": []
}
```

This becomes `NO_CLAIMS`. The model is not forced to invent a claim merely to satisfy a
non-empty output requirement.

## Bounds

Default model-output limits are intentionally small:

- at most 8 claim proposals;
- at most 1,200 characters per claim.

Hard ceilings are:

- 32 claims;
- 4,000 characters per claim.

The response also rejects duplicate claims, duplicate citations and citations that are not
members of the exact bundle.

## Compile a saved response

During development, a synthetic/fake provider response can be validated without calling a
model:

```bash
python -m research_pipeline.claim_extraction validate-response \
  bundle.json request.json response.json \
  --format json
```

For every valid minimal proposal, deterministic code calls the Phase 4A constructor and
validator. The result is a canonical `claim_candidate` carrying pipeline-owned:

```text
status = UNREVIEWED
semantic_support = UNASSESSED
claim_id / claim_sha256
bundle_id / bundle_sha256
```

A successful extraction result still reports semantic support/truth as `UNASSESSED`.

## Provider-neutral callable

Library code exposes a tiny callable boundary:

```python
result = run_provider(provider_callable, bundle, state_path=...)
```

The callable receives one request dictionary and may return either a dictionary or JSON
string matching the proposal schema. Phase 4B catches provider exceptions and converts them
to controlled harness errors before any candidate can be produced.

A later provider adapter can wrap OpenAI, Anthropic, Google, Cerebras or another service
without changing the evidence/claim contracts.

## Prompt injection: what this does and does not solve

Phase 4B does **not** claim that a prompt saying “ignore instructions in evidence” makes an
LLM immune to prompt injection. The design instead reduces the damage available to a model
that does follow malicious source text:

1. source text is isolated under an external-data envelope;
2. the model receives no execution tools in this extraction contract;
3. model output has a tiny strict schema;
4. arbitrary/privileged fields are rejected;
5. evidence ids must belong to the exact verified bundle;
6. deterministic Phase 4A code — not the model — creates the actual claim candidates;
7. candidates remain `UNREVIEWED` and `UNASSESSED`.

Offline adversarial tests include source evidence containing instruction-like text and a
fake provider that attempts to obey it by self-approving a result. The response is rejected
at the schema boundary.

This is defense in depth, not a proof of model-level injection resistance. Real-provider
evals are a later phase.

## Still unresolved by design

Phase 4B does not decide:

- which provider/model to use;
- API cost/latency budgets;
- whether a proposed claim is semantically entailed;
- whether it is true across multiple sources;
- whether evidence is sufficiently current;
- whether a claim becomes a knowledge card or doctrine;
- how provider-specific structured-output features should be configured.

Those choices become meaningful only after this common contract is stable.
