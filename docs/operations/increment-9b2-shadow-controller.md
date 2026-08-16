# Increment 9B2 production-equivalent integration controller

- **Status:** controller and dry-run qualification contract implemented; 9B3 remains blocked
- **Issue:** [#492](https://github.com/fol2/newsroom/issues/492)
- **Dependencies:** #488, #489, #490, #491 and #500
- **Module:** `newsroom.increment9.controller`

## Boundary

9B2 assembles the exact integrated path using content-addressed fixtures and
replay records inside an explicitly supplied isolated SQLite journal. It makes
no source, provider, model or embedding request, obtains no credential, creates
no spend and exposes no publication, Evidence Intake, canary or production
writer adapter. A successful receipt means only
`READY_FOR_9B3_AUTHORISATION_GATE`; the separate prospective runtime gate in
#493 remains mandatory.

The plan consumes and revalidates all predecessor authorities:

- the owner-approved #488 plan and exact 9A1 Shadow Scope;
- the 9A2 Deployment Plan, isolated deployment receipt and
  `READY_FOR_9B2_CONTROLLER_QUALIFICATION` readiness receipt;
- the 9B1 Evaluation Epoch, resolved Effective Manifest and current
  decision-bearing Manifest Cohort; and
- one non-prospective `REPLAY_QUALIFICATION` Run and first Attempt.

Cross-scope, stale, unresolved, not-ready, wrong-Run, wrong-cohort, wrong
snapshot or invalid chronology inputs fail before controller construction.

## Exact integrated path

The controller permits exactly this ordered stage inventory:

1. `SOURCE`
2. `DISCOVERY`
3. `EXTRACTION`
4. `GRAPHITI_PROPOSAL`
5. `DETERMINISTIC_ADMISSION`
6. `NEO4J_PROJECTION`
7. `HYBRID_RETRIEVAL`
8. `TRIAGE`
9. `CANDIDATE`
10. `HANDOFF`
11. `EVALUATION_SINK`

Every stage interface digest must equal the appropriate identity in the
resolved Effective Manifest. Source, code, ontology, projector, retrieval,
triage, Candidate, Handoff and Operational Profile identities therefore cannot
be independently substituted after the plan is sealed. Adjacent stages are a
content-addressed chain: the next request digest must equal the preceding
response digest.

Graphiti has one proposal record and no deterministic decision record. Only
admission, triage, Candidate, Handoff and the evaluation sink carry decision
records. The resulting evidence requires zero Graphiti/proposal authority
commits and exactly five deterministic authority commits.

## Persist-before-downstream journal

Each stage supplies exact rights, purpose, credential-scope, egress, budget,
freshness, request, response, proposal/decision, checkpoint, usage and cost
digests. Before the stage response can be recorded, the controller appends:

1. the control envelope;
2. the budget reservation; and
3. the request.

Before the next stage starts it appends the response, any proposal or decision,
the checkpoint, usage and cost records. Every entry carries a contiguous
ordinal and the exact predecessor digest.

`ControllerEvidenceJournal` is a dedicated, separately supplied SQLite
authority with its own application ID and schema version. It accepts only a
pristine database, uses `BEGIN IMMEDIATE`, stores exact canonical bytes and has
triggers rejecting update and delete. Reopening reconstructs and verifies every
byte, digest, ordinal and predecessor. A non-empty journal cannot be reused as
a fresh qualification attempt. It must live in the isolated protected evidence
area; it is not installed into or aliased with the production or 9B1 Epoch
schema.

## Controls and missing evidence

Qualification requires explicit retained evidence digests for the complete
closed control inventory:

- rights, purpose, credential separation and default-deny egress;
- budget/cost, freshness, contiguous watermark, visible gap and dead letter;
- exact source representation, ontology/relation policy, index generation and
  Operational Profile;
- Graphiti proposal-only and deterministic-committer boundaries;
- unreachable publication, dispatch, Evidence Intake and production writer
  paths;
- production non-mutation, kill/containment propagation, restart/replay and
  teardown/rebuild; and
- every predeclared production-equivalence difference and inference limit.

The runner does not manufacture missing proof digests. Missing, additional or
renamed scenario, control or production-equivalence evidence fails closed.
The evidence bundle binds every supplied digest into canonical bytes.

## Restart, duplicate, ambiguity, kill and rebuild

The exact recovery inventory is:

- `RESTART_REPLAY` → `RECONCILED`;
- `DUPLICATE_REQUEST` → `DEDUPLICATED`;
- `LOST_RESPONSE` → `BLOCKED_RECONCILED`;
- `PARTIAL_RESPONSE` → `BLOCKED_RECONCILED`;
- `AMBIGUOUS_EFFECT` → `BLOCKED_RECONCILED`;
- `KILL_SWITCH_PROPAGATION` → `EARLY_STOPPED`; and
- `TEARDOWN_REBUILD` → `REBUILT`.

Lost, partial, ambiguous and early-stopped evidence retains the original
failure. Recovery evidence is never decision-bearing and cannot convert the
failed attempt into a pass. Every scenario requires zero public effect,
production mutation and orphan resources.

## Qualification receipt

`qualify_controller` passes only when all of the following remain true:

- the exact plan, stage/interface inventory and stage content chain match;
- the durable ledger has exact kinds, payloads, timestamps, ordinals and
  predecessor digests;
- every required scenario and control passes with complete evidence;
- all OD-013 differences and inference limits are retained;
- the production before/after digest is byte-identical;
- Graphiti has no commit authority and only the five deterministic stages
  commit decisions;
- source/provider requests, credentials, gross money, decision-bearing cases,
  public effects, production mutations and Evidence Intake all remain zero;
- teardown/rebuild completes with no orphan; and
- the bundle is sealed inside the plan window.

Missing or prohibited evidence yields `NOT_READY` with
`CONTROLLER_EVIDENCE_INCOMPLETE_OR_FAILED`; it never becomes an optimistic
pass. Even a ready receipt records `runtime_campaign_authority_still_required`
and `campaign_started=false`.

## Production-equivalence and actual-service proof

The plan retains every material and non-material OD-013 difference and its
inference limit. Qualification is component-scoped: it makes no traffic-scale,
high-availability, production-identity or untested credential inference.

#490's exact-main readiness receipt is a required predecessor. The final #492
gate also re-runs the dedicated Neo4j 5.26.2 workflow on the exact controller
head using workflow dispatch, so the retained actual-service proof cannot be
silently inherited from an older tree. This is still an isolated readiness
probe, not prospective campaign evidence.

## Handoff

A merged #492 closes only controller qualification. #493 may begin only after:

- the exact #488–#492 dependencies remain current on one `main`;
- the Effective Manifest identities, source rights/licences and budgets remain
  current;
- the frozen Epoch/Run authority admits a prospective baseline Run;
- the phase gate records the conditional owner execution authority; and
- no human emergency stop or deterministic veto is active.
