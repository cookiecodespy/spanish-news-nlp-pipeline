# Project status and next gates

_Last reviewed: 2026-09-19. This document describes committed capabilities and pending work, not an autonomous service currently running in production._

## Built and exercised

- **V1 preserved:** offline-reproducible Spanish-news headline classification baseline. The v1 snapshot and reported metrics remain documented in the root README.
- **V2 Phase 1:** default-deny, domain-and-path-scoped official-source registry; shallow offline/live discovery; local SQLite discovery memory; operator `doctor`, `status`, and manual `verify-live`.
- **V2 Phase 2A:** bounded HTML ingestion of previously discovered candidates, allowlist/robots recheck, exact-byte local storage, raw SHA-256, `NEW/UNCHANGED/CHANGED` observations.
- **V2 Phase 3A/3B:** pinned HTML extraction, normalized local artifacts with deterministic hashes and citation blocks, fail-closed evidence lookup with provenance. A five-source live smoke was performed for 3A; this is not continuous live monitoring or a guarantee of future site compatibility.
- **V2 Phase 4A/4B:** bounded immutable evidence bundles, strict provider-neutral claim-proposal structure, schema/citation validation and offline adversarial tests. Accepted proposals stay `UNREVIEWED`; semantic support/truth stay `UNASSESSED`.
- **V2 Phase 4C-1:** an **offline**, human-annotation-driven claim-quality evaluator, tests and CLI. It measures judgments and denominators; it does not itself determine whether a model's claim is true. See [claim-quality evaluation](CLAIM_QUALITY_EVALUATION.md) and [evaluation protocol](PHASE_4C_EVALUATION.md).

All ordinary GitHub CI tests are offline. Manual live smoke evidence does not mean a provider integration or automated daily research service exists.

## Outstanding gates

1. **Repository administration:** [Issue #28](https://github.com/cookiecodespy/spanish-news-nlp-pipeline/issues/28) documents all 13 historical branches individually verified as ancestors of `master`; their deletion, `delete_branch_on_merge` and enforceable `master` protection still require owner-side GitHub settings. Never delete `master`. A solo maintainer should require PR + the existing `pytest` status check without imposing impossible independent self-review.
2. **Public metadata:** update repository description/topics in GitHub settings to describe both the v1 origin and current research pipeline. The README and project docs are versioned in Git; repository metadata is not.
3. **Reproducible demo:** document and manually execute one limited official-source discovery → ingestion → normalization → verified evidence/bundle run, keeping external document bodies and local state out of Git and Actions artifacts.
4. **4C-2 live-model pilot:** collect small human-reviewed cases, agree on provider/model, permissions and a hard cost cap **before** external API requests. Evaluate both structural acceptance and actual citation support with private inputs/outputs, and review applicable provider benchmark-publication terms.
5. **Knowledge workflow:** only after pilot results justify it, create reviewable knowledge cards, version/contradiction handling, human doctrine approval, and read-only consumption for Obsidian/agents. Scheduled monitoring, richer ranking ([Issue #17](https://github.com/cookiecodespy/spanish-news-nlp-pipeline/issues/17)), optional Jev and more advanced infrastructure remain separate decisions.

## Working agreement

`master` is the single **long-lived** branch; a small `feature/*` or `maintenance/*` branch may exist temporarily while a PR is under review. Merge only after CI, then delete the merged head branch. An empty branch list beyond `master` between changes is an outcome of cleanup, **not** a reason to push work directly to `master`.

For contributor safety see [CONTRIBUTING.md](../CONTRIBUTING.md), [SECURITY.md](../SECURITY.md), [public repository safety](PUBLIC_REPOSITORY_SAFETY.md), and [source policy](SOURCE_POLICY.md).
