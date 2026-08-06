# Increment 5C1 — named-tool local authorization substrate

## Status and delivery boundary

This record describes **pre-canonical support preparation** for Increment 5C1 /
issue #321. The work remains blocked by completion of parent predecessor
Increment 5B / issue #251. It must not be represented as merged, activated, or
complete until it is reconstructed as one clean product commit over the exact
post-5B `main`, passes the required repository evidence, and is reviewed and
merged through the canonical PR.

The substrate performs only local request validation and authorization. It does
not call the exact, full-text, vector, admitted-graph, collision/hydration, or
source-impact implementations. It creates no Retrieval Context, Candidate,
relationship, identity, fact, authority, operational state, publication, or
public effect.

Fixed identities for this prepared contract are:

- policy: `increment5-named-tool-local-auth-v1`;
- profile: `increment5-named-tool-local-auth-profile-v1`;
- contract: `sha256:cc153d9a850d9e3bf524ee6dec6285c716f89ee488c5e8c162030b03df8fd177`.

## Closed tool inventory

Only these six identities exist:

1. `EXACT_AUTHORITY_LOOKUP`;
2. `BOUNDED_FULL_TEXT_RETRIEVAL`;
3. `BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL`;
4. `BOUNDED_ADMITTED_GRAPH_TRAVERSAL`;
5. `COLLISION_AUTHORITY_HYDRATION_LOOKUP`; and
6. `SOURCE_REVISION_IMPACT_LOOKUP`.

Each identity has exactly one fixed purpose and exactly one request class. A
subclass, another request type, an unknown tool, a mismatched purpose, an extra
field, a missing field, or a changed schema version fails before authorization.
The tool-to-purpose and tool-to-request maps are immutable.

## Common call envelope

Every valid call is bound by canonical bytes to:

- UUIDv4 request identity and bounded idempotency key;
- exact tool and purpose;
- actor identity;
- an already authenticated principal proof, including issuer, method, proof
  digest, policy digest, verified time, and expiry;
- the exact request-derived scope set;
- policy, contract, profile, and generation identities;
- query-valid and serving times; and
- one strict typed request.

The call digest covers the complete envelope. A payload that decodes only after
semantic normalization—for example, an unsorted scope array—is malformed rather
than silently rewritten into a different canonical call.

## Request and scope bounds

Every request fixes:

- result limit: `8`;
- response-byte budget: `262144`;
- timeout: `5000` ms.

Additional fixed bounds are:

- admitted-graph direction: `BOTH`;
- graph depth: `2`;
- graph fan-out: `32`;
- graph temporal window: `31` days;
- source-impact and full-text windows: at most `31` days and never after the
  call's query-valid time; and
- locale: `en-GB`, `zh-Hant-HK`, or `mixed` only.

The exact request-derived scope set is retained in the call and cannot be
widened by caller content. Resource scopes bind, where applicable, the exact
lookup kind and authority scope, vector fixture query, graph root, collision and
requested authority identities, and source/revision identity. Full-text content
is deliberately not converted into authorization syntax; only its fixed tool
and locale scopes are available.

## Injection and write boundary

No request contains a raw or generated Cypher surface, caller Lucene syntax,
arbitrary vector, index, label, predicate, property, direction, depth, fan-out,
window, write session, credential, provider, model, or response-schema selector.

The full-text request rejects field selectors, Boolean/query operators,
wildcards, grouping constructs, escaping constructs, and write-like terms. Any
unknown nested request field—including an attempted tool selector, arbitrary
vector, index, predicate, or response schema—makes the complete payload
malformed.

Source, model, query, and retrieved content cannot select another tool, alter
purpose, add scope, change budgets, or modify the response schema.

## Local authorization decision

Repository-owned grants are exact immutable records bound to:

- actor;
- tool;
- purpose;
- scope set;
- policy and profile;
- validity window; and
- enabled state.

Authorization first verifies actor/proof binding, proof policy, and proof time.
It then requires one and only one current exact grant whose scopes cover the
call's exact request-derived scopes. Missing, wrong-policy, stale, insufficient,
or ambiguous grants fail closed.

The only outcomes are:

- `AUTHORIZED`;
- `POLICY_BLOCKED`;
- `STALE`; and
- `MALFORMED`.

Outcome and reason combinations are closed and validated. A contradictory
retained receipt—for example, `STALE / SCOPE_NOT_GRANTED`—is invalid even if its
JSON and digest are otherwise well formed.

Authorization success proves only local mechanics. It does not prove that any
retrieval branch is available, complete, current, authorised for production, or
truthful about no-match.

## Receipt integrity

The authorization receipt binds every retained evidence field, including:

- original payload and decoded call digests;
- outcome and reason;
- tool, purpose, actor, policy, contract, profile, and generation;
- exact requested scopes;
- accepted grant identity and digest, when authorised;
- completion time; and
- fixed zero-call and zero-spend counters.

The deterministic UUIDv5 receipt identity is derived from the canonical digest
of all those fields. Canonical decoding reserializes the typed receipt and
requires byte equality, preventing semantically equivalent but noncanonical
arrays or field representations from being retained.

For every outcome the counters remain:

- external calls: `0`;
- provider calls: `0`;
- model calls: `0`;
- embedding calls: `0`;
- provider spend: `0`.

## Immutable journal and replay

The local SQLite journal is non-authoritative and first-writer-wins. It retains:

- actor and idempotency identities;
- canonical call digest and bytes;
- canonical receipt digest and bytes; and
- receipt completion time.

Initial lookup is read-only. Receipt production occurs before the short write
reservation. Concurrent producers converge on the byte-identical first retained
receipt. Reuse of an idempotency key for another call, changed row identity,
changed call bytes, changed receipt bytes, changed receipt digest, changed call
binding, or changed recorded time fails closed. Update and delete triggers keep
retained rows immutable.

The journal does not allocate authority and must not be queried as a source of
identity, rights, facts, current collision state, retained source bytes, or
retrieval truth.

## Monitoring and incident interpretation

Until canonical 5C1 delivery, monitoring is limited to local focused-test and
source inspection. After delivery, the useful signals are malformed call rate,
policy-blocked reason, stale proof/grant reason, ambiguous grant detection,
idempotency conflicts, and journal-integrity failures.

An `AUTHORIZED` receipt is not a branch execution receipt. It must never be used
as no-match evidence, authority hydration evidence, complete Retrieval Context,
Candidate admission, operational admission, or production readiness.

## Rollback

Rollback is repository-local:

1. stop constructing 5C named-tool call envelopes;
2. retain historical canonical calls and receipts for audit where required;
3. revert or remove the 5C1 product commit;
4. remove disposable local journal databases only after retention obligations
   are satisfied; and
5. return parent 5C to the completed Increment 5B boundary.

No provider, credential, external service, model, vector index, network route,
or spend requires cleanup because this substrate creates none.

## Explicit deferrals

This work claims **no `DOPS-*` delivery**. In particular:

- `DOPS-026`, the complete operational policy/tool/egress/budget/authority
  boundary against source and model content, remains deferred to 5E / #254; and
- `DOPS-067`, least-privileged provider/source credentials, storage, redaction,
  scopes, and approved network destinations, remains deferred to 5E / #254.
