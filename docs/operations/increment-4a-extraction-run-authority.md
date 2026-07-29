# Increment 4A Extraction Run and proposal authority operations

**Status:** implementation review unit for issue #225
**Parent:** #144
**Authorised base:** `main@d03441ef2fa26b5dc83f65d1797abf2b381d8f1a`
**Execution boundary:** repository-owned deterministic bilingual fixture extraction and approved retained replay only

Increment 4A records immutable Extraction Runs, retained structured output and generic proposal envelopes over exact rights-permitted Source Revision, Discovery Representation and governed-object inputs. It grants no Canonical Entity, relation, Candidate, evidence, graph, publication or production authority.

A successful run means only that the configured proposal producer completed and its structured output passed the approved schema. Every resulting envelope remains `PROPOSED`. Confidence, bilingual equivalence, a predicate hint or successful execution never means `ADMITTED`.

## Public boundary

Open the authority through the dedicated submodule:

```python
from newsroom.authority.extraction_system import (
    open_governed_extraction_authority_system,
)
```

The returned object exposes one bounded facade:

```text
system.extraction.register_contract(...)
system.extraction.execute(...)
system.extraction.contract(...)
system.extraction.metadata(...)
system.extraction.run_history(...)
system.extraction.proposals(...)
system.extraction.raw_output(...)
```

The facade exposes no SQLite connection, capability issuer, command grant, arbitrary query, Graphiti workspace, model provider, graph writer, Candidate writer, Evidence Intake writer or publication writer. Importing from `newsroom.authority.extraction_system` rather than adding the extraction system to the broad `newsroom.authority` package also avoids a source/projection import cycle.

## Commands and scopes

| Operation | Required scope | Durable meaning |
| --- | --- | --- |
| `register_contract` | `authority.extraction.manage` | Retain one immutable extractor contract and exact component versions. |
| `execute` | `authority.extraction.execute` | Commit one immutable Run Version and its output/proposals, or return exact replay. |
| `contract` | `authority.extraction.read` | Read one retained contract without raw source expression. |
| `metadata` | `authority.extraction.read` | Read one Run Version's bounded metadata. |
| `run_history` | `authority.extraction.read` | Read a bounded immutable Run history. |
| `proposals` | `authority.extraction.read_proposals` | Read retained unadmitted Proposal Envelopes. |
| `raw_output` | `authority.extraction.read_raw` | Read retained canonical structured output under the separate raw-output scope. |

The read policy requires distinct metadata, proposal and raw-output scopes, an allow-listed principal and a finite maximum result count. Every read authenticates and authorises before storage access. Raw output and source passage text are excluded from safe object representations.

## Checked schema v13

Schema version 13, migration `extraction_run_authority_v13`, adds:

```text
extractor_contracts
extraction_runs
extraction_run_passages
extraction_run_versions
extraction_run_heads
extraction_outputs
extraction_proposal_sets
extraction_proposals
extraction_proposal_evidence
```

Migration checksum:

```text
sha256:daad9b0d2693e497b8344ab344ec732cb982fb671ed0fda6f7edd6ae5ae83722
```

The complete checked schema fingerprint for this source tree is:

```text
sha256:286164e6d5831e33dd23085fd0708d23703a4c8001489020b1034c564e9feafa
```

The migration is forward-only from v12, preserves all predecessor authority and rolls back atomically if any v13 statement or history check fails. A database with a newer version, missing migration, wrong name/checksum, incomplete table set or different fingerprint fails closed.

All historical records are immutable. The only mutable extraction table is the guarded `extraction_run_heads` projection, which can advance by one exact predecessor version and cannot move after a terminal outcome.

## Extractor contract

An `ExtractorContractRequest` binds exact versions and contract digests for:

```text
framework
model placeholder
prompt
structured-output schema
repository code
normalisation
policy
execution profile
producer kind
```

The only constructible execution profile is `FIXTURE_REPLAY_ONLY`, and the only accepted producer is the exact repository-owned `DeterministicFixtureExtractor`. The contract contains no credential-bearing field. A changed framework, model placeholder, prompt, schema, code, normalisation or policy creates different semantics and cannot reuse an earlier contract identity.

The current fixture contract deliberately names a model placeholder while performing no model call. This preserves the final versioned interface without pretending the real Graphiti/model runtime is approved or qualified.

## Exact input binding

Every Run binds:

- exact Source Definition and current Source Definition Version;
- exact Source Item, Source Revision and Discovery Representation;
- one or more governed-object Admission identities;
- exact hydration Access Decision and hydration-policy contract digest;
- principal, authority domain, purpose, object class, allowed use, security and retention scopes;
- exact byte offset, byte length, blob digest, text digest and language; and
- stable passage identities used by proposal evidence ranges.

