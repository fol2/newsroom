# Increment 1C integrated foundation proof

## Purpose and fixed boundary

Increment 1C proves one synthetic, deterministic path from authenticated command authority through SQLite, governed-object hydration, native Neo4j structural context and authoritative Candidate admission. It is an evidence boundary for issue #82, not a discovery, editorial, shadow, canary or production workflow.

SQLite ledger records, retained command and policy contracts, governed-object lifecycle state, Retrieval Context records and Candidate tables are authoritative. Neo4j is a non-authoritative, rebuildable projection. Never perform graph-to-ledger, graph-to-object or graph-to-Candidate recovery.

The proof contains no live source, RSS, search, GDELT or Brave access; no Graphiti execution; no model or embedding call; no production vector generation; no publication target; no scheduler; no spending; and no public effect.

## Authoritative proof stages

1. `IntegratedFoundationProofController.record_fixture` admits the exact canonical fixture bytes through governed-object authority and executes `integrated.fixture.record` through the authenticated command boundary.
2. The resulting SQLite event binds the exact aggregate, command, object admission and manifest digest. Exact replay returns the retained command and admission identities and rechecks current hydration authority.
3. `ensure_projection` registers the retained structural family, creates or resolves one generation, rebuilds from SQLite authority, validates the exact checkpoint and promotes through the existing atomic generation authority.
4. Retrieval uses `AUTHORITY_SELECTED_ACTIVE`. `EXACT_GENERATION`, fake, no-op, disabled or missing graph paths do not qualify.
5. `build_context` hydrates the complete governed fixture through the trusted purpose-bound hydration policy and records the exact full-object access decision. Graph output supplies bounded context only; factual bytes return from governed authority.
6. `admit_candidate` authenticates and authorizes before graph inventory. It then revalidates the sole ACTIVE generation, checkpoint, validation, service compatibility, complete expected graph state, full fixture mapping and exact bounded read before Candidate authority can commit.
7. Candidate collision and idempotency are relational and deterministic. Similarity, rank, model output and graph existence cannot create Candidate identity.

## Retrieval Context contract

A valid `IntegratedRetrievalContext` binds:

- fixture, aggregate, event and object-admission identities;
- family definition, projector, ontology and mapping identities;
- the authority-selected ACTIVE generation and contiguous authority watermark;
- zero open gaps and zero dead letters;
- query-valid time, serving time and context record time;
- exact sorted nodes, relations and canonical index;
- hydration policy and access-decision identity;
- manifest, query and context digests;
- exact negative execution evidence.

The query digest is server-recomputable from the fixed contract identity, family, generation, sorted canonical IDs, query-valid time and authority watermark. The required negative evidence is:

`No vector, full-text, Graphiti, model, embedding or live-source retrieval was executed.`

Callers cannot replace or soften that statement. Retrieval version must equal the canonical fixture manifest version.

Query-valid time is business-valid time. It may precede the ledger record time for a retroactive fact. It must not exceed serving time. Serving time is the original authority-selected read observation and must not exceed the full-object hydration decision/context record time.

## Complete bounded graph evidence

Candidate admission does not trust the caller to choose the fixture graph subset or read bound.

The server reconstructs all structural batches from retained SQLite authority through the exact checkpoint, identifies the one exact fixture event batch and derives the complete sorted fixture canonical-ID set. The retained context must contain that exact node set.

The server then calculates an upper bound for every retained relation incident to those fixture IDs. The read limit comes from the trusted `ProjectionReadPolicy`, not from caller-provided node or relation counts. If the fixture neighbourhood could reach the policy bound, admission fails closed rather than accepting possibly truncated evidence.

After complete generation reconciliation, the current Neo4j bounded read must match the retained context nodes and relations exactly. Missing the last valid relation, adding an extra relation, graph loss, graph tampering or wrong-generation state all block Candidate authority.

## Hydration and current authority

A Retrieval Context may commit only with a full-object governed hydration decision:

- byte offset is zero;
- allowed bytes equal the immutable blob size;
- the hydrated blob digest equals the canonical manifest digest;
- the policy contract belongs to the admission definition;
- admission and blob lifecycle states are ACTIVE with VERIFIED integrity;
- rights remain allowed and current;
- no deletion state is present;
- the hydration decision time equals the context record time.

Candidate commit repeats those checks immediately before the SQLite transaction. A partial range, stale decision, policy/blob rebinding, revocation, deletion, tombstone or hydration-time rebinding fails before any Candidate event or row is written.

## Retained startup integrity

Every open of the Candidate authority store revalidates the retained evidence graph:

