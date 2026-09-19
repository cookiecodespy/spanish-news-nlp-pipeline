# Jev — potential future decision adapter (not implemented)

**Status (2026-09-19):** The project owner submitted an early-access request to TypeSafe AI; approval, API credentials and pricing for this account are **not confirmed**. This repository does not integrate Jev, call its API, install its SDK or depend on it. No private waitlist application or account details belong in public Git.

## What it could do

TypeSafe describes Jev as a model for structured, typed decisions from supplied state, rather than free-form text generation. See the [official TypeSafe announcement](https://typesafe.ai/blog/introducing-system-one-models-and-jev) and [company site](https://typesafe.ai/). Do not mistake vendor performance claims or probabilities for guarantees of correctness.

A **proposed narrow first experiment**, only after access and explicit user authorization:

```text
verified normalized document (bounded title + extract)
    -> optional relevance decision: AGENT_ENGINEERING | OTHER | UNSURE
    -> human-reviewed priority queue / candidate triage
    -> existing Phase 4A evidence bundles and Phase 4B generative claim harness
```

The exact questions, input/output schema, version, confidence thresholds and cost will be confirmed against TypeSafe's official API documentation **after** approval, rather than guessing them now. Measure agreement against human-labeled examples, precision for the relevant class, appropriate abstentions and coverage. A deterministic baseline (for example, source/topic metadata) must be compared first; add a model only if it materially improves the workflow.

## Non-negotiable boundaries

- Jev **does not** authorize domains, widen the `default: deny` registry, decide whether robots.txt permits a fetch, or substitute for deterministic byte/hash/provenance checks.
- Jev **does not** write `APPROVED`, `VERIFIED`, canonical doctrine or an automatic semantic-truth verdict. Model decisions remain advisory; errors and low confidence go to review or a conservative fallback, not silent exclusion of important research.
- Jev is **not** the generative model required for Phase 4C claim extraction. The current `claim_extraction` provider callable expects claim text plus valid evidence IDs; a decision-only provider would need its own separate adapter and evaluation contract.
- Only explicitly scoped, sanitized/approved document text may leave the local environment. No API key or full downloaded article body is committed to Git, Actions, issues or public reports.
- No shared credentials embedded in repository code; use independently configured credentials and permissions for different apps. Any reuse between this research pipeline and AgentOS should be via an optional client package/interface with separate state and authorization, not an implicit data bridge.
- Failure of the external service must not break offline discovery, ingestion, normalization, citation verification or human review.

## Decision gate

Do not implement a TypeSafe-specific adapter until (1) early access is approved and official SDK/API docs verified, (2) the owner approves the intended data flow and spending cap, (3) a small labeled dataset and deterministic baseline exist, and (4) provider terms concerning public benchmarks are reviewed. A follow-up issue/PR can then build and measure **one** optional decision task; integration with AgentOS is separate future work.

See [`PHASE_4C_EVALUATION.md`](PHASE_4C_EVALUATION.md) for evaluation and budget principles. This is an architectural idea, not an announced feature or a commitment to use a particular vendor.