The deterministic fixture lane accepts only complete governed-object passages. The ephemeral text supplied to the producer must match the admitted blob digest exactly. SQLite retains the binding and digests, not duplicate source expression.

Before producer execution and again before commit, the authority revalidates current source version, source lifecycle, execution boundary, Admission state, Rights Decision, validity period, Access Decision, blob lifecycle, integrity state and tombstone state. Exact replay and all downstream reads perform the same current-use check, so replay cannot bypass later rights revocation, expiry, source-version change or deletion.

A pending deletion in `REQUESTED` state remains inspectable and usable while the governed blob is still active. `TOMBSTONED` or `PHYSICALLY_REMOVED` state blocks replay and downstream use while preserving historical Run records.

## Run identity, versions and outcomes

`ExtractionRunId` identifies one stable semantic intent: exact extractor contract, input binding and budget. The deterministic fixture case is versioned inside the extractor policy contract rather than supplied as caller-controlled Run input. `ExtractionRunVersionId` identifies one immutable attempt.

Version rules:

1. version 1 has no predecessor;
2. every later version names the exact current predecessor;
3. version numbers are contiguous;
4. stable Run semantics cannot change across versions;
5. only a retryable or partial head may advance; and
6. `SUCCESS`, `BLOCKING_FAILURE` and `INVALID_OUTPUT` are terminal.

Supported outcomes are:

| Outcome | Meaning | Output | Proposals |
| --- | --- | --- | --- |
| `SUCCESS` | Complete approved structured output. | Valid, retained | One non-empty retained set |
| `PARTIAL` | Honest bounded partial extraction. | Valid, retained | Retained partial set |
| `RETRYABLE_FAILURE` | No authoritative output; a later exact version may retry. Unexpected producer exceptions are reduced to the allow-listed `PRODUCER_INTERNAL_ERROR` code without retaining exception text. | None | None |
| `BLOCKING_FAILURE` | Terminal contract or policy failure, including a deterministic producer contract that is not one of the approved repository scenarios. | None | None |
| `INVALID_OUTPUT` | Malformed or out-of-contract output retained for diagnosis. | Invalid, retained | None |

Times remain distinct: producer start, producer end and authoritative recording time. Integer usage fields record elapsed milliseconds, input/output bytes, proposal/evidence counts, request/response token placeholders and cost microunits. Boolean, float, negative, excessive or budget-breaking values fail closed.

## Structured output validation

`newsroom.extraction.output_schema` owns the approved Draft 2020-12 JSON Schema and its canonical digest. The store independently validates producer output after preflight and before any extraction authority commit.

For a valid result, the canonical structured output must:

- conform exactly to the closed schema;
- contain no additional property;
- identify the exact contract-bound fixture case and schema version;
- contain the exact bilingual entity/equivalence/relation values represented by the Proposal Drafts; and
- remain within the fixed output and proposal budgets.

The boundary does not trust the producer's validation marker. Malformed or proposal-inconsistent output claimed as `VALID` is normalised into an immutable `INVALID_OUTPUT` Run Version: the canonical bytes are retained as `INVALID`, the failure code is `OUTPUT_SCHEMA_INVALID`, and no Proposal Set exists. Output claimed as `INVALID` that actually conforms exactly to the schema and proposals is instead retained as a terminal `BLOCKING_FAILURE`, because the producer contract is inconsistent. An incompatible output-schema or fixture-policy contract is likewise recorded as a proposal-free blocking failure. Store-level identity, chronology or lineage violations still roll back the complete transaction.

## Persist-before-admission ordering

One successful or partial execution uses one SQLite transaction and commits in this order:

```text
ledger event
stable Extraction Run (first version only)
Run Passage bindings (first version only)
immutable Run Version
retained structured Output
Proposal Set
Proposal Envelopes
Proposal Evidence ranges
current Run head
```

Foreign keys and insertion guards prevent a Proposal Set without a valid retained Output, a Proposal without its exact Set/Output/Run lineage, or Evidence without its exact retained Proposal and Passage. No entity-resolution or relation-admission command exists in 4A, so no later decision can reference an output that was not durably retained first.

## Proposal envelope semantics

A Proposal Envelope records:

```text
stable envelope and local identities
Run, Run Version, Output and Proposal Set
proposal kind
subject and optional object placeholders
optional closed predicate hint
confidence in integer basis points or explicit absence
sorted uncertainty and rationale codes
producer contract digest
one or more exact passage evidence ranges
retained time and canonical digest
```

The deterministic bilingual complete fixture emits:

