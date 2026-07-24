# Increment 1B3 Neo4j rebuild, validation and promotion operations

**Role:** Current implementation and rollback guide for Increment 1B3  
**Status:** Implementation documentation for PR #97  
**Owner:** Newsroom repository maintainers  
**Last updated:** 2026-07-24  
**Canonical language:** English  
**Runtime authority:** None. This document does not authorize source access, Graphiti execution, model or embedding calls, publication, shadow operation, canary, production activation, spending or public effects.

## Fixed authority boundary

SQLite ledger records and governed-object decisions are authoritative. Neo4j contains a disposable, non-authoritative structural projection only.

Never:

- restore, infer or repair SQLite authority from Neo4j;
- treat a Neo4j delivery marker, node, relationship, health result or graph-side flag as generation authority;
- expose the projector credential, driver, session or arbitrary Cypher to an agent, source adapter, model, Graphiti process or general application code;
- activate a generation through a direct lifecycle transition;
- serve a newer `BUILDING` or `VALIDATING` generation because it appears healthier than the SQLite-selected `ACTIVE` generation.

The supported development and CI target remains:

- Neo4j Community container `neo4j:2026.06.0-community-trixie`;
- Neo4j server `2026.06.0`;
- official Python driver `neo4j==6.2.0`;
- Python 3.12 with the repository lockfile.

This is not final production admission.

## Public operational surface

The authenticated Neo4j projection composition exposes typed operations only:

- `Neo4jStructuralProjector.rebuild(StructuralRebuildRequest)`;
- `Neo4jStructuralProjector.validate_generation(StructuralGenerationValidationRequest)`;
- `NativeProjections.promote_generation(ProjectionGenerationPromotionRequest)`;
- `Neo4jStructuralProjector.read_active(StructuralActiveReadRequest)`;
- bounded exact-generation delivery and diagnostic read operations inherited from B2.

The public surface exposes no cleanup command, driver, session, unrestricted query text, arbitrary properties, caller labels, caller relationship types or Neo4j internal IDs. Destructive cleanup is private and occurs only inside the authenticated rebuild operation for the exact target generation.

## Normal generation replacement procedure

### 1. Register the retained family and create a generation

Use the existing projection authority facade to register the exact retained family definition and create a new typed generation in `BUILDING`.

The generation is bound to the retained family definition, ontology contract, mapping contract and projector version. A material contract change requires a distinct generation. Do not reuse an older generation identity.

### 2. Choose an authority cutoff

Read the retained SQLite ledger through the required cutoff. The rebuild request contains:

- the exact target `generation_id`;
- the target generation's current `expected_authority_version`;
- `through_ledger_seq` no later than retained authority at command commit;
- a stable reason code;
- a durable idempotency key.

The requested cutoff is an authority input, not a graph checkpoint. B1 checkpoint, delivery, retry, gap and dead-letter records remain the only authoritative projection-progress model.

### 3. Invoke destructive rebuild

`rebuild()` performs this sequence under the process operation lock:

1. authenticate and authorize the exact rebuild command;
2. commit or replay the SQLite rebuild authority event;
3. confirm that the target remains `BUILDING`;
4. delete only fixed Newsroom projection records in the target generation namespace;
5. resolve every retained event and governed-object decision from SQLite in ledger order;
6. reapply already-authoritative successful deliveries after graph loss;
7. record new delivery outcomes through the B1 authority boundary;
8. leave required failures visible as gaps and dead letters.

The result reports cleanup, reapplication, new delivery, optional-ignore and blocked counts. It does not certify the generation for serving.

### 4. Inspect authoritative progress

Before validation, confirm through the projection authority facade that:

- the generation is still `BUILDING` or already `VALIDATING` only because the same validation command was replayed;
- the current contiguous checkpoint covers the intended authority cutoff;
- there are no open required gaps;
- there are no dead letters;
- retained family, ontology, mapping and projector identities are available.

A generation that contains a retained dead letter is not qualifying even after a later successful delivery. Build a clean replacement generation rather than hiding historical failure evidence.

### 5. Validate through structural reconciliation

Call `validate_generation()` with the exact current authority version and exact current contiguous checkpoint.

The caller does not supply compatibility or graph-state digests. The server:

1. authenticates and authorizes before graph inventory;
2. reconstructs the complete expected structural state from retained SQLite authority and retained mappings;
3. verifies the exact Neo4j server, edition and driver target;
4. inventories actual nodes, relationship-identity records, relationships and delivery markers in the target generation;
5. compares labels, identities, endpoints, properties, provenance and generation scope;
6. rejects missing, extra, malformed, cross-generation, tampered or graph-loss state;
7. records immutable validation evidence bound to the exact checkpoint and contracts.

Direct caller-asserted `ProjectionGenerationValidationRequest` use is rejected by the Neo4j composition.

### 6. Promote atomically in SQLite authority

Call `promote_generation()` with:

- the validating generation's exact authority version;
- the exact validated checkpoint;
- the exact retained validation digest;
- the expected prior active generation and its exact authority version, when one exists;
- a durable idempotency key.

Before SQLite activation, promotion repeats the current Neo4j compatibility check and full generation reconciliation. Graph loss or tampering after validation therefore blocks promotion.

The SQLite transaction then:

- retires the exact prior `ACTIVE` generation, where supplied and still current;
- activates the exact validated target;
- records immutable promotion evidence.

A graph-side flag cannot activate a generation. A changed prior active generation, stale target version, stale checkpoint or changed validation fails closed.

Exact promotion replay re-authenticates and re-authorizes, reconciles the current graph again and only then returns the historical promotion result.

### 7. Serve only through `read_active()`

