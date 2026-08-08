# Increment 5D1 traceability — exact-first hybrid composer

## Delivery boundary

5D1/#330 consumes the completed Increment 5C tool receipts and delivers the
composition portion of parent Increment 5D/#253. It owns exact-first branch
orchestration, fixed reciprocal-rank fusion and authoritative dependency-root
deduplication.

5D1 contributes to `GRAG-035` and `TRI-022`, but does not complete either row by
itself. Factual hydration, the immutable complete Retrieval Context, current
rights/freshness revalidation and final truthful context outcomes remain
5D2/#331.

## Requirement-to-evidence map

| Requirement | Delivery evidence | Verification evidence |
|---|---|---|
| `GRAG-035` independently attributable hybrid response | exact six-entry manifest and retained named request, dispatch, execution and upstream receipt identities | accepted-request/receipt round trip, input-order replay and tamper tests |
| `GRAG-035` one-request coherence | one actor/principal/policy/contract/profile/time context plus fixed compatible named-tool purposes and a receipt-recomputed plan-context digest | cross-principal, request-byte, purpose, request-digest and plan-context substitution regressions |
| `GRAG-035` retained authority-evidence integrity | supplied collision/authority and source-impact raw receipts are semantically revalidated before blocker precedence | positive compatibility plus recomputed rights and temporal-lineage tamper regressions |
| `GRAG-035` exact/source-native precedence | exact-supported roots sort first, explicit admitted-lineage roots second, and similarity-only roots third | exact-first and admitted-lineage ordering against adversarial higher-RRF approximate roots |
| `GRAG-035` deterministic fusion | equal-weight RRF with fixed `k=60` and reduced rational scores | exact fraction, tie order, branch-order and scalar-type tests |
| `GRAG-035` no pooled raw score comparison | only branch rank contributes; raw proof/score remains behind branch-hit digest | vector large-integer proof, source inspection and score invariance tests |
| `GRAG-035` authoritative deduplication | merge only identical upstream `dependency_root_id`; retain every origin and path, with full-text authority-view provenance separate from per-hit identity | shared-root, similarity-only separate-root, provenance and duplicate-mode regressions |
| `GRAG-035` bounded ordering and exclusions | 12 retained roots plus explicit ordered `RESULT_BOUND` exclusions | thirteen-root truncation and would-be-rank tests |
| `TRI-022` truthful request-level status contribution | fixed purpose-to-tool requirements, explicit manifest states and known omissions | missing, stale, blocked, unavailable, invalid-receipt and no-match matrix |
| no false `NO_MATCH` | no-match only after all mandatory branch work and purpose-required checks complete | zero-result complete case and every non-complete blocker case |
| no authority or external effect | zero call/spend counters, `authority_effect=NONE`, no qualification/activation authority | claim rejection and forbidden-surface inspection |
| deterministic restart | first-writer-wins local receipt journal with request-level deterministic re-derivation | restart byte replay, semantic conflict, retained-byte tamper and recomputed-digest semantic substitution tests |

## Core implementation evidence

- `newsroom/increment5/hybrid_composer.py` — strict request/input/manifest,
  exact-first RRF, dependency-root deduplication, explicit exclusions and
  immutable replay journal;
- `newsroom/increment5/named_tool_authority_receipt_validation.py` — pure,
  reusable semantic validation of retained collision/authority and
  source-impact receipt bytes without opening an authority store;
- `newsroom/tests/test_increment5d1_hybrid_composer.py` — accepted 5C receipt
  compatibility, ordering, deduplication, no-match, invalid evidence, bounds,
  replay, tamper and source-boundary tests;
- `docs/operations/increment-5d1-hybrid-composer.md` — operation, monitoring and
  rollback boundary.

## Evidence identities

Every composition binds:

- composition request, actor, authenticated principal, purpose, policy, accepted named-tool contract/profile, query-valid time and serving time;
- one plan-context digest over the exact supplied named-tool request and envelope identities;
- accepted composer contract digest;
- six-tool manifest in fixed order;
- exact named-tool purpose, request/envelope, dispatch, execution and raw upstream receipt digests;
- branch profile, generation and authority watermark where supplied;
- every dependency root and retained origin path;
- selected per-mode rank contribution and exact rational score;
- ordered retained roots and explicit exclusions; and
- normalized outcome, reason, no-match, truncation and known omissions.

## Non-delivery boundary

5D1 does not deliver:

- governed object or passage bytes;
- final rights/lifecycle/freshness revalidation;
- complete immutable Retrieval Context identity/version;
- Candidate or Hypothesis creation, admission, merge or suppression;
- durable cross-request reconciliation or queue effects;
- provider/model calls, embeddings, live sources or spending;
- publication, canary or production activation; or
- complete operational credential, egress, incident, recovery or Operational
  Admission controls.

Those remain 5D2/#331, Increment 6/#146 and Increment 8/#148.

## Completion evidence

The 5D1 child may close only after one exact final head has:

- focused composer and accepted 5C compatibility tests passing;
- complete deterministic repository CI passing;
- only affected permanent Authority/Projection/service lanes passing under the
  Tier-S policy;
- exact changed-file and source-integrity evidence;
- one substantive exact-head review with zero unresolved P1/material-P2
  findings;
- zero unresolved review threads; and
- product-only squash merge with exact commit/tree evidence.

Parent #253 remains open after 5D1. It receives one Tier-M integrated gate only
after 5D2 also merges.