1. one English entity mention;
2. one Hong Kong Traditional Chinese entity mention;
3. one bilingual possible-equivalence proposal with `REQUIRES_EXPLICIT_RESOLUTION`; and
4. one `SUPERSEDES` relation proposal with `REQUIRES_RELATION_ADMISSION`.

These are untrusted local placeholders. They allocate no Canonical Entity, merge no identity, admit no relation and write no Neo4j state.

## Replay, collision and competing writers

Exact replay is resolved by the command service before producer invocation. It returns the originally retained Contract, Run Version, Output, Proposal Set and Proposal identities. The producer is not called again.

The authority rejects:

- one idempotency key rebound to different canonical bytes or identity;
- one immutable ID reused by another command;
- equivalent Contract semantics under a second Contract ID;
- equivalent stable Run semantics under a second Run ID;
- a later Run Version with changed stable semantics;
- a stale, skipped or wrong predecessor; and
- a retry after a terminal head.

SQLite uniqueness, one writer lock, deterministic semantic digests and exact retained lookup make competing writers converge or fail closed. They never create a second authority database or silently coalesce different bytes.

## Startup integrity and diagnosis

Startup rederives and checks:

- migration history and complete schema fingerprint;
- command/event/audit coverage and aggregate identity;
- canonical bytes and digests for every contract, run, version, output, set, proposal and evidence record;
- normalized columns against canonical values;
- stable Run budget and creation-event lineage;
- exact source/object/hydration passage lineage;
- contiguous version chains, chronology and guarded current head;
- output outcome, validation, schema contract and retained-time consistency;
- proposal count, producer contract, output/run/version lineage and retained time;
- sorted uncertainty/rationale encodings;
- complete evidence ordinals, passage membership, byte bounds and evidence digests; and
- complete extraction-domain event-to-record coverage.

Trigger-bypassing raw-SQL mutation, deletion, orphaning, rehashing, chronology inversion or head drift must prevent reopen. Startup does not require historic inputs to remain currently usable; current rights and tombstones are checked when a caller attempts replay or downstream use.

For diagnosis, inspect through typed reads in this order:

```text
Contract
Run metadata and immutable history
Output validation and schema contract
Proposal Set and Proposal Envelopes
Passage/evidence identities and digests
source/object authority through their own facades
ledger/audit records through existing authority inspection
```

Do not log raw structured output, source passage text, credentials or arbitrary producer exception text. Retained failures use allow-listed reason codes only; unexpected producer exception messages are neither persisted nor exposed through representations or typed reads.

## Security boundary

Increment 4A authority modules import no Graphiti package, model-provider SDK, network client, Neo4j driver or arbitrary Cypher surface. Source text that resembles instructions, credentials, tools, graph mutations or policy changes remains untrusted fixture data and cannot alter the producer, schema, egress, budgets, commands or authority.

The repository-owned producer performs no network access, filesystem discovery, subprocess, model, embedding, Graphiti or graph operation. Any non-exact producer implementation is rejected at system construction.

## Stop, rollback and incident response

To stop Increment 4A, stop issuing contract registration and execution commands. There is no live worker, scheduler, external request, provider credential or workspace to disable.

Before schema v13 opens a database, rollback is branch deletion or an ordinary reviewed source revert. After v13 has opened a database:

- do not downgrade `PRAGMA user_version` or migration history;
- do not delete or rewrite Runs, Outputs or Proposals;
- keep the ledger and governed objects as authority;
- fix forward with a checked migration if the retained contract must change; and
- keep every real Graphiti/model lane disabled unless a separate owner decision is recorded.

An incident involving malformed or proposal-inconsistent output is contained by retaining an `INVALID_OUTPUT` version with no proposals. A producer that falsely marks exact conforming output as invalid, or uses an unapproved deterministic contract, is recorded as a proposal-free `BLOCKING_FAILURE`. An unexpected producer exception is recorded as a proposal-free `RETRYABLE_FAILURE` with only `PRODUCER_INTERNAL_ERROR`; its exception text is discarded. An incident involving rights or deletion is contained by current-use denial; history remains available subject to the governing lawful-retention policy.

## Explicit exclusions and next boundary

Increment 4A does not include:

```text
real Graphiti, model or embedding execution
live source access, search, schedules, credentials or external spend
Canonical Entity, Alias or resolution decisions
relation admission, assertions or governed relation projection
an isolated Graphiti proposal workspace
actual-Neo4j Increment 4 proof
Candidate or Evidence Intake authority
publication, production activation or public effect
legacy links, mutable events, clusters or identifier import
```

Issue #226 / Increment 4B remains blocked until issue #225 is merged to `main`, closed with exact-head evidence, and the Extraction Run, retained-output, proposal, rights and replay contracts are stable. This operations document does not authorise 4B or any real runtime.
