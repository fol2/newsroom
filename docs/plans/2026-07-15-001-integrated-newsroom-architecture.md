# Integrated publication, serving and temporal knowledge architecture

**Status:** Proposed
**Owner:** Product owner
**Last updated:** 2026-07-15
**Canonical language:** English
**Target specs and requirements:** [`news-discovery.md`](../specs/editorial-automation/news-discovery.md) (`DISC-001`–`DISC-053`); [`publication-engineering-and-projection-control.md`](../specs/editorial-automation/publication-engineering-and-projection-control.md) (`ARCH-001`–`ARCH-012`, `RETR-001`–`RETR-003`, `SERV-001`–`SERV-019`, `PUBENG-001`–`PUBENG-007`, `OPS-001`–`OPS-006`, `DBOPS-001`–`DBOPS-005`); [`autonomy-and-publication-control.md`](../specs/editorial-automation/autonomy-and-publication-control.md) (`AUTO-020`–`AUTO-025`, `AUTO-040`–`AUTO-041`, `AUTO-050`–`AUTO-057`, `AUTO-060`–`AUTO-064`); [`content-generation-and-presentation.md`](../specs/editorial-automation/content-generation-and-presentation.md) (`CONT-070`–`CONT-075`); [`publication-lifecycle-and-audit.md`](../specs/editorial-automation/publication-lifecycle-and-audit.md) (`LIFE-001`–`LIFE-005`, `LIFE-010`, `LIFE-023`–`LIFE-024`, `LIFE-030`–`LIFE-035`, `LIFE-040`, `LIFE-050`–`LIFE-066`, `AUDIT-001`–`AUDIT-013`)
**Related decisions:** [`../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md) (`Proposed`), [`../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md) (`Proposed`), [`../adr/0003-pseudonymous-store-entitlement-without-newsroom-accounts.md`](../adr/0003-pseudonymous-store-entitlement-without-newsroom-accounts.md) (`Accepted`), [`../adr/0004-source-registry-first-change-driven-discovery.md`](../adr/0004-source-registry-first-change-driven-discovery.md) (`Accepted`)
**Related research:** [`../research/2026-07-15-database-architecture.md`](../research/2026-07-15-database-architecture.md), [`../research/2026-07-15-local-agentic-graph-rag-database-options.md`](../research/2026-07-15-local-agentic-graph-rag-database-options.md), [`../research/2026-07-15-low-cost-news-discovery-options.md`](../research/2026-07-15-low-cost-news-discovery-options.md)
**Explicitly out of scope:** A temporary graph-less production architecture; a planned publication-v1-to-graph-v2 migration; permanent graph-engine lock-in; generic document chat; a Web reader client; Discord or OpenClaw as target dependencies
**Target branch or release:** One new target-architecture programme based on current `origin/main`; PR [#75](https://github.com/fol2/newsroom/pull/75) is not a merge prerequisite and no implementation is authorised until this plan, ADR 0001 and ADR 0002 are all Accepted

## Delivery model — one target architecture

The SQLite ledger and governed object store, publication controller, online-serving projection, Neo4j/Graphiti temporal knowledge projection and Hermes retrieval tools will share one canonical identity, temporal, trust and ordered ledger-event contract from canonical production schema v1.

Work is dependency-ordered because consumers cannot safely precede their contract. It is not divided into a publication-only Stage 1 and a graph-enabled Stage 2. No workstream may introduce an interim canonical model that a later workstream must migrate. Runtime graph independence is a failure-containment property, not a later delivery phase.

```text
                          authenticated commands
                Hermes / workers / Admin / ingestion
                                      |
                                      v
              command service + SQLite ledger + object store
             one identity system + one ordered event contract
                         |                         |
                  target_operation             ledger_event
                         |                         |
                         v              +----------+----------+
            publication controller      |          |          |
            + credentialed adapters   serving   knowledge  operations
                         |             projector  projector   projector
                         v                |          |          |
             public targets + acks        v          v          v
                  + observations       online     Neo4j +    Admin, audit
                         |             serving     indexes    and Semantic UI
                         +---- reconciliation ----+

Each projector owns its contiguous checkpoint and failure/dead-letter state.
```

The graph, full-text/vector indexes, online serving store and operational views are separate rebuildable consumers. Their independent failure and replacement do not create a second authority model.

## Discovery and evidence hand-off

The target discovery plane is source-registry first, direct-watch first, change-driven and search-last without being search-zero:

```text
Source Registry + Planned Agenda
              |
              v
deterministic source adapters and change detection
              |
              v
       Discovery Signal
              |
       deterministic gates
              v
           News Lead
              |
 event retrieval + batched triage
              v
        Story Candidate
              |
              v
 governed evidence acquisition -> Source Observation -> Evidence Package
```

Hermes may schedule deterministic collectors and wake bounded triage work only when signals survive the pre-check. A Discovery Signal, News Lead or Story Candidate is not an authoritative Source Observation or evidence. Discovery storage and RAG are deliberately deferred until the sourcing flow has been validated.

Launch starts in shadow with the smallest owner-approved UK and Hong Kong source subset that covers the agreed beats. Sources are added only when shadow comparison exposes a meaningful gap. This architecture makes no initial locality-completeness or detection-time commitment.

## Current state and corrected interpretation

### Current `main`

Current `main` is the legacy OpenClaw/Discord-oriented runner. It can create a public external effect before final mutable job state is persisted, and posted-event recording is best-effort. It has no long-lived editorial ledger, governed object authority, transactional target-operation record, online app-serving projection, governed graph projector or target reconciliation.

The existing `news_pool.sqlite3` is a bounded discovery pool, not the target editorial ledger. Current `main` is therefore not Stage 1 of this architecture.

### PR 75 is a donor, not Stage 1

PR [#75](https://github.com/fol2/newsroom/pull/75) is an unmerged, credential-free shadow implementation. It contains potentially reusable work:

- canonical JSON and SHA-256 package identity;
- deterministic editorial outcomes and policy checks;
- SQLite transaction, durability and schema-admission patterns;
- append-only audit, authority revision, pause, lease and fencing concepts;
- recording-intent idempotency; and
- zero-public-capability tests.

It does not contain the canonical publication state model, decision-free multi-surface bundle, claim-to-surface manifest, transactional command set, live acknowledgements, correction reconciliation, online-serving projection, governed graph projection, Graphiti admission boundary or Hermes tools. Its schemas also bind shadow-specific concepts that should not become a production compatibility obligation.

PR 75 MUST NOT be merged unchanged merely to establish an intermediate base. Reusable algorithms and tests may be ported or rewritten against the canonical contract after their applicable residual review findings are resolved. This is a source-code donor mapping, not a runtime `v1`-to-`v2` data migration. Keep PR 75 open until a draft replacement architecture PR exists; then add a supersession comment linking the replacement, preserve the branch and review history, and close PR 75 without merging. Only findings that apply to explicitly retained donor primitives migrate into the replacement work. Findings tied solely to rejected shadow code may close with a recorded supersession rationale rather than becoming permanent scope.

## Canonical contract fixed before consumers

Canonical production schema v1 must define stable, typed identifiers for at least:

- source document, source snapshot, source passage and source observation;
- entity mention, entity-resolution proposal and decision, canonical entity, event or formal process;
- claim assertion, claim proposal and admission decision, plus its deterministic Governed Claim view;
- relation assertion, relation proposal and admission decision, plus its deterministic Governed Relation view;
- story, story version, evidence package, surface payload, publication bundle and publication decision;
- access-policy key, revision, assignment and resolved access decision;
- target publication, target operation, fenced attempt, acknowledgement, observation, reconciliation finding and remediation decision; and
- governed object, ledger event, projection consumer, checkpoint, failure or dead letter and Authoritative Projection Baseline.

A content digest identifies immutable bytes; it does not replace a domain identity.

Every authoritative change emits a consumer-neutral versioned event envelope containing at least `ledger_seq`, `event_id`, `event_type`, `schema_version`, `aggregate_type`, `aggregate_id`, `aggregate_version`, `recorded_at`, `correlation_id`, `causation_id`, producer version, `payload_digest` or immutable `payload_ref`, and security and retention scope. The shared envelope carries only non-sensitive routing metadata; payload access is authorised and logged per consumer. Publication, serving, graph and operations projectors use the same envelope and canonical identifiers, while the controller separately consumes committed `TargetOperation` records. Each projector owns its idempotent processing state, contiguous checkpoint and failure or dead-letter record; the ledger does not fan out authoritative queue rows for every consumer.

A later authorised consumer replays retained canonical events or starts from an immutable, ledger-attested Authoritative Projection Baseline declaring its cutoff sequence, scope, schema and projector contract, included aggregate and tombstone classes, object manifest and digest. It must apply later events and tombstones and may not fabricate historical events, sequence numbers or recording times.

Graphiti may extract entity mentions, claim assertions and relation assertions, but it may not allocate authoritative identity or write the governed graph directly. The exact extraction result first becomes an immutable proposal in the ledger. An entity-resolution decision binds each depended-on mention before claim or relation admission. Separate admission decisions then control the deterministic Governed Claim and Governed Relation views exposed by the projector. Re-extraction creates new proposals; it never mutates historical output.

## Dependency-ordered workstreams

WS-A establishes and then implements the shared contract. Once that contract is approved, WS-B, WS-C and WS-D can proceed concurrently against it while WS-A continues its authority-plane work. These are dependency-ordered workstreams, not release stages or separate target architectures.

### WS-A — Canonical contract and authority plane

- Resolve the cross-spec contract and then decide ADR 0001 and ADR 0002 together as parts of this target architecture while preserving their different reversibility.
- Define the canonical production-v1 identity catalogue, event envelope, temporal fields, trust states, entity/claim/relation proposal-and-admission model and orthogonal publication states.
- Implement the dedicated command-service identity, authenticated and fenced command interface, local SQLite ledger and atomically installed governed content-addressed objects on a supported local filesystem.
- Define one authoritative transaction boundary for domain mutation, audit record, consumer-neutral ledger events and only the target operations required for committed public effects.
- Implement consumer-owned checkpoints and failure records, integrity checks, a coordinated encrypted database-and-object recovery point, separately protected deletion journal and deletion-aware restore proof.
- Replace PR 75 compatibility migration language with a donor map showing which algorithms and tests are reused, reshaped or rejected.

**Exit evidence:** A fresh database is created directly at canonical production schema v1. Permission, command, model, crash and transaction tests prove stable identities, valid transitions, stale-command fencing, atomic ledger events and target-operation creation without per-consumer authority fan-out or a shadow-v1 migration. A verified restore meets the approved recovery envelope without resurrecting deleted data.

### WS-B — Publication and online serving action plane

- Render and content-address every target-specific `SurfacePayload` before approval, including app/API article representation, feed card and notification payload where applicable.
- Stage exact payload bytes without creating an authoritative bundle, then commit the decision-free `PublicationBundle` record, separate authorising decision, audit and one command per required target operation in one authoritative transaction.
- Implement fenced attempts, controller-internal least-privilege target adapters, target-native acknowledgement, capability-aware ambiguous-outcome recovery, desired-versus-observed reconciliation, and correction, withdrawal and removal propagation.
- Record immutable public-effect observations and keep `first_public_effect_at`, `primary_feed_published_at` and per-attempt `target_acknowledged_at` distinct. The accepted feed policy defines the event that assigns the feed timestamp.
- Include stable story/version identity, visibility and correction state, asset digests and a stable `AccessPolicyKey` in the serving contract. Resolve immutable revisions through authenticated, audited, bitemporal assignments so free and paid rules can evolve without changing editorial identity or payload bytes.
- Implement the accepted pseudonymous store-entitlement boundary: verify Apple and Google purchase proof server-side, retain only the minimal ecosystem-scoped entitlement record, issue short-lived signed Access Grants and create no Newsroom customer account. Purchase and restore remain within the originating ecosystem. Enforce an Entitlement Verification Barrier so that a native Store success or local receipt cannot unlock paid content before server verification and Access Grant issuance.
- Treat the introductory offer as a store-managed Subscription Trial. Resolve only explicitly human-designated, reader-labelled Free Samples through access-policy assignments so examples remain readable before a trial starts and after it expires; automation may propose candidates but cannot activate or revoke free access, and article age is not a free-access rule.
- Automatically render and validate an exact Preview Excerpt within the versioned one-quarter limit for every paid article and include it in the authorised Publication Bundle. Measure that limit from the canonical article body's readable narrative text in Unicode grapheme clusters; exclude headline, byline, metadata, sources, related links, images and captions from the denominator. Derive the longest continuous leading prefix without skipping or reordering content and, whenever one fits, end on the last complete sentence or list item within the limit. When no complete unit fits, keep the hard one-quarter cap, use the last Unicode word boundary within the budget when one exists and otherwise cut at the grapheme boundary; classify the result as a within-unit truncation without blocking publication. Treat every inline non-text block as indivisible. Include only exact governed media or derivatives carrying rights-validated Preview Media Permission; otherwise stop before the block without skipping to later text. A media-led article may publish with an empty text preview when no media is permitted. Place an Inline Paywall Gate directly after the authorised boundary; when the preview is hidden or empty, place it after the article header and any permitted hero media. Never open a purchase surface merely because the article was opened: only an explicit reader action may start the native Store flow. Let the server select only the Store product identifier and Newsroom access class; obtain localised price, billing period and eligibility-specific trial or offer terms from current Store Commerce Metadata as ephemeral native-client display state, not as a replayed Newsroom projection or access authority. Present exactly one Primary Commerce Action before purchase: Start Trial only when the current Store context confirms trial eligibility, otherwise Subscribe; keep Restore Purchase secondary. When Store Commerce Metadata cannot be obtained, replace that commerce action with Retry, retain Restore Purchase, disable Subscribe and display no stale commerce claim. After Start Trial or Subscribe is invoked, expose `PURCHASE_IN_PROGRESS`, disable repeated purchase initiation and then move a native Store success to `VERIFYING_ENTITLEMENT`; keep the article restricted until server verification yields an effective Store Entitlement and signed Access Grant. Treat a reader cancellation as transient `PURCHASE_CANCELLED`, perform no entitlement verification or error presentation, then return to the current restricted pre-purchase gate with its Primary Commerce Action and Restore Purchase re-enabled. When verification exceeds the configured reader wait limit, expose non-terminal `VERIFICATION_DELAYED`, keep `ENTITLEMENT_PENDING` and the article restricted, replace purchase actions with primary Retry Verification and secondary Restore Purchase, and retry only the same Store transaction idempotently. Trigger single-flight Verification Recovery on reader retry, network restoration, app foregrounding, a native Store transaction update or an authenticated provider server notification; concurrent triggers coalesce and none may initiate a purchase surface. Enter terminal `VERIFICATION_FAILED` only on an authenticated, definitive provider verdict that the submitted transaction is invalid or cannot grant the selected product and access class; transport or availability failures remain delayed and recoverable. Map that failure to one stable Verification Failure Reason—Transaction Invalid, Product Mismatch, Store Context Mismatch, Entitlement Inactive at verification time or Purchase Not Verified—while keeping raw provider detail only in protected operational evidence; process later expiry, refund or revocation of an already verified Store Entitlement as entitlement lifecycle, not Verification Failure. In that terminal state, make Restore Purchase primary and Get Help secondary, hide retry and new-purchase actions, and restore the ordinary gate only after provider-backed restore confirms no active or pending entitlement. Open Get Help as a Newsroom-hosted privacy-minimised form that submits a Support Case to a role-restricted Web Admin queue; attach only the opaque diagnostic reference automatically and accept an optional reply address and description only after explicit reader consent. Serve previews by default, with one authenticated, audited owner Global Preview Control that can disable or re-enable them without rewriting editorial identity; indeterminate control state hides previews.
- Deliver one Capacitor reader codebase for iPhone, iPad, Android phone and Android tablet, published separately per platform. Keep Web Admin separate and do not require an initial reader Web client.
- Project versioned machine-readable Semantic UI state for reader and Admin surfaces from the same canonical identifiers, including content, access, loading, correction, approval, partial and error transitions; do not infer it from screenshots.

**Exit evidence:** The same approved bundle converges to the intended online-serving state after crash, timeout, lost response and retry, or remains truthfully ambiguous when a target cannot be observed. Direct claim impact and target reconciliation remain correct with the graph unavailable. All four supported client classes consume the same access and Semantic UI state contract without treating pending or failed access resolution as free. Purchase, restore, refund and revocation work within each originating store ecosystem without a Newsroom account, silent cross-ecosystem linking or optimistic unlock before server verification.

### WS-C — Governed temporal knowledge projection

- Implement entity-resolution, claim-admission and relation-admission records and a graph projector that consumes the WS-A ledger-event contract from retained history or a verified authoritative baseline.
- Use Neo4j Community with Graphiti as the initial projection implementation and qualification lane inside this programme, not as a later add-on.
- Isolate any Graphiti extraction workspace from the admitted graph. Only the governed projector credential may expose admitted records.
- Pin ontology, projector, embedding, chunking, normalisation and index versions; expose contiguous checkpoint, gap and dead-letter state.
- Validate `same_event` or `development_of`, source-revision impact and long-running case or policy timeline retrieval on one versioned corpus.
- Replace only the projection adapter before first activation if Neo4j produces a measured licence, backup, footprint or deployment blocker. LadybugDB is a contingency, not a planned second stage.

**Exit evidence:** Delete Neo4j, lexical and vector projections, then rebuild them from retained ledger records and governed objects without rerunning stochastic extraction. Canonical entities, Governed Claims, Governed Relations and provenance remain structurally identical, subject only to explicitly recorded retention or deletion redaction.

### WS-D — Hermes retrieval and operational control plane

- Expose versioned, bounded, read-only operations such as `find_related_story_candidates`, `get_event_timeline`, `find_source_revision_impact`, `find_versions_using_claim` and `get_story_provenance`.
- Return canonical IDs, trust scope, exact provenance references, temporal context, projection watermark, projector/ontology version and explicit gap or incompleteness state.
- Keep Hermes unaware of Neo4j internal IDs and deny generic write-capable Cypher. Any Hermes-generated relationship follows the same ledger proposal command as every other extractor.
- Provide Web Admin health, access/loading state, backup freshness, manual-approval queues, projection lag, dead letters, target drift and reconciliation views through bounded admin APIs.
- Expose the full held-work lifecycle: queued, claimed where applicable, permission denied, stale conflict, action in progress or failed, mandatory revalidation, authority commit, dispatch, expiry and terminal result. Commands carry the exact candidate, story version, evidence package, staged candidate-manifest digest, actor, idempotency identity and expected decision version.

**Exit evidence:** Hermes answers the three priority use cases through named tools, and Admin can identify stale or incomplete projection, backup and target state and safely resolve a held item without inspecting raw databases or visual screenshots. Concurrent reviewers cannot commit conflicting outcomes.

### WS-E — Integrated vertical proof and one activation gate

Prove three end-to-end slices against one fresh target database:

1. source ingest -> immutable observation -> extraction proposal -> admission -> governed graph projection -> Hermes retrieval;
2. approved story version -> evidence and surface manifest -> immutable bundle and publication decision -> target operation -> online serving -> acknowledgement or observation -> Semantic UI projection; and
3. source revision -> claim and story impact -> correction decision -> updated graph and serving projections -> target reconciliation.

The owner makes one final production-activation decision. The following are independently evidenced diagnostic sub-gates, not rollout stages:

- **Authority:** canonical schema, command isolation, governed objects, audit, event log and coordinated backup or restore.
- **Publication:** bundle and decision atomicity, target-operation dispatch, idempotency, acknowledgements or observations and reconciliation.
- **Serving:** online projection, visibility, access-policy resolution, clock semantics, rebuild and server-side fail-closed behaviour.
- **Knowledge:** entity resolution, proposal and admission, Neo4j projection, destructive rebuild, temporal retrieval quality and coverage metadata.
- **Operational:** pause, dead letters, projection gaps, backup freshness, Admin observability and held-work concurrency.
- **Reader and commercial access:** iPhone, iPad, Android phone and Android tablet feed, article, automatic paid preview, global preview-disable state, inline paywall gate, single-primary pre-purchase action hierarchy, `PURCHASE_IN_PROGRESS`, transient non-error `PURCHASE_CANCELLED`, `VERIFYING_ENTITLEMENT`, non-terminal `VERIFICATION_DELAYED`, provider-definitive `VERIFICATION_FAILED`, stable reader-safe Verification Failure Reasons, Restore-first Verification Failure Recovery, privacy-minimised Support Case submission and restricted Web Admin queue, single-flight automatic and manual Verification Recovery, ephemeral native Store-authoritative commerce-metadata loading and unavailable states, restriction, correction, empty, partial and error flows; labelled Free Samples; store-managed trial; explicit-action purchase and restore; paid-access grant; native Semantic UI; text scaling, screen-reader, focus and touch-target acceptance. Web Admin receives equivalent keyboard and screen-reader evidence.

Internal pull requests may follow dependency order or deliver thin vertical slices, but there is no intermediate production release whose canonical data later needs conversion. A failed sub-gate identifies the blocked capability; it does not authorise a partial production architecture.

**Exit evidence:** Every sub-gate and every item in the release acceptance section passes on a clean installation and after destructive projection rebuilds, followed by one explicit owner activation decision.

## PR 75 disposition and reuse gates

PR 75 remains independently reviewable until the owner decides its disposition. Passing CI or being mergeable does not make it production-ready.

| PR 75 area | Treatment in this programme |
|---|---|
| Canonical JSON, content digests and package-integrity tests | Port after resolving identity and digest-cycle findings; bind them to canonical `EvidencePackage`, `SurfacePayload` and decision-free `PublicationBundle` contracts. |
| SQLite transaction and durability patterns | Reuse selectively behind smaller repositories; do not carry the multi-responsibility `GovernanceStore` forward unchanged. |
| Audit, pause, authority revision, leases and fencing | Preserve the semantics after crash/replay and ownership findings are resolved against the canonical ledger-event, target-operation and checkpoint model. |
| Recording intent and recording-only publisher | Use as test inspiration only; replace with the canonical multi-target command, acknowledgement and reconciliation model. |
| Shadow policy and fixtures | Retain useful deterministic policy cases and zero-public-capability tests; remove shadow target names from production contracts. |
| Legacy adapter | Do not make it the authority intake for the new system. Any approved historical import is a separate, idempotent one-time adapter. |

Before reuse, PR 75 findings #61, #62 and #65 apply to package and decision primitives; #63, #66 and #67 apply to outbox or event primitives; #68 concerns the monolithic store design; #64, #69 and #71 concern live authority, storage admission or crash-safe dispatch; #70 concerns a delivery response contract; #72 and #74 concern intake or CLI error contracts; and #73 concerns audit control. When the replacement draft PR opens, triage each finding against the donor map: migrate it if its primitive is retained, or close it with the supersession rationale if the underlying shadow code is rejected. Closing PR 75 itself must not be represented as resolving a migrated finding.

## Release acceptance

1. A fresh installation creates canonical production schema v1 directly; neither a PR 75 database nor a shadow-v1 migration is required.
2. One source fixture completes source observation, entity resolution, claim-and-relation proposal and admission, Neo4j projection, Hermes retrieval, publication bundle, online serving and target acknowledgement or observation using the same canonical IDs.
3. The same story and version IDs are visible in the ledger, graph, serving payload, Semantic UI projection and target evidence, with the same stable Access Policy Key.
4. Crash injection proves each domain mutation, audit record and ledger event is atomic, and that only required target operations join an authorising transaction; projectors recover through their own checkpoints without per-consumer authoritative outbox rows.
5. Deleting graph and serving stores and rebuilding from retained events or a verified authoritative baseline preserves canonical IDs, payload digests and external contracts without resurrecting deleted data.
6. Graph unavailability does not corrupt a valid publication or direct reconciliation; a dependency-coverage record proves completeness, and restoration resumes from a contiguous checkpoint without synthetic history.
7. Serving unavailability retains target operations and eventually converges without a lost or blind duplicate publication; an unobservable target remains truthfully ambiguous.
8. Graphiti output remains an immutable proposal, depended-on entity mentions resolve first, and no claim or relation enters the governed graph before its separate admission decision.
9. A source revision finds directly affected claims and controlled surfaces, produces the required correction workflow, and updates graph and serving projections.
10. Access-policy assignments can change without rewriting story, story-version, surface-payload or publication-bundle identity, while each free, entitled, restricted, pending or error access decision identifies the exact resolved revision.
11. Hermes and Admin receive explicit projection lag, gap and trust metadata, cannot use a write-capable graph credential and cannot directly write the ledger or obtain a publication credential.
12. Discord and OpenClaw credentials, message models and identifiers are absent from the new target contracts and activation path.
13. The dedicated command service is the only filesystem writer; authenticated stale-command and network-filesystem tests fail closed.
14. A coordinated encrypted database-and-object recovery drill meets approved objectives, excludes publication credentials and proves deletion-aware quarantine before restart.
15. Public-effect observations preserve asserted and observed times; feed and acknowledgement clocks remain distinct and auditable.
16. The four supported mobile and tablet classes pass feed, article, correction, restriction, paywall, purchase, same-ecosystem restore and paid-access flows through the native Semantic UI contract, including accessibility evidence and no first-party Newsroom account.
17. Authority, Publication, Serving, Knowledge, Operational, and Reader and commercial access sub-gates all pass before one explicit owner activation decision.
18. Every paid article carries one authorised Preview Excerpt within one quarter of its canonical narrative-body grapheme count, excluding headline, byline, metadata, sources, related links, images and captions; non-text content appears only with rights-validated Preview Media Permission and is otherwise restricted without blocking a media-led article. An Inline Paywall Gate follows the resulting boundary, or the header and permitted hero media when the preview is hidden or empty, and cannot launch a Store flow without reader action. The default-on preview can be hidden or restored globally only through the authenticated, audited owner control, and an indeterminate state hides it.
19. The Inline Paywall Gate presents localised price, billing period and eligibility-specific trial or offer terms only from current platform Store Commerce Metadata for the selected product, composed as ephemeral native-client display state rather than a replayable Newsroom projection. If that metadata is unavailable, the gate presents no stale commerce claim, keeps Retry and Restore Purchase available and disables Subscribe. Available metadata or offer eligibility alone leaves access restricted; only verified purchase proof resulting in an effective Store Entitlement and Access Grant authorises paid access.
20. Before purchase, the Inline Paywall Gate exposes exactly one Primary Commerce Action: Start Trial only when current Store Commerce Metadata confirms trial eligibility, Subscribe otherwise, or Retry when metadata cannot be obtained. Restore Purchase remains secondary in every case, and Start Trial and Subscribe never compete as simultaneous primary actions.
21. Invoking Start Trial or Subscribe puts the gate into `PURCHASE_IN_PROGRESS` and disables repeated purchase initiation. A native Store success then produces `VERIFYING_ENTITLEMENT` and `ENTITLEMENT_PENDING`, not `ALLOWED_ENTITLED`; the article remains restricted until verified proof establishes an effective Store Entitlement and the server issues a signed Access Grant.
22. A reader-originated native Store cancellation produces transient non-error `PURCHASE_CANCELLED`, leaves the article restricted, performs no entitlement verification, presents no error banner and returns to the current pre-purchase gate with its appropriate Primary Commerce Action and Restore Purchase re-enabled.
23. Verification that exceeds the configured reader wait limit produces non-terminal `VERIFICATION_DELAYED` while access remains `ENTITLEMENT_PENDING` and restricted. Start Trial and Subscribe remain unavailable; Retry Verification is primary, Restore Purchase is secondary, and any retry idempotently rechecks the same Store transaction without initiating another purchase.
24. Reader Retry Verification, network restoration, app foregrounding, a native Store transaction update and an authenticated provider server notification each trigger Verification Recovery for the same stable verification identity. Concurrent triggers coalesce into at most one active verifier operation, never open a purchase surface and can produce at most one effective Store Entitlement and Access Grant authority.
25. Only an authenticated, definitive Store provider verdict that the transaction is invalid or cannot grant the selected product and access class produces terminal `VERIFICATION_FAILED`. Network loss, timeout, throttling, provider 5xx or unavailability, delayed notification, absent response and exhausted retry budget remain `VERIFICATION_DELAYED`, non-entitled and recoverable.
26. In `VERIFICATION_FAILED`, Restore Purchase is primary and Get Help is secondary while Start Trial, Subscribe and Retry Verification are unavailable. Get Help automatically carries only an opaque diagnostic reference, not identity or reading data; only a provider-backed restore result confirming no active or pending entitlement can return the gate to ordinary pre-purchase actions.
27. Every `VERIFICATION_FAILED` result for the submitted transaction maps to exactly one stable reader-safe reason: `TRANSACTION_INVALID`, `PRODUCT_MISMATCH`, `STORE_CONTEXT_MISMATCH`, `ENTITLEMENT_INACTIVE` at verification time or fallback `PURCHASE_NOT_VERIFIED`. The reader sees only localised non-technical content derived from that reason; raw provider codes and payloads remain protected operational evidence and all reasons preserve the same Restore Purchase and Get Help hierarchy. Later expiry, refund or revocation of an already verified Store Entitlement updates entitlement and access state without creating `VERIFICATION_FAILED`.
28. Get Help opens a Newsroom-hosted privacy-minimised form that automatically contains only the opaque diagnostic reference. A reader may voluntarily add a reply email address and problem description only after explicit consent; the submission contains no Store receipt, raw provider detail or reading history and creates a Support Case in a role-restricted Web Admin queue for designated Owner or Support operators.

## Cutover and rollback

The legacy runner may remain frozen as a separate current service only until the integrated target passes its single activation gate. It is not incorporated into the new architecture, and no new component depends on Discord or OpenClaw. Cutover is one controlled switch to the app-serving controller followed by retirement of the legacy path; it is not a migration between two versions of the new data model.

Any historical content import requires an explicit owner decision and a one-time idempotent adapter into the canonical contract. The new system does not inherit PR 75 records merely because its code is useful.

Rollback of a projector, adapter or serving release preserves ledger sequence, immutable object and bundle identities, target operations, attempts, responses, observations, reconciliation and audit history. Replacing Neo4j or another derived engine means dropping and rebuilding that projection. It must not rewrite canonical records, revive superseded commands or rerun stochastic extraction as historical fact.

## Risks and decisions still required

- ADR 0001 and ADR 0002 remain Proposed until this cross-spec retune is reviewed and the command-writer and recovery boundaries below are resolved; the entitlement authority boundary is accepted in ADR 0003.
- The specifications remain Draft; this plan does not itself authorise production implementation.
- PR 75 has unresolved review findings despite clean mergeability and CI.
- The first app-serving platform and target API capability matrix remain unselected.
- The free layer is now distinct from the store-managed Subscription Trial and consists only of reader-labelled, human-designated Free Samples. Trial duration, authorised roles and the human operating rule for sample count, rotation and retirement remain undecided.
- Automatic paid previews, the fail-closed Global Preview Control, the canonical narrative-body Unicode-grapheme denominator, continuous-prefix ordering, normal complete-sentence or complete-list-item boundaries, the word-then-grapheme within-unit fallback and rights-validated indivisible media boundaries are fixed. Neither an oversized first unit nor a media-led article without permitted preview media blocks publication. The Inline Paywall Gate location, absence of automatic popup, explicit-action Store entry, Store-authoritative price, billing-period and offer-eligibility display, metadata-unavailable behaviour, strict separation of ephemeral commerce display from replayable projections and entitlement authority, single-primary pre-purchase action hierarchy, Entitlement Verification Barrier, transient non-error Purchase Cancellation path, non-terminal Verification Delay without repurchase, single-flight automatic Verification Recovery triggers, provider-definitive-only Verification Failure classification, stable reader-safe Verification Failure Reasons, Restore-first Verification Failure Recovery, and the Newsroom-hosted privacy-minimised Support Case path are fixed. The reader wait limit, retry backoff and budget, Support Case retention and service level, exact copy and visual treatment remain undecided.
- Pseudonymous store entitlement, purchase and same-ecosystem restore are fixed by ADR 0003. A focused privacy and GDPR assessment still needs to confirm retention, processor roles, lawful basis and operational controls; pseudonymisation is not an exemption.
- Governed-object retention may conflict with rights, privacy or deletion duties and needs an explicit deletion-scope policy.
- SQLite service identities, filesystem enforcement, key management, recovery point, recovery time, restore window and capacity triggers require selected mechanisms and measurable thresholds.
- Neo4j Community licence, backup, security and single-instance limits must pass the commercial-product qualification gate before activation.

## Decisions needed

1. Select the command-service identity, local filesystem permissions and process boundary that enforce exclusive ledger and governed-object writes.
2. Select backup encryption and key ownership, the separately protected deletion journal and restore-authorisation mechanism.
3. Commission the focused privacy and GDPR assessment for the minimal entitlement record, provider verification, Access Grant and retention policy without reopening the no-account boundary by default.
4. Select the first online app-serving target and its required create, update, remove, observe and idempotency capabilities, including the policy for permanently ambiguous targets.
5. Define the controller or serving event that assigns `primary_feed_published_at`; retain immutable public-effect and acknowledgement evidence separately.
6. Choose the store trial duration, authorised human roles and operating rule for selecting, rotating and retiring labelled Free Samples without changing the stable access-policy contract.
7. Select the Verification Delay reader wait limit and retry backoff and budget, and set Support Case retention and service-level ownership around the fixed entitlement and support paths; leave exact copy and styling to reader-interface design.
8. Set projection freshness, gap and degraded-operation thresholds for every Hermes and Admin operation.
9. Set the SQLite operating and ledger/object-store recovery targets and the pre-production Neo4j qualification thresholds.
10. After decisions 1–2 and the contract review, accept, amend or reject ADR 0001 and ADR 0002 together as simultaneous parts of this single target architecture.
11. Open the draft replacement architecture PR, add its donor map and link it from PR 75, then close PR 75 as superseded without merging and triage findings #61–#74 by retained scope.

## Completion record

Not started. This Proposed plan defines one target architecture and one activation gate; it does not claim implementation or approval.
