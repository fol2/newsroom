# Increment 3C substantive review

**Date:** 2026-07-28
**Implementation issue:** #207
**Parent:** #143
**Programme:** #141
**Authorised base:** `main@707519cebcc18fd8010b9b1b608b361ab2f6de03`
**Review unit:** Increment 3C — Check, baseline and observable-transition authority
**Runtime authority:** Repository fixtures and approved replay only

## Review conclusion

Increment 3C now provides authenticated, append-only Check Request, Attempt, Outcome, baseline, source-lineage admission, observable-transition and Operational Finding authority over the merged Increment 3A/3B contracts. It retains exact source observations without creating Discovery Signals, Gate Decisions, Leads, Candidates, evidence conclusions, model work, external source access, publication or public effect.

Current substantive-review disposition:

- P1 findings: **0**;
- P2 findings found and corrected: **33**;
- unresolved P1/P2 findings: **0**;
- focused Increment 3C tests: **80 passed**;
- complete repository tests: **1,391 passed, 32 service-only tests skipped in the local non-service run**;
- clustering regression gate: **passed with no baseline regression**;
- temporary materialisation, payload or export transport retained in the final product tree: **0 files required**.

The final exact-head workflow and artifact evidence remains a merge gate. This review closes the known local design and implementation findings; it does not independently authorise merge or production activation.

## Reviewed surface

The review covered:

- stable Check Request identity, immutable Attempt order and one Outcome per Attempt;
- exact Source Definition Version, coverage, rights, adapter, producer and policy binding;
- proposal admission into Source Item, Revision, Representation and Occurrence authority;
- maintained-document, append-only, rolling-list, complete-current-state, explicit-delta and Planned Agenda policies;
- establishment, reset, rebuild, bounded backfill and manual-hold baseline decisions;
- all observable transition kinds and complete-snapshot/Agenda guards;
- Operational Finding case and occurrence separation;
- replay, crash-prefix recovery and competing-worker convergence;
- canonical payloads, normalized SQLite columns, immutable convenience indexes and startup rederivation;
- source-version continuity and historical lineage;
- semantic observation chronology under delayed child-record commits;
- authenticated writes, redacted reads, traceability, operations, exclusions and rollback; and
- compatibility with every retained repository authority and projection regression.

## Corrected findings

### P2-01 — Agenda transition lineage could retain a Representation without a current Revision

Transition contracts now require current Revision and Representation to move together. Agenda expectation-only transitions cannot retain impossible representation lineage.

### P2-02 — Check command events were absent from the shared event-envelope validator

The exact event-envelope command map now includes all seven Check, baseline, transition and Finding commands with their aggregate, event, trust, security, retention and payload contracts.

### P2-03 — Source-version upgrades could split unchanged publisher state

A later Source Definition Version may record a new Representation and Occurrence against the same valid publisher-state Revision when the source identity and revision policy prove continuity. Version downgrades and stale new writes still fail closed.

### P2-04 — One retained Outcome could be reinterpreted with different decision inputs

Proposal-generated Outcome semantic identity now binds the exact baseline control and transition directives. Replay cannot later change baseline or transition classification.

### P2-05 — Absence and Agenda guards trusted caller-supplied counts and booleans

Confirmation guards now retain exact Check Outcome, Check Request and adapter-request-digest references. Authority rederives completion, source/version lineage, contract equality and chronology.

### P2-06 — Retries could inflate confirmation counts

Confirmation evidence now requires distinct Check Request identities. Multiple Attempts or Outcomes under one Request cannot masquerade as independent confirmations.

### P2-07 — Transition observation time could differ from its Outcome

Every Observable Transition must use the exact Check Outcome completion time. Source-asserted time remains separate untrusted metadata.

### P2-08 — Baseline decisions did not rederive their exact parent evidence

Baseline authority now revalidates the exact Outcome, Request, source model, baseline policy, chronology and source/producer/representation/validator digests before commit and on reopen.

### P2-09 — Included baseline entries were not proven observed by that Outcome

Every included Source Item and Revision in a baseline manifest must have an exact Discovery Occurrence under the baseline's Check Outcome.

### P2-10 — Baseline-head timestamps could diverge from the retained head

Head timestamps now equal the exact current Baseline Decision time. Startup rejects a mutated or reconstructed head.

