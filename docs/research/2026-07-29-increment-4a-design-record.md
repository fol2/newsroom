# Increment 4A Extraction Run authority design record

**Status:** Active implementation design  
**Issue:** #225  
**Parent:** #144  
**Authorised base:** `main@d03441ef2fa26b5dc83f65d1797abf2b381d8f1a`  
**Runtime boundary:** repository-owned deterministic fixture extraction and approved retained replay only

## Purpose

Increment 4A introduces the first durable extraction authority above the stable Increment 3 Source Revision and Discovery Representation contracts. It records exactly what was permitted as input, the versioned extractor contract, every immutable execution version and outcome, the retained structured output, and generic untrusted proposal envelopes.

A successful extractor run grants no entity, relation, Candidate, evidence, projection, publication or production authority. Every retained proposal remains `PROPOSED`.

## Public package and authority boundary

The typed domain package is `newsroom.extraction`. It contains:

- opaque Extraction Contract, Run, Run Version, Output, Proposal Set and Proposal identities;
- exact source, revision, representation, governed-object admission and hydration bindings;
- finite execution budget and usage contracts using bounded integers rather than floating point;
- complete, partial, retryable-failure, blocking-failure and invalid-output outcomes;
- canonical structured output validation;
- generic proposal envelopes with exact passage provenance, local subject/object placeholders, confidence basis points and explicit uncertainty codes;
- a deterministic bilingual fixture extractor through the final proposal-producer protocol; and
- traceability, exclusions and deferred runtime decisions.

The authenticated public facade is opened by `open_governed_extraction_authority_system`. The private SQLite store is the only writer. It extends the existing ledger rather than introducing another database or mutable side channel.

## Durable records and ordering

Checked schema version 13 adds immutable tables for:

1. extractor contracts;
2. stable extraction runs;
3. exact run input passages;
4. immutable run versions/outcomes;
5. retained structured outputs;
6. proposal sets;
7. proposal envelopes; and
8. proposal-to-passage evidence links.

One execution command commits one ledger event and, in this exact order inside the same SQLite transaction, the stable run (on first version), input bindings, immutable run version, retained output, proposal set and proposal envelopes. Proposal foreign keys cannot resolve until the output and set exist. No admission surface exists in this unit.

Invalid structured output may be retained for traceability, but it creates no Proposal Set or Proposal authority. Failed executions create an immutable run version with no output unless bounded diagnostic output was explicitly produced and retained.

## Identity, replay and versioning

- An `ExtractionRunId` identifies one exact input/contract/budget semantic intent.
- Each execution is an immutable `ExtractionRunVersionId` with a contiguous version number and exact predecessor.
- A successful or blocking terminal version cannot be silently retried under the same run.
- Exact command replay returns the original Run, Version, Output, Proposal Set and Proposal identities without duplicate rows.
- Reusing an identifier for different canonical bytes, reusing an idempotency key for different semantics, or creating the same semantic run under a second Run identity fails closed.
- Changing framework, model placeholder, prompt, output schema, code, normalisation or policy identity creates a different extractor-contract digest and cannot reuse the earlier Run authority.

## Source, rights and hydration binding

Every Run binds all of the following:

- Source Definition and exact Source Definition Version;
- Source Item and exact Source Revision;
- exact Discovery Representation;
- one or more governed-object Admission identities;
- exact hydration Access Decision and Hydration Policy contract digests;
- full governed-object byte ranges and blob/text digests; and
- language and passage identities.

The initial deterministic lane permits only complete governed-object fixture passages, so the passage text digest must equal the admitted blob digest. This lets the commit guard verify exact bytes from the supplied immutable text without retaining duplicate source expression in SQLite.

Before first commit and before any exact replay/read that could be used downstream, the store revalidates current admission state, rights validity, blob lifecycle, deletion/tombstone state, access-decision principal/domain/purpose, and exact source/revision/representation lineage. Rights revocation, expiry, deletion or source-policy mismatch therefore blocks later use and cannot be bypassed by idempotent replay.

## Retained output and proposal contract

The deterministic fixture lane retains bounded canonical JSON bytes inline. The output record binds the declared output-schema contract and records `VALID` or `INVALID` validation state. A later real lane may require governed-object output storage, but that is not authorised here.

A Proposal Envelope retains:

- Proposal and local deterministic identities;
- exact Run Version, Output and Proposal Set;
- proposal kind;
- subject and optional object placeholders as untrusted local values;
- optional allow-listed predicate hint;
- integer confidence basis points or explicit absence;
- sorted uncertainty and rationale codes;
- exact passage IDs, evidence byte ranges and evidence text digests; and
- canonical provenance and producer digests.

These values are proposal metadata only. They cannot allocate Canonical Entity identity, admit a relation, merge/split identities, create a Candidate, or write Neo4j.

## Deterministic fixture producer

`DeterministicFixtureExtractor` implements the same typed `ProposalProducer` protocol reserved for later private adapters. It accepts only `FIXTURE_REPLAY_ONLY`, exact repository-owned English and Hong Kong Traditional Chinese fixture digests, and the fixed schema/producer contract. It performs no network, filesystem discovery, subprocess, model, embedding, Graphiti, credential or graph operation.

Fixture output is deterministic over the canonical invocation. Failure scenarios are repository-owned typed scenarios; callers cannot inject arbitrary exception text, policy, tools, egress or cost values.

## Security and read policy

- Commands require explicit write scopes through the existing authentication and authorization ledger.
- Metadata, proposal and raw-output reads use separate policy-owned scopes and bounded limits.
- Raw structured bytes are excluded from dataclass representation and are never returned by metadata reads.
- Producer failures retain only allow-listed reason codes and bounded redacted detail.
- No credential-bearing field exists in the public extraction contract.
- Import/API guards reject Graphiti, model-provider SDKs, arbitrary Cypher and governed graph-writer surfaces.

## Startup integrity

Startup rederives canonical bytes and digests for every Increment 4A record; verifies command/event coverage, immutable identity, source/object/hydration lineage, contiguous Run versions, temporal chronology, output/proposal counts, proposal evidence coverage, and migration history/fingerprint. Raw-SQL mutation, orphaning, chronology inversion or policy-contract drift fails reopen.

Current rights are not rewritten into historical records. Startup preserves historical traceability while public replay/use rechecks current policy and tombstones.

## Explicit exclusions

- real Graphiti, model or embedding execution;
- provider, source or graph credentials;
- live source access, browser collection, search, schedules or recurring work;
- external spend, shadow, canary or production activation;
- Canonical Entity allocation or entity resolution decisions (4B);
- relation admission/assertions or governed relation projection (4C);
- Graphiti proposal workspace integration (4D);
- actual-Neo4j bilingual end-to-end proof (4E);
- Candidate, Evidence Intake, publication or public effect; and
- legacy link/event/cluster import or dual-write.

## Rollback

Stop invoking the extraction facade and revert schema/code before any later unit depends on it. SQLite remains authoritative and append-only; rollback never deletes committed Runs, outputs or proposals. No Neo4j or external workspace state is created by 4A.