Serving code supplies a family ID, canonical IDs, query-valid time and bounded limit to `read_active()`.

The operation:

1. authenticates and authorizes the family-scoped selection before revealing serving state;
2. requires exactly one SQLite-authoritative `ACTIVE` generation;
3. resolves that exact generation under the same process lock used by promotion;
4. applies exact-generation read authorization;
5. returns metadata marked `AUTHORITY_SELECTED_ACTIVE`.

No `ACTIVE` generation and multiple `ACTIVE` generations both fail closed. A newer `BUILDING` generation is never selected. Exact-generation reads are marked `EXACT_GENERATION`; they are diagnostic and cannot qualify production, evaluation or complete-live-shadow GraphRAG evidence.

## Incremental delivery to an active generation

The current active generation may continue receiving ordered structural deliveries. A successful delivery advances authoritative projection progress and makes the previous retained validation stale.

Before a qualifying profile may use the new watermark:

1. read the active generation's exact current authority version and contiguous checkpoint;
2. call `validate_generation()` for that `ACTIVE` generation and exact checkpoint;
3. require zero gaps and dead letters;
4. allow the server to recompute compatibility and the complete graph-state digest;
5. retain the refreshed validation while the generation remains `ACTIVE`.

Until this active revalidation succeeds, qualifying GraphRAG must fail closed. Replaying the old promotion request before revalidation is rejected because it is not validated through the current authority checkpoint. After successful revalidation, exact promotion replay still reconciles current graph state before returning the historical result.

## Recovery matrix

| Failure point | Required action | Forbidden action |
|---|---|---|
| Process loss before or during a `BUILDING` rebuild | Reopen from the same SQLite file and retry the exact rebuild request and idempotency key. The target namespace is cleaned again and authoritative successful deliveries are reapplied. | Do not infer missing SQLite delivery state from surviving graph records. |
| Complete Neo4j loss while the generation is `BUILDING` | Restart the exact service target and retry the exact rebuild request. | Do not create authority records from Neo4j backups or markers. |
| Graph loss or tampering after validation but before promotion | Promotion must fail. Mark the unusable generation failed where appropriate, create a new `BUILDING` generation, rebuild, validate and promote it. | Do not promote using the retained validation digest alone and do not transition the generation back to `BUILDING`. |
| Graph loss after a generation is `ACTIVE` | Create a new `BUILDING` generation from retained authority, rebuild, validate and promote the replacement. The former active generation is not destructively rebuilt in place. | Do not wipe and rebuild the active namespace while it remains the serving authority. |
| Required gap or dead letter | Correct the source/code defect under a new clean generation or use the existing explicit B1 recovery controls where permitted, then produce fresh validation evidence. | Do not skip the event, rewrite the checkpoint or delete retained failure evidence. |
| SQLite loss with surviving Neo4j | Restore SQLite and governed objects only from an independently verified authority recovery point. Rebuild Neo4j from that authority. | Never perform graph-to-ledger recovery. |
| Wrong or missing Neo4j credentials/configuration | Correct the private runtime configuration and repeat compatibility/reconciliation. | Do not use the bootstrap `neo4j` identity, disable authentication or place credentials in the URI. |

## Rollback

Increment 1B3 performs no production activation or irreversible graph migration.

For a source rollback before merge or deployment:

1. revert the B3 source/configuration review unit;
2. remove disposable Neo4j generation state;
3. discard disposable test SQLite/object state created by the unmerged increment;
4. restore no authority from Neo4j.

For an operational forward fix after an active-generation defect:

1. keep SQLite ledger and governed objects unchanged;
2. create a new generation under the verified retained contracts or corrected versioned contracts;
3. rebuild from authority;
4. validate against the actual Neo4j state;
5. atomically promote the replacement;
6. clean retired disposable graph state only through controlled private operations.

Do not directly reactivate a `RETIRED` generation. The lifecycle is retained and terminal; use a new generation and new validation evidence.

## Actual-service qualification

`.github/workflows/projection-b2-neo4j.yml` uses runtime-generated masked credentials, runner-loopback Bolt exposure and the pinned Community image. The permanent gate requires all B3 actual-service cases to execute without skip, failure or error, including:

- authority-selected active serving and rejection before promotion;
- active-generation incremental delivery followed by required revalidation;
- promotion rejection after graph loss following validation;
- graph/process-loss rebuild from retained authority;
- target-generation cleanup isolation;
- tombstone non-resurrection after wipe and rebuild.

The workflow also runs the B1/B2 service tests and preserves the private credential and fixed-query boundaries.

## Qualifying-profile rule

Production, evaluation and complete-live-shadow profiles require:

- enabled native Neo4j GraphRAG configuration;
- the exact qualified compatibility target;
- exactly one SQLite-authoritative active generation;
- current retained validation through the required authority watermark;
- current graph-state evidence matching that validation;
- an authority-selected active read, not an exact-generation diagnostic read;
- zero gaps and dead letters.

Development and unit profiles may use explicit non-qualifying fakes or disabled graph access. Their receipts cannot be presented as product qualification evidence.

## Retained exclusions and deferred admission

This increment includes no Graphiti runtime execution, model or embedding call, live source/search access, protected-content vector generation, final vector/full-text/hybrid retrieval, entity resolution, editorial relation admission, full Candidate or triage workflow, Evidence Intake, publication, shadow run, canary, production activation, spending or public effect.

Still deferred are final production image/manifest admission, intended-hardware performance and capacity, licence approval, owner acceptance of Community compensating controls, production TLS/network/supervision/credential rotation/monitoring, offline dump/load, encrypted backup and key custody, restore drills and RPO/RTO, and exact Graphiti/model/prompt/embedding/vector/full-text/hybrid versions.