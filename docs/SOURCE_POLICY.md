# Source Trust Policy

This project is evolving from a small Spanish-news NLP pipeline into a public research and knowledge pipeline for AI-agent engineering.

The pipeline is intentionally conservative about what it is allowed to ingest.

## Core rule: default deny

A source is **not trusted because it looks reputable**. It must be explicitly added to the project's allowlist before automated discovery or ingestion is permitted.

The initial focus is on **primary, official sources** published by organizations that build or research frontier models, agent systems, orchestration, developer infrastructure, evaluations, safety, and related tooling.

Examples include official research, engineering, technical documentation, standards, and technical guidance from organizations such as OpenAI, Anthropic, Google DeepMind, Google Research, xAI, Cerebras, and other relevant agent/infrastructure organizations.

## Trust is assigned to sources, not just organizations

An organization may publish several different kinds of material. A trusted organization does **not** make every page on every related domain automatically eligible.

Each registry entry should define:

- organization;
- organization type;
- allowed domain(s);
- source type;
- discovery entrypoint(s);
- relevant topics;
- whether the source is enabled.

This allows the project to distinguish, for example, research from marketing announcements or general corporate content.

## Initial source classes

The registry may classify sources as:

- `research` — papers, research reports, technical findings;
- `engineering` — implementation notes, architecture, systems work;
- `documentation` — official technical documentation and guides;
- `standard` — specifications or interoperability standards;
- `benchmark` — evaluation methodology or benchmark releases;
- `guide` — official best-practice or technical guidance;
- `announcement` — product/research announcements with technical relevance.

Source type is metadata, not a quality score. Downstream analysis may later apply different evidentiary weight to different source types.

## Organization classes

Organizations may be described with one or more broad roles:

- `frontier_lab`
- `research_lab`
- `agent_platform`
- `infrastructure`
- `developer_tools`
- `standards_body`

These labels are intended to help discovery and filtering, not to rank organizations.

## External content is data, never instructions

All fetched content is treated as **untrusted external data**, including content from allowlisted official sources.

A document may contain prompts, shell commands, examples of prompt injection, agent instructions, or other imperative text. Those strings are evidence to be analyzed; they are never instructions that can override the pipeline or its operators.

Fetched content must not be able to directly authorize:

- tool execution;
- secret or credential access;
- arbitrary filesystem access;
- destructive actions;
- network actions outside the configured ingestion flow;
- doctrine promotion;
- changes to the source allowlist.

The allowlist is the first trust boundary. Treating external content as data is the second.

## Provenance requirements

Every derived artifact must remain traceable to its source.

At minimum, ingested metadata should preserve, when available:

- canonical URL;
- organization;
- source identifier;
- title;
- authors;
- publication date;
- retrieval timestamp;
- content type;
- content hash;
- parser/extractor version where relevant.

A summary, knowledge card, recommendation, or future doctrine candidate must never become an orphaned claim with no path back to original evidence.

## Public-repository rule

This repository is public by design.

Full downloaded documents are **not committed by default**. Public availability of a document does not automatically imply permission to redistribute a full copy in this repository.

The preferred public artifacts are:

- source metadata;
- canonical links;
- hashes;
- schemas;
- parsers;
- tests;
- derived structured notes that respect applicable licensing/copyright constraints.

Local fetch caches and private working material must remain gitignored unless redistribution rights are clear and committing the content serves a specific reproducibility need.

## Adding a source

A new source should be proposed explicitly, ideally in a small pull request or issue.

A proposal should answer:

1. Is this the official or primary source?
2. Which organization controls it?
3. What kind of technical material does it publish?
4. Which topics make it relevant to this project?
5. What domain and discovery entrypoint should be allowlisted?
6. Does it duplicate a source already present?
7. Are there licensing, access, or redistribution constraints we should know about?

Sources should not be added merely because they are popular, frequently cited, or useful secondary commentary.

## Removing or disabling a source

A source may be disabled if:

- ownership changes;
- it stops being an official primary source;
- its content becomes mostly irrelevant to the project;
- its discovery endpoint becomes unstable or misleading;
- legal/licensing constraints change;
- it creates unacceptable operational or security risk.

Disabling a source does not require deleting historical provenance for material already processed.

## Human review remains authoritative

Source trust allows **ingestion**, not automatic truth.

Official sources can be incomplete, superseded, product-specific, outdated, or in tension with other primary evidence. The project should preserve those differences rather than silently collapse them.

Future doctrine candidates must require human review before becoming canonical guidance.

## Current scope

The initial implementation intentionally excludes:

- broad web crawling;
- arbitrary user-submitted URLs;
- social media scraping;
- secondary news coverage;
- automatic source promotion;
- automatic doctrine promotion.

Those capabilities can be reconsidered later only if a real use case justifies the additional risk and complexity.