### P2-11 — A later Attempt could outrun its predecessor Outcome

Attempt N must name Attempt N-1, and the predecessor must have a completed Outcome no later than the new Attempt start time.

### P2-12 — Operational Finding scope could disagree with its cited lineage

Finding scope now resolves to the exact Request, Attempt, Outcome, Source Item, Source Version or adapter authority it names. Finding occurrences must preserve the stable case scope.

### P2-13 — Structurally valid transitions could describe impossible history

Transition admission and startup rederive prior observed Revision and prior transition state. First observation, re-observation, reactivation and Agenda continuation cannot be asserted without their required history.

### P2-14 — Discovery Occurrences could cite missing or mismatched Check Outcomes

Post-v11 Occurrences require an exact retained successful observable Outcome with matching source/version, completion time, receipt, Revision and Representation.

### P2-15 — Startup inner joins could hide orphan Occurrences

Occurrence integrity now begins from every retained Occurrence and uses outer-link checks. Missing Outcomes or Check links are detected rather than filtered out.

### P2-16 — Outcome evidence classes permitted contradictory transport/parser claims

Blocked and disabled Outcomes cannot carry transport evidence; every post-preflight Outcome requires a receipt; HTTP/transport failures cannot claim parser evidence; malformed/drift Outcomes require parser evidence; observed items require parser evidence. Equivalent SQL checks protect schema v11.

### P2-17 — Unchanged observations did not retain exact item provenance

Check Outcomes now retain every exact observed item key and digest, not only changed candidates. Parser-only unchanged work therefore has durable item-level provenance.

### P2-18 — An unrelated Representation could be attached to a successful Outcome

Occurrence admission derives the deterministic Source Item identity from the Outcome's observed item key and requires the Representation digest to equal the observed item digest.

### P2-19 — Observed-item bytes and counts lacked an independently checked index

Canonical observed-item bytes are mirrored into immutable `check_outcome_observed_items` rows containing item key, item digest and deterministic Source Item ID. Reads and startup require exact canonical/index equality.

### P2-20 — First-run policy could imply historical novelty

Maintained documents create an explicit baseline only; bounded backfill retains included and excluded history; complete-state first observation means observed active, not proven newly activated.

### P2-21 — Rolling or append-only disappearance could imply ending

Append-only disappearance has no ending authority. Rolling-list disappearance is at most `AMBIGUOUS_ABSENCE` under a non-authorizing guard.

### P2-22 — Incomplete output could create implicit absent state

Partial and truncated Outcomes may advance independently valid present items, but cannot establish clean absence, ending, withdrawal, cancellation or a clean Agenda miss.

### P2-23 — Transition directives were not fully source-local

Each directive must resolve its item key, related item, source version and exact current/prior lineage under the same source authority. Cross-source classification fails closed.

### P2-24 — Baseline reset and rebuild could drift from the current head

Reset/rebuild requires a `RESET_REBUILD` trigger, exact predecessor identity and later retained decision. Automatic baseline control cannot silently name or replace a predecessor.

### P2-25 — Classified transition replay could substitute a later interpretation

Deterministic transition identity includes the exact Outcome, item, prior/current Revision, Representation, related item, directive and policy. A different classification collides rather than replays.

### P2-26 — Resumed admission could report a replay while creating missing authority

Admission results now retain explicit states for baseline, transitions, Findings and Finding occurrences. A retry that creates any missing record reports completion rather than full replay.

### P2-27 — Competing workers could misreport a retained winner as newly created

Item, Revision, Representation, Occurrence and decision states distinguish `CREATED`, `REUSED` and `REPLAYED` after exact conflict reload.

### P2-28 — Conditional or incomplete absence evidence could authorize ending

Ending requires complete, identity-confirmed, scope-complete, pagination-complete, grace-satisfied confirmations with no alternative explanation. Conditional or partial evidence cannot authorize state removal.

### P2-29 — Child-record ledger order could override source observation order

Latest observed Revision and latest Observable Transition now order by Check Outcome completion time and Outcome authority sequence, with child event sequence only as a final tie-break. Delayed recovery commits cannot move state history backwards.

### P2-30 — Representation ledger order could override parser production order

The latest Representation for one Revision is selected by production time and then authority sequence. A late commit of older parser output cannot become current provenance.

