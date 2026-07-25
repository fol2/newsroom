# Increment 2A governed relation authority

**Role:** Implementation and operations record
**Status:** Draft PR evidence — no activation authority
**Owner:** Product owner
**Implementation issue:** #155
**Parent epic:** #142
**Draft PR:** #159
**Authorised base:** `main@f29a24201d9808cf8079646c40eaedece5b98ec0`
**Canonical language:** English

## Purpose and exact boundary

Increment 2A adds the first production-shaped SQLite authority for editorially meaningful relations and the repository-owned `integrated_fixture_v2` contract. It does not start Increment 2B.

The unit implements:

- typed immutable Relation Proposal, Relation Admission Decision and admitted Relation Assertion records;
- one exact repository-owned `DEVELOPMENT_OF` fixture rule;
- independently authenticated and authorised fixture-binding, proposal and decision commands;
- checked SQLite schema v6 and startup cross-record validation;
- idempotency, semantic collision, conflicting-proposal retention, stale-decision, hold, rejection, admission, invalidation, revocation and supersession semantics;
- an engine-neutral admitted-relation projection-event seam;
- governed-object rights, lifecycle, deletion and tombstone linkage; and
- synthetic English and Hong Kong Traditional Chinese fixture data.

SQLite ledger records, immutable decisions and governed objects remain authoritative. Neo4j receives no write in this unit. There is no raw driver, arbitrary Cypher, caller-selected label, caller-defined relationship type or graph administration surface.

## Repository fixture contract

The checked fixture files are:

- `newsroom/fixtures/integrated_fixture_v2.json`;
- `newsroom/fixtures/integrated_fixture_v2.schema.json`.

The fixture is repository-owned synthetic expression, contains no personal data and uses only the retained `project.discovery` purpose. Its exact canonical manifest digest is derived from canonical JSON bytes at import and checked again at binding.

The fixture contains:

- formal process identifier `SYN-PROC-2042`;
- English and Hong Kong Traditional Chinese aliases;
- two immutable synthetic Source Revisions;
- separate Signal, Lead, Event Hypothesis Version and prior Candidate Version identities;
- four active bilingual evidence passages;
- two active ineligible distractor passages;
- one actually governed tombstoned negative passage; and
- one proposal-only `SAME_EVENT_AS` distractor.

The exact admitted fixture relation is:

```text
new Event Hypothesis Version
DEVELOPMENT_OF
prior Event Hypothesis Version
```

Admission also requires the exact repository producer identity, producer version, rule version, statement, uncertainty set, temporal scope and four governed evidence passages. A caller cannot obtain admission by matching only endpoints or confidence.

## Governed-object fixture binding

Every fixture byte sequence enters the existing governed object authority before relation authority can reference it.

The fixture binding command checks:

1. the exact repository fixture identity, schema version and canonical manifest digest;
2. the complete sorted passage set and exact blob digest for every passage;
3. immutable rights-decision canonical evidence, object class, allowed use, security scope and retention scope;
4. non-expiring retained repository-permitted rights for this deterministic fixture;
5. ACTIVE current lifecycle for every active passage; and
6. an actual prior `governed_blob.deletion.tombstoned` event for the tombstone-negative passage.

For every passage, the server retains an exact lifecycle link containing the lifecycle state, authority event ID, ledger sequence and recorded time observed before the binding event. Startup integrity re-derives that link from governed-object history. A JSON field claiming `TOMBSTONED` while the object remains ACTIVE is rejected.

Later revocation, deletion or physical removal does not rewrite the immutable binding. It changes current admissibility and the admitted projection state through later ordered lifecycle authority.

## Public command boundary

The public mutation facade is `GovernedRelations`. It exposes typed methods only:

- `bind_fixture`;
- `propose`;
- `decide`.

Each call creates a server-owned `SemanticCommand` and must pass authentication and authorisation before the private SQLite store receives a signed commit grant.

The command scopes are deliberately separate:

