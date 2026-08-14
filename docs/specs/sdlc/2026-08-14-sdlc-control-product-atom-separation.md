# SDLC v2.6 corrective enforcement — control/product atom separation

- Status: Accepted owner corrective record
- Owner: fol2
- Date: 2026-08-14
- Related issue: #456
- Contract: `sdlc-v2.6`

## Decision

A change to the repository-wide SDLC control surface must be independently
reviewable and independently reversible from product behaviour.

The route classifier therefore fails closed when one exact change contains
both:

1. a global SDLC control path, including `.sdlc/**`,
   `.github/workflows/**`, `scripts/sdlc/**`, SDLC specifications or SDLC
   tests; and
2. non-test product implementation under `newsroom/**`, non-SDLC
   `scripts/**`, `deploy/**` or `release/**`.

The failure is deterministic and occurs before route evidence is emitted:

```text
CLASSIFIER_ERROR:global SDLC control changes and non-test product
implementation must be separate delivery atoms
```

A dedicated control/support atom may include:

- SDLC implementation and configuration;
- SDLC documentation;
- dependency or lock changes needed by that control atom;
- any repository tests required to prove topology, compatibility or
  regression behaviour.

A product atom may include its product implementation and tests, but it may
not also change the global SDLC control surface.

Renames and copies are evaluated using both old and new paths, so moving a
file across the control/product boundary cannot bypass the rule.

## Preserved boundaries

This corrective guard does not change:

- the accepted sixteen-shard deterministic topology;
- the 90-second individual-test hard boundary;
- the 75-second individual-test warning;
- the 330-second core shard and critical-path hard boundary;
- the 300-second shard and critical-path warning;
- complete deterministic-suite blocking policy;
- risk-tier or actual-service escalation;
- credentials, provider execution, locality activation, publication,
  shadow, canary or production authority.

## Rationale

Increment 7B2 correctly delivered its product boundary, but its branch also
carried global core-topology changes. That mixed ownership made independent
review, rollback and evidence attribution harder than necessary. This guard
prevents that shape from recurring without weakening any evidence gate.

## Rollback

The correction is one reversible classifier policy layer. Removing the
control/product separation check restores the prior routing behaviour without
changing the underlying classifier, evidence schema, time budgets or test
inventory.
