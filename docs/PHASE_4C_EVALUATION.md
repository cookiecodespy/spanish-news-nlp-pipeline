# Phase 4C — controlled model-evaluation protocol

**Status: proposed protocol; no live generative-model integration or evaluation results yet.** Phase 4B already builds a provider-neutral request and validates proposal structure, citations and provenance offline. A structurally accepted claim still has `semantic_support=UNASSESSED` and `semantic_truth=UNASSESSED`.

## Question to answer

Can a particular generative model extract useful, *actually supported* claims from the exact bounded evidence supplied, at an acceptable cost and error rate? Passing the existing JSON/citation validator is necessary but not proof of entailment, truth, usefulness or prompt-injection immunity.

## Pilot scope and authorization

- Start with one explicitly selected provider/model and a **small** set of bounded evidence bundles; no automatic crawling or bulk inference as part of the pilot.
- Ask the repository owner to approve the model/provider and a hard spending cap **before** making API requests; no assumed TypeSafe/Jev access and no API key in Git, CI, logs, issue comments or artifacts.
- Record an explicit maximum requests, input/output tokens, concurrency (1 initially), timeout and retry policy; stop rather than silently exceed any budget.
- Use local state for source documents, model inputs/outputs that reproduce full source text, billing metadata and annotations. Publish only synthetic or redistribution-cleared fixtures and sanitized aggregate reports after reviewing the provider's terms (including any benchmarking/publication restrictions).
- Keep ordinary CI deterministic and offline; live calls are an explicit local/manual pilot, never a required PR check.

## Dataset and annotations

Build a small **human-reviewed** dataset of cases sampled from different document types and source organizations, plus synthetic adversarial cases. Use training/development cases to design prompts and a separate held-out set for reporting. Store for each case: immutable bundle ID/SHA, task version, expected answerable claims or `NO_CLAIMS`, exact evidence IDs needed for support, and annotator rationale. Where reviewers disagree, report disagreement instead of manufacturing certainty. Do not put real third-party article text in committed fixtures without redistribution permission.

Include cases with: a directly supported claim; a tempting but unsupported inference; two similar/conflicting blocks; irrelevant/empty evidence; outdated vs newer observations; an instruction-like string in source text; fabricated evidence IDs; and explicit abstention. These are **planned cases**, not claims that today's test suite already measures model quality.

## What to record and measure

1. **Contract acceptance:** percentage of responses accepted by Phase 4B; invalid JSON/schema, wrong request ID, unknown citations, privilege-field attempts and empty (`NO_CLAIMS`) responses counted separately.
2. **Semantic support:** human-labeled supported, partially supported, unsupported or unassessable for each proposed claim *relative to the cited blocks*. Report supported-claim precision and unsupported-claim frequency with numerators and denominators, not merely a score.
3. **Coverage and abstention:** how many annotated important findings were captured; missed findings and appropriate/inappropriate `NO_CLAIMS` decisions. Avoid treating a model that never produces claims as successful.
4. **Prompt-injection behavior:** whether source text altered task compliance, requested unauthorized output, or caused unsupported claims; separate deterministic rejection from model resistance.
5. **Operations:** provider/model version, prompt/contract version, bundle IDs, input/output token use when available, latency, request failures, retries and reported billing. Missing cost/usage data is `UNKNOWN`, not zero.

Run an offline deterministic baseline or hand-authored reference through the same evaluator where useful. Never publish named model rankings or benchmarks without reviewing the relevant terms.

## Acceptance and failure policy

No numeric launch threshold is invented here. Before the pilot, the owner must agree on acceptable unsupported-claim rate, citation-support precision, coverage, review workload and spending limits. A passing structural validator **never** auto-approves semantic support or doctrine. Stop and investigate if a provider leaks secrets, crosses the cost cap, executes external instructions, fabricates citations, or otherwise violates the fixed contract. Failures become reviewed issue(s), not silently retried until a favorable sample appears.

## Sequence

1. Finish GitHub hygiene (`master` protections and merged-branch cleanup) before broader automation.
2. Publish a reproducible synthetic/cleared benchmark schema and an offline evaluator in a focused PR; test labels and denominators, invalid outputs, abstentions and missing billing data.
3. Obtain explicit approval of provider and budget; run a bounded pilot locally with saved private inputs/outputs.
4. Review results and errors manually, decide whether a provider adapter is warranted, and only then design knowledge-card generation.

See [`CLAIM_EXTRACTION.md`](CLAIM_EXTRACTION.md) for the existing Phase 4B boundary and [`JEV_INTEGRATION.md`](JEV_INTEGRATION.md) for a separate possible decision model.