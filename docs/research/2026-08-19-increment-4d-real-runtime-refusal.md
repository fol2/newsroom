# Increment 4D real-runtime refusal surface and owner packet

**Date:** 2026-08-19  
**Ticket:** [What is the exact Increment 4D real-runtime refusal surface and owner packet this beta must satisfy?](https://github.com/fol2/newsroom/issues/691)  
**Parent:** [Wayfinder map — Private unpublished GraphRAG editorial beta](https://github.com/fol2/newsroom/issues/690)  
**Method:** primary sources only (operations doc, typed adapter, authority store, migrations, GRAG-020, 4D/4E tests). No flag flip. No implementation.

## Question

What is the exact Increment 4D real-runtime refusal surface and owner packet this private unpublished GraphRAG editorial beta must satisfy before any real Graphiti, model, or embedding call?

## Refusal surface

A real call is `GraphitiRuntimeMode.REAL_GRAPHITI`. Construction, persistence, and execution each refuse independently. Completing the typed packet is not execution authority.

| Layer | Symbol | What it refuses |
| --- | --- | --- |
| Closed flag | `newsroom.graphiti_adapter.models:REAL_GRAPHITI_RUNTIME_ENABLED` | Hardcoded `False`. Tests pin the literal. |
| Execution gate | `GraphitiAdapterConfiguration.require_execution_authorized` | If mode is `REAL_GRAPHITI` and the flag is false, raises `GraphitiRuntimeNotAuthorized` (`"real Graphiti/model execution remains disabled and unqualified"`). Fake and replay skip this raise. |
| Configuration constructor | `GraphitiAdapterConfiguration.__post_init__` real branch | Real mode requires `execution_profile` in `{EVALUATION, PRODUCTION}` only; no fixture case; a complete `RealGraphitiRuntimeAuthority`; workspace `egress_policy=APPROVED_PROVIDER_ONLY` and `credential_class=PROPOSAL_WORKSPACE_ONLY`. Other profiles raise `GraphitiAdapterContractError` (`"real Graphiti requires evaluation or production profile"`). There is no private-beta / unpublished-beta profile in `GraphitiExecutionProfile`. |
| Fake / replay constructors | same `__post_init__` | Fake is qualification + fixture, no real authority, deny-all workspace. Replay is replay profile, no fixture, no real authority, deny-all workspace. Real authority on those modes is a contract error. |
| Authority execute path | `GovernedGraphitiAdapterBoundary` (else branch after fake/replay) | Calls `require_execution_authorized()`, then `raise AssertionError("unreachable real Graphiti execution path")`. There is no real Graphiti adapter class wired. |
| Persist configuration | `_graphiti_adapter_store_commit` | If stored mode is `REAL_GRAPHITI`, calls `require_execution_authorized()` before commit. |
| Re-read / attempt validation | `_graphiti_adapter_store_common` | Calls `configuration.require_execution_authorized()` on the reconstituted configuration. |
| Fake and replay adapters | `DeterministicFakeGraphitiAdapter`, `ApprovedReplayGraphitiAdapter` | Both call `require_execution_authorized()`; with current modes this is a no-op unless a real-mode configuration is smuggled in. |
| SQLite CHECK | `graphiti_adapter_configurations` | Real rows must be `EVALUATION` or `PRODUCTION`, `fixture_case IS NULL`, `real_runtime_authority_digest IS NOT NULL`. |
| SQLite trigger | `graphiti_configuration_workspace_policy_guard` | Real inserts must bind `APPROVED_PROVIDER_ONLY` + `PROPOSAL_WORKSPACE_ONLY`. Fake/replay must bind `DENY_ALL` + `NONE`. |
| Traceability | GRPROD-015 / GRPROD-016 rows | Evaluation/production validation rejects fake, replay, missing, or unapproved runtime. Real integration remains `DISABLED_AND_UNQUALIFIED`. |

`GraphitiRuntimeNotAuthorized` is a `PermissionError`. Missing packet or wrong profile is `GraphitiAdapterContractError` at construct time, before the flag is consulted.

## Typed `RealGraphitiRuntimeAuthority` fields

All required; each digest field is a SHA-256 digest; the three `*_release` fields are tokens:

- `authority_decision_digest`
- `framework_release`
- `model_release`
- `embedding_release`
- `destination_contract_digest`
- `data_processing_terms_digest`
- `prompt_contract_digest`
- `output_schema_contract_digest`
- `permitted_expression_digest`
- `rights_privacy_retention_digest`
- `workspace_security_digest`
- `egress_credential_digest`
- `budget_digest`
- `evaluation_plan_digest`
- `rollback_digest`

A structurally complete instance still cannot execute while the flag is `False`.

The same configuration also binds `VersionedExtractionComponent` values for framework, model, embedding, prompt, output schema, code, normalisation, temporal policy, and adapter policy. Caller text cannot replace them.

## Owner packet in the 4D operations doc

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

Approval or merge of issue #228 is not that decision. Creating map #690 is not that decision.

The typed class is a digest/token envelope of that packet. It does not enumerate timeout, retry, partial, ambiguous-effect, provider-change, or retained-raw-output rules as distinct fields; those remain owner-packet items that a later decision must bind into one of the digests (or extend the type).

## Execution-profile constraint

`GraphitiExecutionProfile` is closed: `QUALIFICATION`, `REPLAY`, `EVALUATION`, `PRODUCTION`.

- Qualification ↔ deterministic fake only.
- Replay ↔ approved replay only.
- Real Graphiti ↔ evaluation or production only.

Private unpublished beta is not a profile. Running real Graphiti under this beta therefore requires a later decision: treat the beta as evaluation, treat it as production, add a new profile (type + CHECK + constructor change), or refuse real Graphiti until a later increment. This note records the constraint; it does not choose.

## `REAL_GRAPHITI_RUNTIME_ENABLED` current value

Hardcoded `False` at `newsroom/graphiti_adapter/models.py` line 68. Live import on this host is `False`. Tests:

- `newsroom/tests/test_graphiti_adapter_4d_traceability.py` asserts `REAL_GRAPHITI_RUNTIME_ENABLED is False` and that the operations doc contains the phrase `REAL_GRAPHITI_RUNTIME_ENABLED = False`.
- `newsroom/tests/test_graphiti_adapter_4d_contracts.py` builds a complete evaluation real configuration and still expects `GraphitiRuntimeNotAuthorized`.
- `newsroom/tests/test_increment4e_traceability.py` asserts the flag remains `False` after 4E (actual Neo4j projection is not real Graphiti).

A reviewed code change that sets the flag true is still insufficient: the execute path raises `AssertionError("unreachable real Graphiti execution path")` and there is no Graphiti package in the repository boundary.

## GRAG-020

**GRAG-020 — Extractor is proposal-only.** Graphiti or another extractor MAY create proposals but MUST NOT write authoritative editorial relations or governed graph state directly.

4D traceability records this as `IMPLEMENTED_PROPOSAL_ONLY`. Satisfying the owner packet would still leave Graphiti as a proposal producer, not a governed-graph writer.

## What this ticket does not authorise

- Flipping `REAL_GRAPHITI_RUNTIME_ENABLED`.
- Binding exact Graphiti / chat-model / embedding / prompt / schema releases (blocked grilling ticket on this map).
- Spend, Keychain class, or egress allow-list.
- A private-beta execution profile.
- Wiring a real Graphiti executor past the `AssertionError` unreachable path.
- Installing the `graphiti` package, starting Neo4j, or live provider calls.
- Increment 11 / 11R, AUTO_PUBLISH, public TargetOperation, production store, or First I/O Gate Record mint.
- Entity resolution, relation admission, Candidate, Evidence Intake, or publication authority (4D exclusions).

## Citations

1. Ticket: <https://github.com/fol2/newsroom/issues/691>
2. Operations packet and stop boundary: `docs/operations/increment-4d-graphiti-proposal-adapter.md` (runtime modes/profiles; “Separate real-execution decision packet”; stop boundary).
3. Flag, packet type, constructor, execution gate: `newsroom/graphiti_adapter/models.py` (`REAL_GRAPHITI_RUNTIME_ENABLED`, `RealGraphitiRuntimeAuthority`, `GraphitiAdapterConfiguration.__post_init__`, `require_execution_authorized`).
4. Closed enums and error type: `newsroom/graphiti_adapter/types.py` (`GraphitiRuntimeMode`, `GraphitiExecutionProfile`, `GraphitiEgressPolicy`, `GraphitiCredentialClass`, `GraphitiRuntimeNotAuthorized`).
5. Unreachable real executor: `newsroom/authority/_graphiti_adapter_boundary.py` (fake/replay dispatch then `require_execution_authorized` + `AssertionError`).
6. Persist/re-read gates: `newsroom/authority/_graphiti_adapter_store_commit.py`; `newsroom/authority/_graphiti_adapter_store_common.py`.
7. SQLite CHECK and workspace-policy trigger: `newsroom/authority/graphiti_adapter_migrations.py`.
8. GRAG-020: `docs/specs/editorial-automation/governed-graphrag-and-knowledge-projection.md`.
9. GRPROD-015 / GRPROD-016 implementation status: `newsroom/graphiti_adapter/traceability.py`; spec text in `docs/specs/editorial-automation/graphrag-native-production-deployment.md`.
10. Tests pinning the flag and the evaluation-packet-still-refused case: `newsroom/tests/test_graphiti_adapter_4d_traceability.py`, `newsroom/tests/test_graphiti_adapter_4d_contracts.py`, `newsroom/tests/test_increment4e_traceability.py`.
11. 4E runtime boundary (actual Neo4j ≠ real Graphiti): `docs/operations/increment-4e-bilingual-actual-neo4j-proof.md`.
12. 4D exclusions / deferred owner packet: `newsroom/graphiti_adapter/traceability.py` `INCREMENT_4D_EXCLUSIONS`, `INCREMENT_4D_DEFERRED`.
