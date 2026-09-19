# Security policy

This repository is a public research prototype, not a hardened general-purpose crawler or a production security boundary. Its source allowlist, robots handling, bounded networking, local hashes and evidence contracts are defense-in-depth measures; they do not establish that arbitrary URLs, content or model outputs are safe.

## Supported versions

Security fixes are considered for the current default branch (`master`). Historical feature branches and snapshots are not maintained releases.

## Reporting a vulnerability

**Please do not publish exploit details, API keys, private information or full third-party documents in a public issue, pull request or discussion.** Use GitHub's **Report a vulnerability** / private vulnerability reporting feature in the repository's Security tab **if it is available**. If that option is not available, request a private reporting channel from the repository maintainer without sharing technical exploit details publicly. Never send secrets in an issue or comment.

A helpful private report includes the affected commit or file, a minimal reproduction with synthetic data, the expected and actual behavior, and any relevant impact. Please do not test against third-party services or accounts without authorization.

## If you encounter exposed credentials

Treat them as compromised: revoke or rotate them first, stop affected workflows if needed, then remove exposed material and assess Git history, CI logs and forks. Deleting a branch or commit alone does **not** revoke leaked credentials. See [Public Repository Safety](docs/PUBLIC_REPOSITORY_SAFETY.md).

## Trust and scope

Official domains are not an instruction authority. Every external page, retrieved paragraph and model response remains lower-trust data. A valid hash or citation only proves integrity/attribution within the pipeline, not semantic correctness or immunity to prompt injection. Paid providers, public benchmarks and private user data are outside the default offline test workflow.
