# Increment 4E substantive review — bilingual governance and actual Neo4j

**Issue:** #229
**Parent:** #144
**Authorised base:** `main@bf7b955d57f5e583fcfc9bade109eec79564a200`
**Review status:** current local source review; not final merge evidence

## Review scope

This review covers the deterministic Source Revision → Graphiti fake/replay → entity resolution → relation admission → admitted-only actual-Neo4j proof. It includes generation rebuild, active serving, workspace loss, graph loss, entity lineage, relation correction, revocation, source tombstoning and permanent workflow routing.

It does not approve a real Graphiti, model, embedding, live-source, publication or production runtime.

## Review method

The review inspected:

- all new `newsroom.increment4` contracts, projection code and controller code;
- the existing 4A–4D authority seams consumed by 4E;
- exact fake and approved-replay fixture construction;
- current and historical entity/relation authority behavior;
- SQLite/Neo4j generation boundaries and private-driver imports;
- actual-service test selection and JUnit enforcement;
- rights, deletion, tombstone and rebuild behavior;
- public API, credential, Cypher and private-ID exposure; and
- permanent A2a, A2b, B1, service and signed SDLC routing.

## Findings and corrections

### P2-01 — admitted snapshots originally required at least one entity

A rights purge can legitimately leave no current admitted entities or relations. Requiring non-empty state would force a stale generation to remain active or misclassify lawful deletion as a failed rebuild.

**Correction:** the snapshot accepts immutable empty entity and relation tuples while still requiring retained event authority and an exact cutoff. The controller can validate and promote a zero-node, zero-relation replacement generation.

### P2-02 — replacement generation status could resolve the prior ACTIVE checkpoint

Family status reports the current ACTIVE generation by design. Using it while building a replacement could bind the predecessor checkpoint to the new generation.

**Correction:** a generation-specific authenticated status read was added and the controller binds the exact BUILDING generation checkpoint.

### P2-03 — source-watermark equality was too strict for structural projection

Projection-management events are optional for the admitted structural family. A valid generation checkpoint may therefore exceed the latest non-projection source watermark.

**Correction:** validation requires checkpoint greater than or equal to the required source watermark and separately requires the latest non-projection source watermark to equal the request. The same condition is checked atomically at validation and promotion.

### P2-04 — the package root imported the official Neo4j driver transitively

Eagerly importing `.neo4j` from `newsroom.increment4.__init__` made the static boundary inventory treat the package root as a second official-driver importer.

**Correction:** Neo4j controller exports are lazy and cached. Only `newsroom/projection/neo4j/_adapter.py` imports the official driver.

### P2-05 — the permanent actual-service workflow omitted Increment 4E

The signed service topology knew about the 4E test file, but the standalone permanent Projection B2/B3/C1 workflow did not execute or inspect its cases.

**Correction:** the workflow invokes the exact service file and validates the exact four required cases, with no skip, failure or error permitted.

### P2-06 — the SDLC classifier contract retained the old service inventory

Adding the 4E service file to the classifier without changing the exact expected test list caused repository CI to fail.

**Correction:** the classifier test now includes the 4E service file in canonical sorted order. Workflow and routing changes are covered together.

### P2-07 — downstream authority initially bound the source fake attempt

Using the source fake attempt for entity and relation decisions would make approved replay an unexercised side record rather than the recovery path.

**Correction:** downstream fixture authority binds the approved replay Run Version, output and Proposal Set. The source attempt remains retained history only.

### P2-08 — bilingual equivalence needed exact accepted evidence

Matching English and Traditional Chinese names could otherwise be interpreted as automatic canonicalisation.

**Correction:** the Chinese alias is admitted only after an explicit resolution proposal and accepted decision tied to exact retained evidence.

### P2-09 — identical bilingual names needed context-separated fixtures

A single bilingual person does not prove false-merge protection.

**Correction:** the deterministic fixture contains two people with identical English and Chinese names in different contexts. Four mentions resolve to two distinct Canonical Entities; crossed pairings never admit.

### P2-10 — unresolved identity needed immutable relation history

Merely raising an admission error would not prove an inspectable editorial decision.

**Correction:** the relation receives `HOLD` at decision version 1 while the material dependency is unresolved. A later accepted identity decision permits `ACCEPT` at version 2 without rewriting the hold.

### P2-11 — relation-assertion endpoints required ACTIVE predecessors

A current correction may need to point to a superseded predecessor assertion. Requiring the predecessor to remain ACTIVE made valid correction lineage unreadable after supersession.

**Correction:** assertion endpoints require retained assertion authority and live underlying source/entity rights, not ACTIVE lifecycle. Revoked or rights-invalid material still fails closed.

### P2-12 — the mapper initially supported only entity endpoints

Correction and supersession lineage between relation assertions could not be projected through the dedicated admitted family.

**Correction:** relation-assertion endpoints are reified with deterministic subject/object structural bindings and exact predecessor provenance.

