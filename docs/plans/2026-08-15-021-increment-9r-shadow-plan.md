# Increment 9R immutable shadow plan and owner-decision packet

**Issue:** #488 / 9R
**Parent:** #149 / Increment 9
**Programme:** #141
**Status:** Owner decision required; runtime blocked
**Planning base:** `main@834250f8b0e7b5ce34e0cb54236d463429bd766e`
**Planning tree:** `06b99d383f514db2fda95afe83f99c0e5b489ef5`
**Authority schema:** v32 / `sha256:3439b82ec6d212116e54765d50cace4d7f147b6ecc3e6ff84146b523c6fd5676`
**Machine record:** `newsroom/increment9/shadow_plan_v1.json`
**Draft digest:** `sha256:a881b3c0da08dfa8d817f54377827879f13365d94e001c867c53bca68b32dbd8`

## Decision

The exact Increment 8 authority is eligible for a separate Increment 9 plan,
not for shadow execution. The machine record retains the verified repository
baseline, all fourteen unresolved owner-decision groups, the complete #488–#498
dependency and file-ownership graph, non-effect rules, stop precedence, gates,
outcome vocabulary and Increment 10 blockade.

No source, rights, provider, model, embedding, budget, reviewer, credential,
egress, licence or production-equivalence value has been inferred. Each remains
`OWNER_DECISION_REQUIRED` with a null selection and no invented evidence.
`require_owner_approved_plan()` therefore fails closed and identifies every
unresolved decision.

This draft is immutable and content-addressed, but it is not the approved final
plan. Owner answers require a reviewed successor version and new digest in the
same canonical planning PR. #488 closes only after that successor records the
explicit approval and all planning gates pass.

## Bound repository baseline

The record binds the accepted Increment 8 exact-main commit and tree, schema
v32 fingerprint and migration-history digest, exact-main run `31871581163`,
`FIXTURE_OPERATIONAL_ADMITTED` and `ELIGIBLE_FOR_SEPARATE_PLAN` disposition.

It also binds the exact base-commit Git blobs for:

- the Python project and `uv.lock` dependency resolution;
- the SQLite migration registry;
- the admitted-only Neo4j controller, ontology and projector;
- the proposal-only Graphiti contract and workspace policy;
- bounded retrieval, named-tool and hybrid-composition contracts;
- Candidate, Handoff and bounded Search authority; and
- the Increment 8 readiness and Operational Admission records.

These are observed baseline identities, not selected live-runtime versions.
The current real Graphiti runtime remains disabled. The currently qualified
Neo4j image and Operational Profile remain fixture evidence only.

## Required owner decisions

| ID | Decision | Must bind before approval |
|---|---|---|
| `OD-001` | Live source portfolio, roles, locality and rights | Exact endpoints, roles, beats/locality, rights versions, access permission, query/source-data handling, retention/deletion and model destination |
| `OD-002` | SQLite authority snapshot and export | Schema/history, cutoff/watermark, export digest, shadow-copy identity, production read boundary, restore and purge |
| `OD-003` | Neo4j shadow deployment | Image digest, driver, database/namespace, ontology/projector, generation policy, hardware/capacity and recovery |
| `OD-004` | Graphiti runtime | Framework lock, proposal workspace, adapter code, structured destination, temporal/normalisation contracts, retention/cleanup and destination rights |
| `OD-005` | Model and prompt | Provider/model release, prompt digest, output schema, tools/destination, retention, timeouts/retries/rates and Evaluation compatibility |
| `OD-006` | Embedding and indexes | Provider/model/dimensions, chunking, normalisation, full-text/vector configuration, protected-content permission, generation/rebuild and query retention |
| `OD-007` | Integrated application versions | Retrieval/named tools, triage/relation, Candidate/Handoff, Operational Profile, controller image/config, queue/schedule/retry/capacity and end-to-end compatibility |
| `OD-008` | Evaluation Epoch and prospective universe | Epoch/freeze time, window/cutoffs, eligible denominator, slices/strata, exposure, thresholds/uncertainty and material-change rules |
| `OD-009` | Reviewer authority | Named reviewers/adjudicators, independence/conflicts, blinding, assignment/replacement, disagreement/adjudication and workload/cost |
| `OD-010` | Comparator and fault phases | Baseline/comparator, Search Purpose, assignment, exposure/request templates, phase inventory, expected observations, containment/recovery and stop order |
| `OD-011` | Gross budgets | Source/provider requests, model and embedding units/tokens, storage, reviewer minutes, gross GBP minor units, duration and amplification |
| `OD-012` | Licences, credentials, egress and protected artefacts | Terms versions, credential classes and secret locations, destination allow-list, network policy, protected classes, encryption-key class, retention/purge/access review |
| `OD-013` | Production-equivalence differences | Intended-production manifest plus material/non-material traffic, schedule, identity, credential, capacity and topology differences and inference limits |
| `OD-014` | Incident, kill switch, rollback and restoration | Authority/mechanism, zero-tolerance stop, containment, incident notification, rollback target, restore/reconciliation, teardown and unchanged-rerun prohibition |

