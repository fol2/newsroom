# Increment 9C1 comparator and fault-phase authority

Status: **contract complete; execution not authorised**
Issue: [#494](https://github.com/fol2/newsroom/issues/494)
Owner plan: `newsroom/increment9/shadow_plan_v1.json`
Owner-plan digest: `sha256:92510c8b3989bb25cfce187b3477a71d8909a691ad8f3b88ae4917e456e9216d`

## 1. Boundary

`newsroom.increment9.comparator` is the immutable, strict-canonical contract
surface for the prospective comparator and isolated fault campaign. It performs
no I/O and does not authorise:

- a live source, provider, model or embedding call;
- credential access, egress or spend;
- a fault injection or deployment change;
- publication or Evidence Intake;
- canary or production mutation/activation.

An `ADMITTED` receipt means only that a proposed phase matches the sealed 9C1
contract. Increment 9C2 must still supply its own runtime authority and every
upstream receipt. An `ADMITTED` receipt therefore has
`runtime_authority_still_required=true` and all effect-authority flags false.

## 2. Comparator identity and assignment

A `ComparatorPlan` binds one exact Evaluation Epoch to:

- `FROZEN_READ_ONLY_NEWS_POOL_EXPORT`, never live Brave, GDELT or legacy
  Gemini;
- media radar comparators `RAD-01_RTHK` and `RAD-02_BBC`;
- retrieval ablations `EXACT`, `FULL_TEXT`, `VECTOR`, `ADMITTED_GRAPH` and
  `HYBRID_RRF`;
- purpose `BOUNDED_RECALL_AND_GAP_MEASUREMENT_ONLY`;
- assignment `DETERMINISTIC_DIGEST_SAMPLE`;
- provider-neutral template `increment9-agent-profiles-v1`;
- exact digests for source portfolio, eligible universe, rights rules,
  query-data handling and the bounded request template.

The plan must be sealed before any result. Every comparator uses the same case
universe. Hindsight switching, cherry-picking, backfill and denominator repair
are all false and cannot be changed by parsing or reconstruction.

## 3. Exposure and denominator contract

The `ExposureContract` records exact UTC opening and closing instants. The
semantic universe is exactly 120 cases. Comparator exposure is capped at one
third. The retained minima from OD-008 are:

| Exposure | Minimum |
| --- | ---: |
| Cases per claimed beat | 20 |
| Changed revisions per claimed source | 10 |
| Correction or supersession | 10 |
| `EN_GB` | 30 |
| Fault warning transitions | 12 |
| Hong Kong | 30 |
| `MIXED` | 20 |
| Official cases | 60 |
| Related-distinct or false-merge | 20 |
| UK | 30 |
| `ZH_HANT_HK` | 30 |

All natural warning transitions are included. Denominators retain:

1. every due poll;
2. every eligible case, with deterministic digest sampling only if the budget
   would otherwise be exceeded;
3. every new or changed revision, including blocked and failed revisions.

Missing evidence is `INCONCLUSIVE_OR_BLOCKED_NEVER_PASS`. A material change
closes the Epoch; it is not repaired in place and no retrospective cases are
substituted.

## 4. Gross budgets

`BudgetCaps` is an exact code-level representation of OD-011:

| Resource | Gross cap |
| --- | ---: |
| Scheduled source checks | 8,400 |
| Gross HTTP attempts | 10,500 |
| Attempts per source | 3 |
| Metered API requests | 2,000 |
| Metered model input tokens | 20,000,000 |
| Metered model output tokens | 4,000,000 |
| Embedding passages | 50,000 |
| Embedding tokens | 10,000,000 |
| Storage | 500 GiB-days |
| Metered AI reviewer time | 2,400 minutes |
| Human reviewer time | 0 minutes |
| Gross monetary cost | GBP 250.00 (25,000 minor units) |
| Epoch duration | 28 days |
| Model attempts per metered call | 2 |
| SUT model operations per case | 3 |

Budget transfer is false. Admission compares each reservation with both the
global caps and the pre-registered per-phase attempt/amplification caps. Any
overrun fails closed with `API_BUDGET`, closes the Epoch and grants no
decision-bearing authority.

## 5. Ordered fault inventory

The inventory is exact, complete and ordered. Each `FaultPhase` binds its plan,
ordinal, injection-scope digest, expected observable result, containment action,
recovery action, maximum attempts and amplification. Every phase is isolated;
public effect and production mutation are false.

| # | Fault | Expected observation | Mandatory containment | Recovery |
| -: | --- | --- | --- | --- |
| 1 | `SOURCE_FAILURE` | `SOURCE_UNAVAILABLE_RETAINED` | `STOP_SOURCE_IO` | `RETRY_OR_CLOSE` |
| 2 | `DUPLICATE` | `DUPLICATE_SUPPRESSED` | `QUARANTINE_DUPLICATE` | `REPLAY_CANONICAL_INPUT` |
| 3 | `OUT_OF_ORDER` | `STALE_OR_GAP_VISIBLE` | `FREEZE_WATERMARK` | `RECONCILE_LEDGER` |
| 4 | `CORRECTION` | `SUPERSESSION_RETAINED` | `ISOLATE_REVISION` | `REBUILD_DERIVATIVES` |
| 5 | `PROMPT_INJECTION` | `INJECTION_BLOCKED` | `QUARANTINE_INPUT` | `REPLAY_SANITISED_FIXTURE` |
| 6 | `SCHEMA_ERROR` | `SCHEMA_REJECTED` | `QUARANTINE_RECORD` | `REPLAY_VALID_RECORD` |
| 7 | `MODEL_FAILURE` | `MODEL_FAILURE_RETAINED` | `STOP_MODEL_IO` | `RETRY_OR_CLOSE` |
| 8 | `EMBEDDING_FAILURE` | `EMBEDDING_FAILURE_RETAINED` | `STOP_EMBEDDING_IO` | `REBUILD_INDEX` |
| 9 | `NEO4J_FAILURE` | `GRAPH_UNAVAILABLE_VISIBLE` | `ISOLATE_GRAPH` | `RESTORE_OR_REBUILD_GRAPH` |
| 10 | `SQLITE_FAILURE` | `AUTHORITY_FAILURE_VISIBLE` | `KILL_ALL_PHASES` | `RESTORE_VERIFIED_BACKUP` |
| 11 | `QUEUE_FAILURE` | `QUEUE_GAP_VISIBLE` | `STOP_DISPATCH` | `RECONCILE_QUEUE` |
| 12 | `BUDGET_EXHAUSTION` | `BUDGET_STOP_VISIBLE` | `STOP_METERED_EFFECTS` | `NEW_BUDGET_AUTHORITY_REQUIRED` |
| 13 | `RIGHTS_PURGE` | `PURGE_TOMBSTONE_RETAINED` | `STOP_AFFECTED_SOURCE` | `VERIFY_PURGE` |
| 14 | `CREDENTIAL_ATTEMPT` | `CREDENTIAL_DENIAL_VISIBLE` | `REVOKE_AND_KILL` | `ROTATE_AND_RECONCILE` |
| 15 | `EGRESS_ATTEMPT` | `EGRESS_DENIAL_VISIBLE` | `BLOCK_EGRESS_AND_KILL` | `VERIFY_NETWORK_CONTAINMENT` |
| 16 | `PUBLICATION_ATTEMPT` | `PUBLICATION_DENIAL_VISIBLE` | `KILL_PUBLIC_ADAPTER` | `PROVE_NO_PUBLIC_EFFECT` |
| 17 | `PRODUCTION_WRITE_ATTEMPT` | `PRODUCTION_WRITE_DENIAL_VISIBLE` | `KILL_PRODUCTION_PATH` | `PROVE_PRODUCTION_NONMUTATION` |
| 18 | `KILL_AND_RESTORE` | `RECOVERY_PROOF_RETAINED` | `GLOBAL_KILL` | `RESTORE_AND_RECONCILE` |

`SOURCE_FAILURE` includes the approved source/network failure surface;
`OUT_OF_ORDER` makes stale and gap behaviour observable;
`BUDGET_EXHAUSTION` exercises bounded capacity; and `KILL_AND_RESTORE` is the
sole recovery-proof phase. These are coverage mappings, not additional
unapproved fault kinds.

## 6. Phase ordering and early stop

The overall order is fixed:

1. `DRY_REPLAY`;
2. `28_DAY_BASELINE`;
3. `SEALED_COMPARATORS`;
4. `ISOLATED_FAULT_CAMPAIGN`;
5. `SEALED_AI_REVIEW_AND_DECISION`.

Stop precedence is deterministic and independent of observation order:

1. `PUBLIC_OR_PRODUCTION_EFFECT`;
2. `RIGHTS_OR_CREDENTIAL`;
3. `LEDGER_OR_CONTAINMENT`;
4. `API_BUDGET`;
5. `MANIFEST_IDENTITY`;
6. `EXPOSURE_IMPOSSIBLE`;
7. `ORDINARY_FAILURE`.

The zero-tolerance observations are public/production effect outside authority,
rights or credential breach, prohibited egress, authority cross-contamination,
uncontained ambiguous effect, ledger gap and API budget overrun. One such
observation immediately produces `EARLY_STOP`, closes the Epoch and prevents
all later decision-bearing work. The original failed Epoch remains failed.

After any stop, only the pre-registered `KILL_AND_RESTORE` phase with
`RunKind.RECOVERY_PROOF` may receive `RECOVERY_ONLY`. Its evidence is explicitly
non-decision-bearing. A new independently qualifying final Effective Manifest
or a new Epoch remains necessary for resumed decision-bearing evidence.

## 7. Admission algorithm

`ApprovedPhaseAdmissionController.admit` checks, in order:

1. campaign, Comparator Plan, Epoch, cohort and Effective Manifest digests;
2. exact Epoch comparator, universe, source, rights and budget bindings;
3. exact cohort-to-Epoch and cohort-to-manifest bindings;
4. a known pre-registered phase and an allowed `FAULT` or `RECOVERY_PROOF` Run;
5. resolved identities, no material drift and a decision-bearing cohort;
6. current rights;
7. isolation and production non-mutation proof;
8. no requested public or production effect;
9. global and phase budget/amplification limits;
10. deterministic stop precedence.

The result vocabulary is `ADMITTED`, `RECOVERY_ONLY`, `EARLY_STOP` or
`REJECTED`. Missing, unknown, non-canonical, reordered, duplicated, drifted or
over-budget inputs never become an admission.

## 8. Canonical and tamper properties

`ComparatorPlan`, `FaultCampaignManifest` and `PhaseAdmissionRequest`:

- use restricted canonical JSON and SHA-256 identities;
- reject duplicate keys, unknown fields, unknown enums and trailing bytes;
- reconstruct nested records through their validators;
- reject missing, duplicate or reordered fault phases;
- are frozen dataclasses and expose no mutating runtime operation.

Tests replay canonical bytes, tamper every binding class, reverse ordered
inventories and precedence observations, expand budgets, request prohibited
effects, introduce material drift and attempt post-stop decision-bearing work.

## 9. Traceability

| Contract | Owner decision / predecessor |
| --- | --- |
| Source portfolio and query handling digests | OD-001 |
| Epoch, universe, denominators and exposure | OD-008; #491 |
| Comparator identity, assignment, phase order and fault inventory | OD-010 |
| Gross budgets and amplification | OD-011 |
| Rights, credentials, egress and protected artefacts | OD-012; #489 |
| Zero tolerance, kill, rollback and recovery | OD-014 |
| Immutable owner plan and non-effect boundary | #488 |
| Stable 18-shard gate topology | #500, #504, #508 |

This contract is an input to #495. It does not activate #495 and does not alter
the dependency requirement that #490, #491, #492, #493 and #494 all complete
before comparator or fault execution.