### P2-13 — historical alias provenance conflicted inside one structural batch

Lineage rebuild may contain historical aliases whose first authority events differ from the current projection event. Reusing inconsistent node provenance can violate deterministic batch identity.

**Correction:** historical identity nodes use stable earliest retained provenance while structural relations use the exact current projection event required by the batch.

### P2-14 — merge and split could silently imply relation retargeting

Preferred identity changes might be mistaken for authority to rewrite older relation endpoints.

**Correction:** tests prove merge, split and reversal preserve prior assertion endpoint bytes. A new relation or correction decision is required for changed editorial meaning.

### P2-15 — workspace-loss recovery could accidentally rerun extraction

Reconstructing private proposal graph state or invoking the fake again would make the disposable workspace a hidden recovery source.

**Correction:** approved replay verifies retained output and proposal digests, uses no private graph recovery and does not invoke fake, Graphiti, model or network.

### P2-16 — graph-loss recovery needed exact generation replacement

Reusing a damaged generation or manually repairing rows would weaken reconciliation and audit.

**Correction:** complete graph loss allocates a new generation, replays retained admitted authority, reconciles exact counts and identities, validates, promotes and retires the predecessor.

### P2-17 — tombstone purge needed an empty ACTIVE generation

Deleting old graph rows without promoting a complete empty or reduced generation could leave serving metadata pointed at stale state.

**Correction:** the tombstone path builds and promotes an exact empty generation, purges the predecessor and proves exact replay cannot resurrect the prohibited derivatives.

### P2-18 — permanent focused lanes needed explicit 4E bridge files

Repository-wide execution alone does not guarantee the focused Authority and Projection lanes retain 4E coverage.

**Correction:** dedicated A2a, A2b and B1 bridge files prove chronological authority, rights/deletion behavior and admitted-only graph mapping with no Graphiti/proposal leakage.

## Authority review

SQLite and governed objects remain authority for source identity, rights, extraction output, proposals, entity decisions, relation decisions and ordered history. The 4E controller receives a typed snapshot and bounded callables; it owns no database or graph credential.

Neo4j is a derivative generation. It cannot allocate an entity, admit a relation, mutate a decision or recover missing authority. Promotion is recorded by relational authority only after actual graph reconciliation.

## Security review

The public 4E surface exposes no:

```text
Neo4j driver or session
generic Cypher or caller-selected labels/predicates
Neo4j element ID or Graphiti private ID
model, embedding, network or provider credential
entity or relation admission bypass
Candidate, Evidence Intake or publication writer
live-source, schedule, spending, shadow, canary or activation capability
```

Source and model output remain untrusted data. The deterministic fake has deny-all egress and no credentials. Approved replay reads retained authority only.

## Rights and deletion review

Every current use revalidates source-version, admission, access and deletion authority. Tombstoning denies current entity/relation reads, removes covered derivatives through a replacement generation and prevents replay resurrection. Immutable retained history remains subject to lawful retention; it is not exposed as current admitted state.

## Current local evidence

The current reviewed source has produced the following separate inventories:

```text
Increment 4E projection contracts:                         3 passed
Increment 4E generation controller:                        8 passed
Increment 4E workflow contracts:                           2 passed
Increment 4E governed fake/replay and lifecycle path:     10 passed
Permanent Increment 4E A2a bridge:                         1 passed
Permanent Increment 4E A2b bridge:                         1 passed
Permanent Increment 4E B1 bridge:                          1 passed
Permanent Authority A2a inventory:                        34 passed
Permanent Authority A2b inventory:                        91 passed
Permanent Projection B1 inventory:                        39 passed
Complete repository sharded inventory:                  1,826 passed
Intentional local service-only skips:                       38
Complete repository failures/errors:                         0
Focused failures/errors:                                     0
Required focused skips:                                      0
Compilation and diff checks:                              passed
ResourceWarning policy for focused 4E evidence:            fatal
```

The complete repository inventory was reproduced from the exact clean remote tree plus the retained advanced binary patch, split into twelve deterministic file shards solely to stay within the local execution-tool deadline. The four Increment 4E actual-service tests are intentionally skipped outside an authenticated service environment and must execute unskipped in the permanent Neo4j workflow. Final merge evidence must still come from retained exact-head permanent JUnit and signed SDLC evidence.

## Review disposition

```text
P1 findings:             0
P2 findings corrected:  18
Unresolved local P1/P2:  0
Review threads:          pending current clean remote-head audit
Exact-head workflows:    pending final clean publication
Real runtime:            disabled and unqualified
```

This document is not final merge evidence. Issue #229 and parent #144 remain open until one clean source-only head passes CI, Authority A2a, Authority A2b, Projection B1, authenticated Projection B2/B3/C1 Neo4j and signed SDLC Evidence Shadow, with zero unresolved P1/P2 findings and review threads.