### P2-31 — An earlier observed Outcome could remain incomplete while a later Check classified the item

Proposal admission now detects an earlier observed Outcome lacking its exact Occurrence and stops before committing the later Outcome. Direct transition authority performs the same fail-closed history check.

### P2-32 — Prior-state counts could include future or same-time-later observations

Prior Revision and Occurrence lookups are bounded to the current Outcome's semantic position. Exact replay uses the retained current Outcome sequence; a not-yet-retained Outcome treats already retained same-time Outcomes as prior. Future child records cannot change an earlier replay classification.

### P2-33 — A same-time later crash prefix could poison exact earlier replay

A later Outcome may have committed a non-head Revision and Representation before crashing ahead of its Occurrence. Exact replay of an earlier Outcome at the same completion time now reuses its already observed non-head Revision, while an unobserved non-head state remains eligible only as the current crash prefix or under explicit reactivation policy. A genuinely new Check still stops behind the unresolved later prefix.

## Adversarial evidence added

The Increment 3C suites now prove, among other cases:

1. exact Request replay and separate immutable Attempts;
2. one Outcome per Attempt and proposal;
3. parser-only reprocessing creates Representation/Occurrence only;
4. first maintained observation is baseline-only;
5. later maintained state creates one Revision and `REVISED` transition;
6. append-only, rolling, complete-state, explicit-delta and Agenda policy distinctions;
7. complete-snapshot ending and Agenda miss require exact independent confirmations;
8. retries cannot inflate confirmations;
9. partial/degraded output cannot infer absence;
10. malformed and failed proposals create stable Findings without source history;
11. missing Finding authority prevents a partial Outcome commit;
12. exact crash-prefix replay completes only missing records;
13. competing workers converge on one semantic lineage;
14. raw-SQL mutation of canonical bytes, normalized columns, heads, links and observed-item index fails reopen;
15. unrelated Representation/Item attachment is rejected;
16. source-version upgrades preserve valid historical state;
17. reverse transition commit order still returns semantic latest state;
18. reverse Representation commit order still returns semantic latest provenance;
19. an earlier incomplete observed Outcome blocks later classification; and
20. same-time exact replay is bounded by Outcome authority sequence rather than future child commits; and
21. a later same-time Revision/Representation crash prefix cannot poison exact earlier replay, while a new Check remains blocked behind it.

## Authority and safety assessment

The implementation preserves these boundaries:

- only repository fixture and approved replay inputs are admitted;
- no source credential, network client, browser, scheduler or recurring worker is introduced;
- no model, Graphiti, embedding, search or arbitrary Cypher executes;
- Source Revisions describe permitted observable source-state differences only;
- first observation is not newly published, and Agenda expectations are not occurrence facts;
- Check Outcomes and Operational Findings are not editorial rejection, Signal, Lead, Candidate, materiality or truth decisions;
- Neo4j remains an offline-rebuildable derivative and receives no Increment 3C discovery projection;
- no shadow, canary, publication, spending, production activation or public effect occurs; and
- later Increment 3D/3E authority remains blocked.

## Rollback assessment

Before merge, rollback is branch deletion or a normal code revert. After schema v11 opens a database, do not downgrade or delete retained authority. Restore a verified pre-v11 backup or apply a reviewed forward correction. Baselines, Outcomes, observed-item index rows, Occurrences, transitions and Findings must not be reconstructed from Neo4j or parser output.

## Remaining exact-head merge gates

Before merge, PR #214 must retain successful evidence for its final reviewed head from:

- CI;
- Authority A2a;
- Authority A2b;
- Projection B1;
- authenticated Projection B2/B3/C1 Neo4j regression; and
- SDLC Evidence Shadow route, core, service and final decision.

The final head must also have zero unresolved review threads, zero actionable review comments, zero unresolved P1/P2 findings and no temporary payload, materializer or export workflow. CI is regression evidence, not owner or production approval.

## Stop boundary

Increment 3D remains blocked. Do not begin Discovery Signal, Gate Decision, Lead, urgency, Watch Condition or discovery-lineage projection implementation until PR #214 is merged, issue #207 is closed with exact completion evidence, and the resulting `main` head retains deterministic source Revision and transition authority without premature editorial effects.
