# Project status and next gates

_Last reviewed: 2026-09-20. This is an engineering pipeline with an offline demonstrator, **not** a deployed autonomous research service._

## Built and exercised

- **V1 preserved:** offline-reproducible Spanish-news headline classifier, original snapshot and baseline metrics documented in the root README.
- **V2 Phase 1:** official-source default-deny registry, shallow offline/live discovery, local SQLite discovery memory, operator `doctor`, `status`, and manual `verify-live`.
- **V2 Phase 2A:** bounded HTML ingestion of discovered candidates, allowlist/robots recheck, exact-byte local raw storage, SHA-256 and `NEW/UNCHANGED/CHANGED` observations.
- **V2 Phase 3A/3B:** pinned HTML extractor, locally stored deterministic normalized artifacts and citation blocks, fail-closed evidence lookup with provenance. A five-source live smoke was previously performed for 3A; this is not continuous monitoring or a guarantee of future site compatibility.
- **V2 Phase 4A/4B:** bounded immutable evidence bundles and a provider-neutral, strictly validated claim-proposal contract. Accepted proposals remain `UNREVIEWED`, with semantic support/truth `UNASSESSED`.
- **V2 Phase 4C-1:** offline human-annotation-driven evaluation, tests and CLI. An evaluator reports supplied human judgments; it cannot automatically determine truth.
- **Synthetic offline walkthrough:** `python -m examples.offline_walkthrough` seeds invented discovery/ingestion observations, exercises the actual pinned normalization, evidence, bundle, proposal and review contracts, and prints an explicitly illustrative result. See [walkthrough](OFFLINE_WALKTHROUGH.md). This is **not** a live-source, real-human-study or LLM performance result.
- **GitHub administration completed:** [Issue #28](https://github.com/cookiecodespy/spanish-news-nlp-pipeline/issues/28) closed after verification: one permanent protected `master`, required PR and GitHub Actions `pytest` check, no force pushes/deletion, automatic head-branch cleanup, accurate repository description and updated topics. Temporary branches are normal during PR development.

Ordinary GitHub CI remains deterministic and offline. No external model provider/Jev API integration, recurring crawler, vector DB or agent-access service is claimed here.

## Remaining product gates — separate from GitHub hygiene

1. **Manual real-source end-to-end verification:** have an operator explicitly run a bounded source discovery → actual ingestion → real normalization → verified citation → bundle. Keep the third-party article body, local state and any model I/O out of public Git history and CI artifacts. Synthetic walkthrough is insufficient for this gate.
2. **4C-2 owner-authorized generative-model pilot:** collect independently reviewed cases; agree on the provider/model, permissions, token/request limits and hard spending cap **before** external requests. Evaluate structural validity and semantic citation support with private inputs/outputs; review model benchmarking/publication terms. See [Phase 4C protocol](PHASE_4C_EVALUATION.md).
3. **Knowledge product:** only after useful pilot results, define versioned knowledge cards, contradiction handling, human approval, and read-only export/consumption for Obsidian or other agents. These components are not yet implemented.
4. **Optional parallel work:** document-likeness candidate ranking ([Issue #17](https://github.com/cookiecodespy/spanish-news-nlp-pipeline/issues/17)), scheduled monitoring, extra sources and [Jev triage](JEV_INTEGRATION.md) are individual decisions, not prerequisites for an offline milestone. Jev early-access approval and API availability have not been confirmed here.

## Practical handoff

The present project can be **paused or reused as a tested offline provenance/evidence foundation** once its walkthrough PR and final `master` CI pass. Calling the entire research/knowledge system finished would be inaccurate until the real-source and model/knowledge gates above are met. A future integrator should consume explicit verified evidence or human-approved artifacts via a versioned read-only interface, not copy the local SQLite database or grant arbitrary file/network access to agents.

Working agreement: `master` is the sole long-lived branch; use small temporary branches, PRs and the required `pytest` check, then delete merged heads automatically. Review [CONTRIBUTING.md](../CONTRIBUTING.md), [SECURITY.md](../SECURITY.md), [public-repository safety](PUBLIC_REPOSITORY_SAFETY.md) and [source policy](SOURCE_POLICY.md) before publishing data or integrating tools.
