# Public Repository Safety

This project is developed in public. Treat every committed file, branch, pull request, issue, workflow log, fixture, and generated artifact as information that may be read, copied, indexed, or forked by anyone.

## Never commit

Do not commit:

- API keys, access tokens, cookies, session data, passwords, private keys, or credentials;
- `.env` files or machine-specific secret configuration;
- private Obsidian vaults or personal notes;
- private prompts, agent transcripts, or local conversation histories;
- customer, employer, university, or company-confidential material;
- personal data that is not intentionally public;
- internal BlueBox documents, credentials, client information, or proprietary operational data;
- local agent state, databases, caches, or execution traces that may contain sensitive context;
- downloaded third-party documents unless redistribution is clearly permitted and committing them is necessary.

Use synthetic or deliberately sanitized fixtures for tests and examples.

## Local-only working data

The repository's `.gitignore` is intended to keep common secret/configuration files, research caches, local databases, and private vault material out of Git.

`.gitignore` is a guardrail, not a security boundary. Before every commit, contributors remain responsible for reviewing what is staged.

## External research content

Fetched material from allowlisted sources is still external data. Follow [`SOURCE_POLICY.md`](SOURCE_POLICY.md).

The public repository should normally preserve metadata, canonical URLs, hashes, schemas, parsers, tests, and derived structured notes rather than redistributing complete downloaded documents.

## Logs and CI

Code and tests must not print secrets or private local paths into logs.

GitHub Actions should use the minimum permissions needed. Workflows in this repository should default to read-only repository access unless a specific write capability is required and reviewed.

Tests should be offline by default. Network access should be explicit when a future test genuinely requires it.

## If a secret is committed

Assume the secret is compromised even if the commit is quickly deleted.

1. Revoke or rotate the credential first.
2. Stop workflows or integrations that may continue using it when necessary.
3. Remove the secret from the current tree.
4. Decide whether Git history must be rewritten based on the sensitivity and exposure.
5. Review logs, artifacts, forks, and other copies that may still contain it.
6. Document the incident without reproducing the secret itself.

Deleting a Git commit is not a substitute for rotating a credential.

## If private data is committed

Stop adding new copies, remove the material from the active tree, and assess whether history rewriting or external takedown requests are necessary. Do not paste the sensitive content into an issue while discussing the incident.

## Contribution rule

Before opening or merging a pull request, verify that the change contains only information intended for permanent public disclosure.

When in doubt, keep the artifact local and commit a sanitized example instead.
