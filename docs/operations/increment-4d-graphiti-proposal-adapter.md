# Increment 4D isolated proposal-only Graphiti adapter operations

**Status:** implementation review unit for issue #228
**Parent:** #144
**Authorised base:** `main@b2f12922e5ec853991f95ac41bf46a977a70dc1a`
**Execution boundary:** deterministic repository-owned fake and approved replay only

Increment 4D provides a private adapter that can produce retained Extraction Run output and Proposal Envelopes, but cannot resolve entities, admit relations, write governed Neo4j state, create Candidates, start Evidence Intake, publish, or activate production.

The repository contains no Graphiti package or model-provider runtime in this boundary. `REAL_GRAPHITI_RUNTIME_ENABLED = False`. A structurally valid real-runtime configuration is still rejected until a separate owner decision binds every required framework, model, prompt, rights, destination, credential, security, budget, evaluation and rollback value.

Map #690 reviewed flip: Control Plane Graphiti may execute under EVALUATION with `REAL_GRAPHITI_RUNTIME_ENABLED = True`. Increment 4D qualification remains deterministic fake and approved replay. PRODUCTION stays closed. `graphiti-core==0.29.3` is an optional extra.

## Public boundary

Open the authority through the dedicated submodule:

```python
from newsroom.authority.graphiti_adapter_system import (
    open_governed_graphiti_adapter_authority_system,
)
```

The returned `system.graphiti` facade exposes only:

```text
register_configuration
execute_attempt
approve_replay
configuration
attempt
attempt_history
replay_source
```

It exposes no SQLite connection, capability issuer, raw output bytes, source-expression store, private graph node or relation identifiers, arbitrary SQL or Cypher, graph credential, model provider, entity decision, relation decision, Candidate, Evidence Intake or publication writer.

## Runtime modes and profiles

The closed runtime modes are:

```text
DETERMINISTIC_FAKE
APPROVED_REPLAY
REAL_GRAPHITI
```

The closed profiles are:

```text
QUALIFICATION
REPLAY
EVALUATION
PRODUCTION
```

Qualification accepts only the deterministic fake. Replay accepts only an exact approved retained replay source. Evaluation and production require a separately authorised `RealGraphitiRuntimeAuthority` and reject missing, disabled, fake, replay or incompatible runtime configuration. Even a structurally complete real authority packet cannot execute while `REAL_GRAPHITI_RUNTIME_ENABLED = False`.

The initial production target remains Neo4j Community plus Graphiti under ADR 0005, but this unit does not qualify any exact Graphiti or model release and does not make a network or provider call.

## Fixed contracts

```text
Adapter contract:
graphiti-proposal-adapter-v1

Adapter policy:
graphiti-proposal-only-policy-v1

Workspace policy contract:
graphiti-disposable-workspace-v1

Qualification workspace policy digest:
sha256:d0c8b514d053f19ffd24a19eca6ca17d8ffe6ca84347c7db7deae8c3282e1d2b

Replay workspace policy digest:
sha256:47155ae53fb798e821978b154520cfb984355f6d4696ccd5a4ea5361c94e60fc
```

Every configuration binds exact placeholders or versions for the Graphiti framework, model, embedding model, prompt, structured-output schema, adapter code, normalisation, temporal behavior, adapter policy, Extraction Run contract and workspace policy. Caller text and source content cannot replace those values.

## Commands and scopes

| Operation | Command | Required scope | Trust |
| --- | --- | --- | --- |
| Register immutable configuration | `graphiti.adapter.configuration.register` | `authority.graphiti.configuration` | `ADMITTED` configuration authority |
| Execute one proposal attempt | `graphiti.adapter.attempt.execute` | `authority.graphiti.execute` | `PROPOSED` output authority |
| Approve retained replay | `graphiti.adapter.replay.approve` | `authority.graphiti.replay.approve` | `ADMITTED` replay authority |
| Read configurations | — | `authority.graphiti.read_configuration` | Configuration only |
| Read attempts/history | — | `authority.graphiti.read_attempts` | Rights-current attempts only |
| Read replay source | — | `authority.graphiti.read_replay` | Rights-current replay authority only |

The three read scopes are distinct. Every command and read authenticates and authorises before storage access, checks authorization provenance and uses finite read limits.

Command-definition identities:

```text
graphiti.adapter.configuration.register
sha256:d47779c3373f73690a2a8ef7ea591bc6f28d770ee5f7332032c1c158b3bf8e88

graphiti.adapter.attempt.execute
sha256:95452d9f9a34a43e11226d8689ca04fd1bbe0e0c87b4e84e2135c63237c1d6df

graphiti.adapter.replay.approve
sha256:2dd48439a9f594a7b9ac07de5cda775c71aba02c113d28c103179d81ad83624d
```

## Checked schema v16

Migration `graphiti_proposal_adapter_v16` advances schema v15 to schema v16.

```text
Migration checksum:
sha256:ffd44aa70e65e7a2c69a48b3b652160ccc33285d9282c7eed202d206133ba991

Complete schema fingerprint:
sha256:b5a6d2afc78838cdeb648e7cd34b66452f2e0a0f7dab4773dd17a4cc28e3b5d8
```

