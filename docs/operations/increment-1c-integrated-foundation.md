# Increment 1C integrated foundation proof

## Purpose and fixed boundary

Increment 1C proves one synthetic, deterministic path from authenticated command authority through SQLite, governed-object hydration, native Neo4j structural context and authoritative Candidate admission. It is an evidence boundary for issue #82, not a discovery, editorial, shadow, canary or production workflow.

SQLite ledger records, retained command and policy contracts, governed-object lifecycle state and Candidate authority are authoritative. Neo4j is a non-authoritative, rebuildable projection. Never perform graph-to-ledger, graph-to-object or graph-to-Candidate recovery.

The proof contains no live source, RSS, search, GDELT or Brave access; no Graphiti execution; no model or embedding call; no production vector generation; no publication target; no scheduler; no spending; and no public effect.

## Authoritative proof stages

1. `IntegratedFoundationProofController.record_fixture` admits the exact canonical fixture bytes through the governed-object authority and executes `integrated.fixture.record` through the authenticated command boundary.
2. The resulting SQLite event must bind the exact aggregate, command, object admission and manifest digest. Replay must return the retained command and admission identities.
3. `ensure_projection` registers the retained structural family, creates or resolves one generation, rebuilds from SQLite authority, validates the exact checkpoint and promotes through the existing atomic generation authority.
4. Retrieval must use `AUTHORITY_SELECTED_ACTIVE`. `EXACT_GENERATION`, fake, no-op, disabled or missing graph paths do not qualify.
5. `build_context` hydrates the governed fixture through the trusted purpose-bound hydration policy and records the access decision. Graph output supplies bounded context only; exact bytes return from governed authority.
6. `admit_candidate` authenticates and authorizes first, then revalidates the sole ACTIVE generation, checkpoint, validation, compatibility, full expected graph state and exact bounded read before Candidate authority can commit.
7. Candidate collision and idempotency are relational and deterministic. Similarity, rank, model output and graph existence cannot create Candidate identity.

## Retrieval Context rules

A valid `IntegratedRetrievalContext` binds:

- fixture, aggregate, event and object-admission identities;
- family definition, projector, ontology and mapping identities;
- ACTIVE generation and contiguous authority watermark;
- zero open gaps and zero dead letters;
- query-valid time and serving time;
- exact nodes, relations and canonical index;
- hydration policy and access-decision identity;
- manifest, query and context digests;
- explicit known omissions.

Serving time is a canonical observation of the original read. A later current read may have the same or a later serving time, but never an earlier one. Persistent family, generation, checkpoint, validation, gap and dead-letter identities remain exact.

## Graph loss and recovery

Graph loss, graph-state mismatch or a read that lacks exact fixture provenance must fail closed. It must never be interpreted as “no prior match”.

Recovery uses a new generation:

1. leave SQLite authority and governed objects unchanged;
2. create a replacement generation;
3. rebuild through the required authority ledger sequence;
4. validate the full expected graph state against the authenticated Neo4j service;
5. promote atomically, retiring the prior ACTIVE generation where applicable;
6. construct a fresh Retrieval Context;
7. rerun deterministic Candidate collision admission.

A recovered equivalent proposal must deduplicate to the retained Candidate rather than create another Candidate.

## Revocation, deletion and tombstone

After fixture admission revocation and governed deletion/tombstone:

- hydration must fail;
- replay of the fixture command must not bypass current governed-object policy;
- a later graph rebuild must not restore covered fixture relations or make the fixture admissible;
- Candidate admission using stale pre-deletion context must fail closed.

The permanent actual-service test `test_actual_service_integrated_foundation_replay_recovery_and_tombstone` proves initial admission, exact replay, graph-loss failure, replacement-generation recovery, Candidate deduplication and tombstone non-resurrection against authenticated Neo4j Community.

## Permanent qualification

The permanent workflow is `.github/workflows/projection-b2-neo4j.yml`, displayed as **Projection B2/B3/C1 Neo4j**. It uses:

- the pinned Neo4j Community image and Python driver retained by B2/B3;
- runtime-generated masked credentials;
- a dedicated non-bootstrap projector identity;
- runner-loopback Bolt exposure;
- exact B1, B2, B3 and C1 actual-service tests;
- JUnit evidence that proves the required C1 case executed once without skip, failure or error.

Repository CI, Authority A2a, Authority A2b, Projection B1, the actual-service gate and the SDLC evidence decision must all be green for the same exact PR head before review completion.

## Rollback

Increment 1C has no production state or public effect. Rollback is:

1. revert the Increment 1C source, migration and test commits;
2. remove disposable test SQLite, governed-object and Neo4j state;
3. retain the pre-Increment `main` authority and B3 graph foundations;
4. do not recover authority from Neo4j;
5. rerun the existing A2a, A2b, B1, B2/B3 and repository CI gates.

## Deferred work

Production sources and rights approvals, Graphiti/model/prompt/embedding versions, full entity resolution, editorial relation admission, hybrid retrieval quality thresholds, Evidence Intake transport, Evaluation Plan, Operational Admission, shadow, canary, activation and intended-hardware capacity/licence/recovery evidence remain deferred.
