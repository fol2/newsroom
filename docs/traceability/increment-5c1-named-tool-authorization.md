# Increment 5C1 traceability — named-tool contracts and local authorization

## Delivery boundary

5C1 is the first child atom of parent Increment 5C / #252. It delivers strict
request schemas and local caller/purpose/scope authorization mechanics for the
closed six-tool inventory. It executes no retrieval branch, collision check,
authority hydration or source-impact read and therefore cannot complete parent
5C by itself.

## Requirement-to-evidence map

| Requirement | Delivery evidence | Verification evidence |
|---|---|---|
| Closed six-tool inventory | `NamedToolId` | exact inventory test |
| Tool-permitted purpose taxonomy | `PERMITTED_PURPOSES` | invalid-purpose and inventory tests |
| Strict common call envelope | `NamedToolEnvelope` | exact-key, type, time and bound tests |
| One strict schema per tool | six typed request classes and decoder | six-schema round-trip matrix |
| Unknown/extra fields rejected | exact key sets and duplicate-key JSON hook | extra Cypher/Lucene/vector/predicate and duplicate-key tests |
| Fixed result, timeout and response maxima | repository constants and envelope checks | excessive-bound matrix |
| Fixed graph depth/fan-out/window | graph request checks | broader graph-shape tests |
| Bounded source-impact window | impact request chronology check | window and lineage tests |
| Fixture vector only | vector request identity/digest only | arbitrary-vector extra-field test |
| Payload-derived exact scope | `ToolScope` plus per-request scope equality | scope mismatch and content-widening tests |
| Immutable reviewed grant | `NamedToolAuthorizationGrant` | canonical digest/tamper tests |
| Exact actor and principal match | `NamedToolAuthorizer` | actor/principal mismatch matrix |
| Exact tool and purpose match | deterministic grant checks | tool/purpose mismatch matrix |
| Exact policy, contract, profile and generation match | deterministic grant checks | policy/contract/profile/generation matrix |
| Validity window | deterministic serving-time comparison | not-yet-valid and expired tests |
| Deterministic local outcomes | `AUTHORIZED`, `POLICY_BLOCKED`, `STALE` receipts | success, unknown-grant and mismatch tests |
| No branch/authority execution claim | fixed false receipt flags | receipt claim-rejection tests |
| No external work, spend or authority | zero counters and `authority_effect=NONE` | zero/claim-rejection tests |
| Immutable byte-identical replay | SQLite first-writer-wins journal | restart, fresh-journal, concurrency, conflict and tamper tests |
| Query/source/model content remains data | envelope/payload separation | injection-like query and scope-widening tests |
| No operational admission claim | explicit operations boundary | documentation/source-integrity tests |

## Exact identities

- contract: canonical SHA-256 over the six tool identities, purpose and language
taxonomies, per-tool purpose map and all hard bounds;
- policy: `increment5-named-read-tools-v1` plus exact reviewed policy digest;
- profile: `increment5-named-read-tools-v1`;
- grant: canonical SHA-256 over principal, tool, purposes, scope, validity,
policy, contract, profile and generation;
- registry: canonical SHA-256 over grants sorted by grant identity;
- request: canonical SHA-256 over exact envelope and typed payload;
- decision: deterministic UUIDv5 plus canonical receipt digest.

## Accepted parent requirement boundary

5C1 provides common mechanics needed by parent #252 for named read-only tools,
including strict request shape, local authenticated actor/purpose/scope checks,
hard bounds and inspectable authorization receipts. Parent delivery of
`GRAG-033` and `GRAG-034` remains incomplete until 5C2 executes all six named
tools through their reviewed branch or authority ports. `GRAG-035` and
`TRI-022` remain owned by the composed Retrieval Context boundary in 5D/#253.

5C1 claims no `DOPS-*` row. In particular, local request validation does not
satisfy the complete `DOPS-026` policy/tool/egress/budget/authority boundary or
the `DOPS-067` credential/source-access/network-destination boundary. Both
remain explicitly deferred to Increment 8/#148.

## Completion evidence

The 5C1 child issue can close only after one clean product commit over the exact
accepted post-5B `main` has:

- focused request, authorization and journal tests passing;
- the complete deterministic repository suite passing;
- source-integrity and local boundary checks passing;
- exact-head substantive review with zero unresolved P1/material-P2 findings;
- zero unresolved review threads; and
- product-only squash merge with exact commit/tree evidence.

Parent #252 remains open for #329 and one parent Tier-M aggregate gate. No
successful 5C1 receipt may be described as a completed named tool, Retrieval
Context, collision decision, hydration result, operational admission, provider
approval, production activation or public effect.