- canonical bytes and digests match every SQLite identity column;
- the fixture event type, trust, security, retention, object reference and manifest digest remain exact;
- each Exact Index entry re-derives its first source event and digest from the authoritative ledger sequence;
- each retained relation exactly matches the authoritative ledger event and provenance;
- the selected generation was ACTIVE at serving time;
- the exact checkpoint and validation existed no later than serving time;
- a qualifying promotion existed at or before the context checkpoint and no later than serving time;
- full-object hydration and decision time remain exact;
- Candidate collision, version, admission decision and authority event identities reconcile across records.

Schema v5 permits exactly one immutable Candidate Version per Candidate. A later Candidate-revision feature requires a new checked migration and command/event contract rather than offline insertion.

## Candidate admission and recovery deduplication

An `ADMITTED` decision is bound to the exact Retrieval Context that created Candidate Version 1.

After graph loss, a replacement generation produces a new, independently validated Retrieval Context. An equivalent new proposal may receive `DEDUPLICATED` while reusing Candidate Version 1, provided the replacement context has the same exact fixture, manifest, route and server-recomputed semantic collision authority. The deduplication decision records its own replacement context; it does not rewrite the immutable original Candidate Version.

Exact command replay reauthenticates, reauthorizes and revalidates current graph and object authority before returning the historical decision. Replay creates no additional event, Candidate, Candidate Version or decision.

## Graph loss and recovery

Graph loss, graph-state mismatch or a read that lacks exact fixture provenance must fail closed. It must never be interpreted as “no prior match”.

Recovery uses a new generation:

1. leave SQLite authority and governed objects unchanged;
2. create a replacement generation;
3. rebuild through the required authority ledger sequence;
4. validate the full expected graph state against the authenticated Neo4j service;
5. promote atomically, retiring the prior ACTIVE generation where applicable;
6. construct a fresh Retrieval Context;
7. rerun deterministic Candidate collision admission;
8. reopen the Candidate authority and rehydrate the replacement context as restart evidence.

A recovered equivalent proposal must deduplicate to the retained Candidate rather than create another Candidate.

## Revocation, deletion and tombstone

After fixture admission revocation and governed deletion/tombstone:

- hydration fails;
- replay of the fixture command cannot bypass current governed-object policy;
- a later graph rebuild cannot restore covered fixture relations or make the fixture admissible;
- Candidate admission using stale pre-deletion context fails closed.

The permanent actual-service test `test_actual_service_integrated_foundation_replay_recovery_and_tombstone` proves initial admission, exact replay, graph-loss failure, replacement-generation recovery, Candidate deduplication, process restart and tombstone non-resurrection against authenticated Neo4j Community.

## Credential and query boundary

The public integrated surface exposes typed commands and fixed structural operations only. It exposes no Neo4j driver, session, arbitrary Cypher, caller labels, caller relationship types, unrestricted properties or administrative cleanup command.

Candidate reconciliation derives the one exact family from the retained `ProjectionReadPolicy` and rejects a caller-supplied different family before any SQLite metadata lookup.

The permanent service gate creates runtime-generated masked credentials, rejects the bootstrap administrator identity for projection use, creates the dedicated `newsroom_projector` identity and exposes Bolt only on runner loopback.

## Permanent qualification

The permanent workflow is `.github/workflows/projection-b2-neo4j.yml`, displayed as **Projection B2/B3/C1 Neo4j**. It uses:

- the pinned Neo4j Community image and Python driver retained by B2/B3;
- runtime-generated masked credentials;
- a dedicated non-bootstrap projector identity;
- runner-loopback Bolt exposure;
- exact B1, B2, B3 and C1 actual-service tests;
- JUnit evidence proving the required C1 case executed once without skip, failure or error.

Repository CI, Authority A2a, Authority A2b, Projection B1, the actual-service gate and the SDLC evidence decision must all be green for the same exact reviewed PR head before review completion. CI is regression evidence, not approval.

## Rollback

Increment 1C has no production state or public effect. Rollback is:

1. revert the Increment 1C source, migration, workflow, documentation and test commits;
2. remove disposable test SQLite, governed-object and Neo4j state;
3. retain the pre-Increment `main` authority and B3 graph foundations;
4. do not recover authority from Neo4j;
5. rerun Authority A2a, Authority A2b, Projection B1, B2/B3 actual Neo4j, repository CI/clustering and SDLC evidence gates.

Rollback does not require source credentials, publication targets, production data migration or public correction because none exists in this increment.

## Deferred work

Production sources and rights approvals, Graphiti/model/prompt/embedding versions, full entity resolution, editorial relation admission, hybrid retrieval quality thresholds, Evidence Intake transport, Evaluation Plan, Operational Admission, shadow, canary, activation and intended-hardware capacity/licence/recovery evidence remain deferred.
