# Offline walkthrough and integration handoff

This repository includes a **synthetic, provider-free** demonstration of the implemented local v2 contracts. It is a reproducible engineering smoke test, **not** evidence that an autonomous researcher, live crawler, truth evaluator, or Jev integration is operational.

## Run it

From the repository root with Python 3.11 and dependencies installed:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m examples.offline_walkthrough
pytest -q
```

The walkthrough prints one compact JSON object with the synthetic source marker, raw and normalized SHA-256, exact block ref, evidence bundle/request ids, `citation_integrity=VALID`, `candidate_status=UNREVIEWED` and the **illustrative** author-labeled review metric. It creates a temporary local SQLite database and content-addressed raw/normalized objects, deleting that scratch directory at exit. Normalization runs the real pinned `trafilatura==2.2.0` extractor, not a hand-built normalized fixture.

**Deliberate boundaries:** `synthetic-demo` / `example.com` are invented records, not an actual allowlisted or fetched publication. Discovery and ingestion are **locally seeded observations**, not a network/robots compliance demonstration. Claim text and review labels are **written by this example's author**; the reported precision of 1/1 is a fixture assertion, *not a result for a generative model or independent human review*. No API, Jev, credentials, real source bodies, network requests or third-party content are used. This example does not add the synthetic source to the production registry or expose its data to agents.

## Manual real-source smoke (separate; not CI)

A real-source end-to-end smoke requires the operator's explicit decision to access a website. Follow the source registry and robots requirements. Start from the existing commands in the [README](../README.md): `assurance doctor`, `assurance verify-live --source ...`, `live_discovery --source ...`, `ingestion --source ... --limit 1`, `normalization --source ... --limit 1`, `evidence list --format json`, and finally `grounding bundle` with a real URL and real block ref returned by evidence. Never copy example URLs or synthetic ids into a real observation. A passing synthetic run does **not** substitute for that manual smoke. Preserve legal/redistribution boundaries: keep HTML, normalized content, SQLite, bundle and provider I/O out of Git, Actions artifacts, public issue/PR comments and public demo screenshots unless explicitly cleared for redistribution.

## What 'done' means for the current offline core

- Source-policy and local provenance/citation/claim contracts and the offline evaluator exist, have tests, and can be demonstrated with synthetic content.
- GitHub governance has a protected `master`, required `pytest` PR check and auto-deletion of merged heads. Normal work is via temporary PR branches, not direct pushes.
- The offline walkthrough and the test suite complete successfully on a fresh environment with the declared dependencies.

These criteria define a **bounded offline engineering milestone**, not final product completion. Before declaring a live research system or reusable knowledge product complete, independently validate a manual real-source run, run an owner-authorized limited generative-model pilot with real human annotations and a hard spending cap, define and test knowledge-card approval/export contracts, then design read-only, least-privilege AgentOS/Obsidian integration. Optional Jev waits for approved access, a documented decision task, and evaluation; it is not a prerequisite for the offline milestone.

The standalone [project status](PROJECT_STATUS.md) is the source of truth for outstanding gates. [Phase 4C protocol](PHASE_4C_EVALUATION.md) separates model quality from structural citation integrity. [Jev proposal](JEV_INTEGRATION.md) describes its optional future role.
