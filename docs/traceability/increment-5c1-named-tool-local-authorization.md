# Increment 5C1 traceability — named-tool local authorization substrate

## Delivery status

This inventory records **pre-canonical support preparation** for issue #321. It
is not completion evidence. Increment 5C1 remains blocked by Increment 5B / #251
and must be reconstructed over exact post-5B `main` before canonical review and
merge.

The prepared files deliver only strict local named-tool request and
authorization mechanics. They call no retrieval branch and produce no retrieval
result, authority hydration, collision truth, source-impact result, complete
Retrieval Context, Candidate, relation, operational state, publication, or
public effect.

## Requirement-to-evidence map

| Requirement | Prepared implementation evidence | Focused verification evidence |
|---|---|---|
| Closed six-tool identity and purpose taxonomy | `ToolIdentity`, `ToolPurpose`, immutable `TOOL_PURPOSE_BY_IDENTITY` | `test_closed_inventory_has_exactly_six_tools_and_six_purposes`, immutable-map test |
| One strict request class per tool | six frozen request records and immutable exact request-type map | six-tool round-trip matrix and subclass rejection |
| Exact common call envelope | `NamedToolCall` canonical value and call digest | every-tool round trip, purpose/schema mismatch, temporal and identity tests |
| Exact request-derived scope | per-request `scope_tokens` and equality gate | six-tool resource-scope matrix, missing and extra scope rejection |
| Fixed result, byte, timeout, graph, fan-out, and window bounds | repository constants and strict integer checks | bound-widening, non-integer, graph-shape, and date-window tests |
| EN-GB, ZH-Hant-HK, and mixed requests | closed locale set | accepted and rejected locale matrices |
| No raw query or write surface | exact-key decoding and full-text query guard | Lucene field/operator/wildcard/grouping and Cypher/write-like rejection |
| No arbitrary vector/index/predicate/response schema | exact nested request keys | arbitrary vector/index, graph predicate, tool selector, and response-schema tests |
| Content cannot select tools or widen scope | tool/purpose/request-class binding plus exact scope equality | content-selector and extra-scope tests |
| Already-authenticated caller binding | `AuthenticatedPrincipalProof` | actor mismatch, future proof, expired proof, typed time tests |
| Exact repository-owned grants | `ToolAuthorizationGrant` and `NamedToolAuthorizer` | policy, scope, missing, disabled/current, ambiguous, future, expired, and mixed-window tests |
| Closed decision semantics | `ToolAuthorizationOutcome`, `ToolAuthorizationReason` and allowed-pair validation | authorised, policy-blocked, stale, malformed, and contradictory pair tests |
| Deterministic complete receipt identity | UUIDv5 over every canonical evidence field | deterministic receipt, field-tamper, semantic-order, and round-trip tests |
| Immutable non-authoritative replay | `NamedToolAuthorizationJournal` | first writer, concurrency, idempotency conflict, row/byte/time tamper, update/delete tests |
| Zero external/provider/model/embedding calls and spend | fixed receipt counters and no client import | zero-counter, no-execution claim, and import-boundary tests |
| No authority creation or branch execution | receipt schema contains no results/context/Candidate/authority fields | `test_no_named_tool_authorization_can_claim_execution_or_authority` |
| Operations and rollback | `docs/operations/increment-5c1-named-tool-local-authorization.md` | documentation/source review before canonical merge |

## Applicable accepted inventory

The prepared substrate is intended to support the local mechanics portion of:

- `GRAG-033`;
- `GRAG-034`;
- `GRAG-035`; and
- `TRI-022`.

Those requirements are not marked complete by this support branch. Completion
requires one clean post-5B product commit, the complete deterministic repository
suite, all permanent exact-head workflows, a current substantive review with
zero P1/P2 findings, zero unresolved review threads, and merge to `main`.

## Exact prepared identity

- policy: `increment5-named-tool-local-auth-v1`;
- profile: `increment5-named-tool-local-auth-profile-v1`;
- contract: `sha256:cc153d9a850d9e3bf524ee6dec6285c716f89ee488c5e8c162030b03df8fd177`;
- fixed result limit: `8`;
- fixed timeout: `5000` ms;
- fixed byte budget: `262144`;
- fixed graph depth: `2`;
- fixed graph fan-out: `32`;
- fixed date window: `31` days.

The contract digest covers the policy/profile identities, tool and purpose
inventories, authentication methods, outcomes, reasons, exact lookup kinds,
strict per-tool request keys, fixed bounds, local/read-only status, and zero-call
counters.

## Non-delivery statements

This atom does not deliver:

- execution of exact, full-text, vector, or admitted-graph retrieval;
- collision/authority hydration or source/revision impact reads;
- cross-branch calls, fusion, raw-score comparison, or dependency-root
  deduplication;
- complete Retrieval Context or Candidate admission;
- identity, fact, rights, relationship, or authority creation;
- provider/model execution, credentials, egress, external calls, or spend;
- Evidence Intake, publication, production activation, or public effect; or
- any `DOPS-*` requirement.

`DOPS-026` and `DOPS-067` remain explicitly deferred to Increment 5E / #254.
Local parser and authorization success cannot be used as evidence for those
complete operational and credential/egress controls.

## Canonical completion evidence still required

Before issue #321 can close, the final product must retain:

- one clean commit over exact post-5B `main`;
- focused 5C1 tests with zero required skips;
- the complete deterministic repository suite;
- CI, Authority A2a/A2b, Projection B1, authenticated Neo4j, and signed SDLC
  workflows on the exact reviewed head;
- current substantive review with zero unresolved P1/P2 findings;
- zero unresolved review threads; and
- exact merge commit and tree identities on `main`.

An `AUTHORIZED` local receipt proves only that a strict call passed the local
mechanics gate. It is never branch-completion, no-match, authority, operational,
or production evidence.