| Command | Scope | Trust |
|---|---|---|
| `integrated.fixture.v2.bind` | `authority.fixture.v2.bind` | `OBSERVED` |
| `relation.proposal.record` | `authority.relation.propose` | `PROPOSED` |
| `relation.admission.decide` | `authority.relation.admit` | authoritative decision envelope |

Idempotency namespaces remain bound to authority domain, principal and command type. Reusing one idempotency key for different canonical semantics fails. Exact replay returns the retained immutable identity and creates no second event, proposal, decision or assertion.

## Proposal identity, collision and conflict

A proposal has three distinct identities:

- stable typed Proposal ID;
- semantic slot digest over subject, predicate, object and temporal scope; and
- semantic identity digest over the complete proposal semantics except Proposal ID.

The content digest is an integrity and equality mechanism; it does not replace stable domain identity.

An exact semantic duplicate under another Proposal ID raises a semantic collision. A materially different proposal may occupy the same semantic slot and remains independently retained as `PROPOSED`. It receives no admitted projection effect merely because its endpoint axis or confidence resembles an admitted relation.

The repository fixture admission policy admits only the complete deterministic fixture proposal. Other predicates, producers, statements or evidence combinations may be retained, held, rejected, invalidated or superseded but cannot enter the admitted seam in Increment 2A.

## Decision lifecycle

Every decision is immutable and versioned per Proposal ID. A decision request must carry:

- the exact Proposal ID and Proposal digest;
- expected current decision version;
- exact previous Decision ID when one exists;
- one typed action;
- reason code and policy version; and
- exact successor Proposal ID for supersession.

A stale digest, stale version or wrong predecessor creates no transition.

Supported actions are:

- `HOLD` — retains a visible non-admitted current state;
- `REJECT` — records authoritative refusal without deleting the proposal;
- `ADMIT` — creates one immutable Relation Assertion for the exact fixture proposal;
- `INVALIDATE` — terminally invalidates the current proposal state;
- `REVOKE` — terminally removes an admitted assertion from current projection state; and
- `SUPERSEDE` — terminally links a compatible successor proposal while retaining both histories.

A proposal can allocate at most one assertion. Revocation, invalidation and supersession do not delete that historical assertion; they change the rebuildable current-state head and emit removal state for projectors.

## Admitted assertion and projection seam

The Relation Assertion reifies:

- typed subject and object identities;
- allow-listed predicate;
- `ADMITTED` trust scope;
- exact valid-time scope;
- exact governed evidence object identities and blob digests;
- producer and rule identities;
- statement and retained uncertainty;
- Proposal and Admission Decision identities; and
- a deterministic engine-neutral relation key.

The read authority is separate from proposal and admission mutation scopes. It exposes:

- bounded current admitted assertions; and
- bounded projection events after a ledger cutoff.

The current admitted view applies both current governed-object authority and relation valid time. A future-valid assertion remains immutable history but does not appear on the current admitted surface before `valid_from`.

Projection events contain only admitted assertion state:

- `UPSERT` carries an admitted Relation Assertion;
- `REMOVE` carries no assertion payload and identifies relation revocation, invalidation, supersession or the latest applicable governed-object lifecycle event.

Proposal-only records never appear in this seam. The `SAME_EVENT_AS` distractor is tested as retained proposal authority with zero admitted projection effect.

The seam is engine-neutral. Increment 2B will consume it through governed projectors and add actual Neo4j admitted-relation, full-text and vector generation state. Increment 2A itself performs no Neo4j operation.

## Rights, revocation, deletion and tombstone behaviour

Admission rechecks the current governed fixture manifest and every evidence object inside the same SQLite transaction boundary used to commit the decision.

An admitted assertion ceases to appear on the current admitted surface when any required object is:

- admission-revoked;
- blob-missing, corrupt, deletion-pending or deleted;
- deletion-requested, tombstoned or physically removed; or
- otherwise outside its retained purpose, security, retention or rights authority.

The projection seam associates removal with the latest exact lifecycle event and returns every invalid affected Object Admission ID in stable order. When several evidence objects are invalid, the reason code and source event are taken from the same latest event; they cannot be accidentally combined from different objects.