Schema v16 adds:

```text
graphiti_workspace_policies
graphiti_adapter_configurations
graphiti_workspaces
graphiti_workspace_lifecycle_events
graphiti_input_manifests
graphiti_input_manifest_passages
graphiti_cleanup_receipts
graphiti_adapter_attempts
graphiti_adapter_attempt_heads
graphiti_replay_sources
graphiti_adapter_attempt_replays
```

The migration is forward-only, atomic and checked. A newer schema, wrong migration checksum, changed fixed workspace-policy seed, missing table/view/trigger, foreign-key violation or different schema fingerprint fails closed. Configuration, manifest, workspace, lifecycle, cleanup, attempt, replay and authority-event rows are immutable. The current attempt head is a checked derivative of immutable attempt history.

A governed Passage may legitimately appear in multiple immutable manifests. Passage canonical digests are therefore unique only within the owning manifest, not globally across all attempts.

## Exact hydration manifest

`GraphitiInputManifest` binds:

- adapter configuration identity and digest;
- Extraction Run and requested Run Version;
- exact extractor contract;
- current Source Definition Version;
- Source Item, Source Revision and Discovery Representation;
- every governed Passage, Admission and Access Decision;
- hydration-policy contract;
- byte offset and allowed byte count;
- blob/text digest, language and input-binding digest.

The manifest contains governed identities and digests, not a second authoritative source-text store. Execution rehydrates through the exact permitted Extraction Run input and rechecks current rights before activating a workspace.

## Disposable proposal workspace

Every attempt receives one separately namespaced workspace under an operator-selected root. The workspace contract requires:

```text
credential class: NONE
egress policy: DENY_ALL
governed graph access: false
entity/relation decision access: false
Candidate/Evidence Intake/publication access: false
directory mode: 0700
private file mode: 0600
bounded files and bytes
```

Private node and relation identifiers may exist only inside the disposable workspace. Public canonical values reject private Graphiti IDs, Neo4j IDs, Cypher, credentials, secrets, API keys and access tokens.

Every execution records activation, cleanup and an exact cleanup receipt. Cleanup verifies private files and namespace removal. A recreated supposedly cleaned workspace makes checked startup fail until the private state is removed.

## Attempt outcomes

The adapter contract has explicit outcomes:

```text
COMPLETE
PARTIAL
TIMEOUT
MALFORMED_OUTPUT
PROVIDER_REJECTED
POLICY_BLOCKED
FAILED
AMBIGUOUS_EFFECT
```

The deterministic fake exercises complete, partial, malformed, provider-rejected and ordinary failure paths. The authority converts a late completion into `TIMEOUT`, discards late output/proposals and retains an immutable retryable attempt. Policy-blocked and ambiguous-effect values are closed contract states reserved for honest future runtime handling; neither is silently converted into success.

Usage retains authority-measured elapsed time, input/output bytes, proposal and evidence counts, bounded token placeholders and cost microunits. Caller-reported timing cannot override authority timing.

## Persist-before-admission and atomic ordering

The adapter does not persist output after returning control to an admission controller. One SQLite transaction commits:

1. exact Extraction Run Version;
2. retained structured output;
3. Proposal Set and Proposal Envelopes;
4. cleanup and workspace lifecycle authority;
5. adapter attempt and current head; and
6. the ordered adapter authority event.

The Extraction Run event precedes the adapter-attempt event. A failure in adapter metadata persistence rolls back the Extraction Run output and proposals as well. This is the enforceable persist-before-admission boundary: entity and relation admission can reference only already-retained authority, and the adapter has no admission command.

## Deterministic fake

`DeterministicFakeGraphitiAdapter` uses the same final `ProposalOnlyGraphitiAdapter` interface as replay and any future real implementation. It accepts only exact repository-owned fixture bytes, writes a bounded private proposal graph, returns typed output through the Increment 4A `ProposalProducer` seam and removes the workspace before returning.

The fake cannot be selected for evaluation or production. Its purpose is deterministic contract, migration, lifecycle, rights and ordering qualification.

## Approved replay

Replay requires an explicit `graphiti.adapter.replay.approve` decision over one exact retained attempt, Run Version, Output, Proposal Set and canonical payload digest. Only complete, partial or malformed retained output is eligible.

An approved replay:

- uses the same final adapter interface;
- does not invoke the deterministic fake, Graphiti, a model or network;
- does not need private workspace recovery;
- creates a later exact Run Version when the source outcome is non-terminal;
- preserves the retained source attempt and approval event; and
- verifies output/proposal digests before returning.

The replay survives complete workspace loss because authoritative history is in SQLite and governed objects, not Graphiti private state.

## Rights, deletion and source-version change

Attempt and replay reads revalidate the exact retained Extraction Run provenance. Revoked or expired rights, tombstoned or physically removed governed bytes, changed current Source Definition Version, stale retained contract or divergent manifest block current use while immutable audit rows remain retained.

Configuration authority contains no hydrated source expression and can remain readable after source rights change. Attempt and replay surfaces raise `GraphitiAdapterRightsDenied` rather than exposing lower-level extraction or entity exceptions.