Secret values must never enter the plan. An approved selection names credential
and key classes plus governed secret locations only.

## Frozen rules independent of owner selection

- Prospective evidence only; complete denominators are mandatory.
- No hindsight selection, post-result threshold change or Case substitution.
- Any material source, right, model, prompt, index, profile, budget or
  configuration change closes the Epoch.
- Failed, partial, blocked, early-stopped and inconclusive outcomes are retained.
- An unchanged failed Run is not retried as a route to a passing result.
- Missing evidence is inconclusive or blocked, never optimistic PASS.
- Public effect, production-authority mutation, rights breach, credential
  exposure, prohibited egress, authority cross-contamination and uncontained
  ambiguous effect each have threshold zero.

## Non-effect and stop boundary

Only repository inspection, canonical plan construction/replay and substantive
plan review are currently allowed. The plan grants no deployment, live source,
provider/model, embedding, credential, egress, spend, decision-bearing shadow,
fault execution, live-evidence review, Evidence Intake, publication, canary,
production mutation, activation or legacy retirement authority.

Stop precedence is public effect/production mutation, rights/credential breach,
containment failure, budget exhaustion, material manifest drift, impossible
required exposure, then ordinary phase failure. A stop prevents later phases.
Evidence is retained, ambiguous effects reconciled, production non-mutation
proved, and isolated resources restored, rebuilt or removed only from retained
authority.

## Dependency and ownership graph

```text
Wave 0
#488 9R

Wave 1 after #488
#489 9A1     #491 9B1     #494 9C1     #496 9D1

Wave 2
#489 -> #490
#489 + #490 + #491 -> #492

Wave 3
#488 + #489 + #490 + #491 + #492 -> #493

Wave 4
#490 + #491 + #492 + #493 + #494 -> #495

Wave 5
#493 + #495 + #496 -> #497

Wave 6
#488-#497 -> #498
```

The canonical JSON assigns non-overlapping expected source, test, script and
documentation paths to every issue. Each branch has one writer. A dependency
must merge to main before its dependent atom starts, including the ordered
`#490 -> #492` sequence grouped under Wave 2.

The retained graph follows the parent #149 parallel-wave contract: #491 depends
on #488, not on #489. The older `Contract dependency: #489` line in #491 must be
corrected when this plan is owner-approved; until then #491 remains blocked and
no implementation ambiguity can create runtime authority.

## Gate placement

- **9R:** explicit owner approval, every owner decision bound, strict canonical
  replay, source integrity, zero P1/material-P2 findings and zero unresolved
  threads.
- **Contract atoms:** focused replay/tamper tests, dependency closure,
  applicable deterministic CI and substantive review; no live execution.
- **Isolation/controller atoms:** affected security, egress, recovery and actual
  isolated-service proof; no decision-bearing prospective evidence.
- **Runtime atoms:** exact approved plan, explicit execution authority, current
  rights/licences, available gross budgets, frozen Epoch, enforced early stop,
  complete inventories and production non-mutation proof.
- **Review/decision:** sealed prospective evidence only with pre-registered
  assignments, slices, thresholds and ablations.
- **9G:** one exact main, all applicable deterministic and actual-service
  evidence, independent reconstruction, clean substantive review and Sigstore
  bundle.

## Outcome and Increment 10 boundary

The closed outcome vocabulary is `FAILED`, `INCONCLUSIVE`, `CONTINUE_SHADOW`,
`COMPARATOR_ONLY`, `BLOCKED_ACTIVE_COVERAGE` and
`SCOPED_OPERATIONAL_ELIGIBILITY`.

No outcome automatically starts Increment 10. Eligibility additionally needs
the signed Increment 9 closeout, an outcome supporting the exact proposed
canary scope, remediation of every zero-tolerance finding, current Operational
Admission, Accepted or explicitly owner-authorised Evidence Intake and a
separate owner-approved Increment 10 plan.

## Approval procedure

1. The owner supplies exact selections and evidence references for
   `OD-001`–`OD-014`.
2. Update the machine record in this same PR; retain no secret value.
3. Change each bound decision to `APPROVED`, record the owner identity/time and
   approval record, and content-address the approved bytes.
4. Keep live/comparator/fault execution flags false: #488 approval authorises
   only the later contract/isolation implementation graph.
5. Run focused canonical, duplicate-field, unknown-field, tamper, graph,
   non-effect and source-integrity evidence.
6. Obtain substantive review with zero P1/material-P2 findings and resolve every
   thread.
7. Merge the single canonical PR and close #488. Only then activate #489, #491,
   #494 and #496 from the new exact main.