Tombstone and physical-removal history cannot recreate authority. Reopening SQLite validates immutable object and lifecycle linkage but does not reactivate the relation. A later graph rebuild must consume this retained authority and must not infer relation state from Neo4j.

## SQLite schema and startup validation

Checked migration `governed_relation_authority_v6` adds immutable tables for:

- fixture bindings and passage object linkage;
- Relation Proposals and evidence linkage;
- Relation Admission Decisions and current heads;
- admitted Relation Assertions and evidence linkage.

The migration is part of the repository schema fingerprint and exact migration history. SQLite remains configured with foreign keys, WAL and `synchronous=FULL` through the existing authority store.

Every store open validates:

- schema version, migration checksums and schema fingerprint;
- SQLite quick check and foreign-key check;
- command, payload, event and audit envelopes;
- canonical bytes and digests for every new immutable row;
- fixture manifest and passage equality with repository files;
- historical ACTIVE and TOMBSTONED lifecycle links ordered before fixture binding;
- Proposal columns, semantic digests and exact evidence mappings;
- Decision predecessor chains, Proposal digest and authority-event mapping;
- Assertion equality with the admitted Proposal and Decision;
- assertion-evidence equality with Proposal evidence; and
- current decision-head equality with the latest immutable Decision.

Raw-SQL rebinding, re-digesting altered canonical bytes, changing an evidence admission, rewriting a decision head or tampering governed rights evidence causes store open to fail.

## Operator checks

Before review completion, run from the repository root:

```bash
uv lock --check
python -m compileall -q newsroom scripts
python -m pytest -q
python scripts/eval_clustering_metrics.py \
  --dataset newsroom/evals/clustering_eval_dataset_v1.jsonl \
  --baseline newsroom/evals/clustering_eval_metrics_baseline_v1.json \
  --fail-on-regression
git diff --check
```

The exact reviewed PR head must also pass every applicable GitHub and SDLC workflow. CI is regression evidence, not owner approval.

## Fault handling

Do not repair relation authority by editing SQLite rows, deleting migration history or writing a compensating graph edge.

When startup validation fails:

1. stop relation proposal and admission work;
2. retain the database and governed-object directory as evidence;
3. identify the first failed invariant and exact immutable row or lifecycle link;
4. restore a verified pre-corruption authority backup or apply a reviewed forward fix;
5. reopen and rerun all relation, authority, migration and repository gates; and
6. rebuild disposable projections only from verified SQLite and governed-object authority.

Graph state is never a backup for Relation Proposals, Decisions or Assertions.

## Rollback

Increment 2A has no production, source, search, model, publication or public effect.

Before a database has migrated to schema v6, rollback is a normal revert of the Increment 2A source, fixture, documentation and tests.

After a database has migrated to schema v6, older code correctly rejects the newer schema. Safe rollback therefore requires either:

1. restoring a verified pre-v6 SQLite and governed-object backup; or
2. retaining schema v6 and applying a reviewed forward fix.

Do not perform an ad hoc down-migration by deleting relation tables or migration rows. Do not reconstruct authority from Neo4j. Disposable future fixture graph generations may be deleted and rebuilt from retained authority.

## Fixed exclusions and stop boundary

This unit performs none of the following:

- Increment 2B implementation;
- Neo4j relation writes, full-text indexes, vector indexes or generation changes;
- arbitrary Cypher or caller-selected graph mutation;
- Graphiti execution;
- external model, prompt or embedding calls;
- live RSS, JSON, search, Brave, GDELT or other source execution;
- general entity resolution, merge, split or reversal;
- hybrid retrieval, fusion or Retrieval Context v2;
- full triage, Candidate admission or Evidence Intake;
- scheduler, shadow, canary or production activation;
- publication, spending or public effect.

Issue #156 remains blocked until Increment 2A is merged to `main`, issue #155 is closed with exact evidence, and the relation, fixture and projection-event contracts are stable on the then-current main head.
