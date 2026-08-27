# Review Policy

This file defines the current review behaviour for Newsroom development. It is
not a standing repository review result and must not preload historical code or
architecture into an ordinary task.

## Review input

Review the exact issue intent, exact diff, Focus Gate manifest, selected tests
and affected contracts. Read broader history only when a concrete finding or
unresolved dependency requires it.

The GitHub issue is the ordinary change-intent source of truth. Do not create a
duplicate intent document, specification or plan unless a real ambiguity or an
independent decision boundary needs one.

## Finding order

Report findings before summaries, ordered by consequence:

- **P0:** unsafe, irreversible or externally harmful effect;
- **P1:** relevant correctness, authority, persistence or security failure;
- **P2:** material maintainability, evidence or efficiency defect; and
- **P3:** optional polish with no present correctness consequence.

A feature-complete review is one pass over the complete proposed change. Repeat
only after a material fix or unresolved relevant finding. Do not use repeated
reviews as ceremony.

## Merge boundary

This repository has no organisation ruleset, merge queue or required-status
platform enforcement. For ordinary non-F4 work, the agent may merge after one
observed exact-head Focus Gate success and one clean feature-complete review.
F4 effects, credentials, regulated or irreversible actions and explicit owner
decisions remain human/owner gated.

Historical review snapshots belong under `docs/research/`. The preserved
2026-02-09 OpenClaw review is
[`docs/research/2026-02-09-openclaw-architecture-review.md`](docs/research/2026-02-09-openclaw-architecture-review.md).
