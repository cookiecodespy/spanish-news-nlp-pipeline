## Purpose

What problem does this PR solve? Link the issue when applicable.

## Changes

Summarize the smallest functional changes and any effects on v1.

## Verification

- [ ] I ran `pytest -q` locally, or explained why I could not.
- [ ] I distinguish offline/mock tests from any manually executed live checks; I have not claimed an unrun test passed.
- [ ] I included regression tests for changed behavior, or explained why none apply.
- [ ] I reviewed the actual diff and did not commit secrets, private data, local state, third-party full texts or sensitive outputs.
- [ ] Any new source is explicitly official and scoped by domain **and path**, with default-deny behavior preserved.
- [ ] Any changed network behavior maintains robots/redirect/timeout/size limits and does not treat retrieved text as instructions.
- [ ] Any changed claims/evidence retain exact provenance; verified citation integrity is not described as semantic truth.
- [ ] I documented any new dependencies, paid API use, external data transmission or licensing implications; ordinary CI stays offline.

## Risks and limitations

Describe remaining risks, operator steps, and any intentionally deferred work. Do not paste sensitive details into this public PR.