## Prompt and source-injection containment

Source and model expression is untrusted data. It cannot change adapter mode, profile, prompt contract, output schema, tools, credentials, egress or budget.

A fixture containing instructions such as `run_cypher`, credential exfiltration, network enablement, budget escalation or automatic admission is rejected unless its bytes exactly match the governed Admission and Access Decision. The rejection occurs before workspace activation and leaves no Extraction Run Version, adapter attempt, entity decision or relation decision.

## Concurrency, replay and failure atomicity

One authority writer owns the SQLite lock. A process-local command lock prevents concurrent identical requests from executing the private adapter more than once. Concurrent identical configuration, attempt and replay commands produce one durable event plus exact replay. Incompatible reuse or stale sequencing fails closed.

A timeout attempt can be replayed exactly without rerunning workspace code, then followed by a later contiguous retry. No output or proposal from the timed-out execution is retained.

## Integrity and tamper response

Checked startup reconstructs and validates:

- fixed workspace-policy seeds;
- configuration canonical bytes and exact extractor contract;
- workspace descriptor and lifecycle chronology;
- manifests and every Passage binding;
- attempt sequence, outcome, cleanup, output/proposal lineage and head;
- replay approval, eligible source, exact digest and replay binding;
- authority command/event envelopes; and
- physical workspace absence after cleanup.

SQLite triggers reject ordinary mutation. Focused tests bypass individual guards and prove checked reopen rejects manifest-passage divergence, a missing attempt head, a missing replay binding and an authority event without its typed record. A recreated private workspace also blocks reopen.

Operators must preserve a failed database and diagnose from an unchanged copy. Do not repair immutable authority rows in place.

## Recovery and rollback

### Before merge

A 4D branch can be abandoned without affecting `main`. Delete its disposable workspace and test databases. Do not copy schema-v16 databases into environments running schema-v15 code.

### After migration

Schema v16 is forward-only. Rollback means:

1. stop adapter and extraction writers;
2. retain the complete database, governed objects and cleanup evidence;
3. restore a pre-v16 backup for schema-v15 code, or keep v16 code deployed with all Graphiti adapter command scopes removed;
4. correct defects through a later migration/version, never by deleting committed v16 history; and
5. rerun checked open, the complete 4D inventory and all permanent repository gates.

### Workspace loss

Do not restore private workspace files. Verify the namespace is absent, reopen checked authority and use retained output/proposals or an explicitly approved replay. Private workspace state is never a recovery source.

### Rights or deletion incident

Remove execute/replay/read authority, preserve immutable history, complete governed deletion and verify attempt/replay reads fail closed. Workspace cleanup must still complete. Do not rewrite attempts to simulate deletion.

## Operational checks

Before enabling even deterministic qualification in a controlled environment:

- confirm schema v16, migration checksum and schema fingerprint;
- confirm all three command definitions and three distinct read scopes;
- confirm `REAL_GRAPHITI_RUNTIME_ENABLED = False` unless a later reviewed release changes it;
- confirm the selected policy is `DENY_ALL`, credential class `NONE` and the workspace root is not a symlink;
- run contract, workspace, fake/replay, authority, lifecycle, ordering, rights, concurrency, security, injection, integrity, migration and traceability tests;
- verify no Graphiti/model/provider/network/Cypher/governed-graph runtime import entered the authority boundary;
- verify zero unresolved P1/P2 findings and review threads; and
- retain exact-head CI, Authority, Projection, authenticated service and signed SDLC evidence.

## Permanent workflow hooks

Increment 4D has dedicated files in each applicable permanent focused lane:

```text
newsroom/tests/test_authority_a2a_graphiti_adapter.py
newsroom/tests/test_authority_a2b_graphiti_adapter.py
newsroom/tests/test_projection_b1_graphiti_adapter.py
```

A2a proves exact command envelopes and Extraction Run event ordering before the adapter attempt. A2b proves current attempt/replay reads recheck governed-object rights while immutable history remains. Projection B1 proves workspace and Proposal state produce no admitted entity or relation projection event.

The authenticated actual-Neo4j workflow remains a regression gate. It does not qualify real Graphiti/model execution; the complete bilingual actual-Neo4j proof belongs to Increment 4E.

## Separate real-execution decision packet

No real Graphiti/model call may occur until an owner-approved decision binds at least:

- exact Graphiti, model and embedding releases;
- destination and data-processing terms;
- prompt, system instructions and output schema;
- permitted expression, rights, privacy and retention;
- workspace topology, credentials, egress and security controls;
- token, request, rate and gross monetary budgets;
- timeout, retry, partial, ambiguous-effect and provider-change policy;
- retained raw output and replay rules;
- evaluation cases, thresholds, reviewers and early-stop rules; and
- rollback or replacement path.

Approval or merge of issue #228 is not that decision.

## Stop boundary

Issue #229 / Increment 4E must not begin until #228 is merged to `main` and closed with exact evidence. Completion of 4D does not authorise real Graphiti, model or embedding execution, production credentials, live-source access, governed graph writes, publication or public effects.
