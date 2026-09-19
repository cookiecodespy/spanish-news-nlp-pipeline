# Contributing

Thanks for helping improve the research pipeline. This is a public, provenance-first project that preserves its original Spanish-news NLP experiment as v1.

## Before opening a pull request

1. Check existing issues and propose a narrowly scoped change before adding a new source, dependency, crawler capability, LLM provider, or storage service.
2. Branch from the current `master`, make small commits, and open a pull request. Do not push directly to `master`. Delete the feature branch after the PR is merged.
3. Create a Python virtual environment, install `requirements.txt`, and run `pytest -q` locally. Ordinary CI must stay offline and deterministic; a live-source check must be an explicit, bounded, separately documented operator action.
4. Explain what changed, why, how you tested it, and whether it affects the public trust boundary, external requests, stored state, privacy, licensing, or costs.
5. Read [Public Repository Safety](docs/PUBLIC_REPOSITORY_SAFETY.md) and [Source Policy](docs/SOURCE_POLICY.md) before contributing external data or modifying network behavior.

## Source and evidence changes

A source is not approved just because a URL looks official. New registry entries need a verifiable official domain and exact section/path scope. Keep default-deny behavior, robots compliance, bounded requests and redirect validation; treat every fetched page as **untrusted data**, even on an allowlisted domain. Do not turn retrieved text into executable instructions or auto-approved doctrine.

Preserve provenance across all transformations. Raw-byte changes, normalized-content changes, supported citations and semantic truth are different concepts. Tests must not confuse them.

## Public materials and secrets

Use synthetic or redistribution-cleared fixtures only. Never include API keys, private prompts, personal/customer information, private vaults, local SQLite state, downloaded full-text articles, or sensitive data in Git history, PR comments, CI logs or artifacts. `.gitignore` does not guarantee safety. Do not post a potential vulnerability or exposed credential publicly; see [SECURITY.md](SECURITY.md).

## Review and acceptance

Keep pull requests focused, preserve the existing v1 workflow, add regression tests for behavior changes, and do not claim live-source or model-quality verification based only on mocked/offline tests. Passing CI is necessary but does not replace human review. Do not introduce vendor dependencies, paid API calls or published model benchmarks without an explicit decision on authorization, cost and terms.
