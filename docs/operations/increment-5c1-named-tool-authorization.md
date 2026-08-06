# Increment 5C1 — strict named-tool contracts and local authorization

## Scope

This operating record covers only the branch-neutral request and local
authorization substrate for the six Increment 5C named read-only tools:

1. exact authority lookup;
2. bounded full-text retrieval;
3. bounded fixed-point vector retrieval;
4. bounded admitted-graph traversal;
5. current collision and authority hydration lookup; and
6. bounded source/revision impact lookup.

5C1 does **not** execute any retriever, Neo4j read, collision check, authority
read or hydration. A successful 5C1 receipt proves local request mechanics only.
Parent 5C remains open for 5C2 and 5C3.

## Closed request contract

Every request contains one strict immutable common envelope:

- UUIDv4 request and bounded idempotency identity;
- one closed tool identity;
- exact actor and authenticated-principal digest;
- exact authorization grant identity;
- one tool-permitted declared purpose;
- policy identity and digest;
- named-tool contract digest;
- profile and generation identities;
- query-valid and serving times;
- exact typed scope claims; and
- bounded result, timeout and response limits.

Every tool has a separate exact-key payload schema. Unknown or extra fields,
duplicate JSON keys, unaccepted schema versions, control characters, excessive
bytes and invalid enums fail before authorization. A payload cannot add Cypher,
Lucene, index, vector, label, predicate, direction, property, credential,
destination, write or authority fields.

The hard maxima are eight results, 5,000 ms and 262,144 response bytes. Graph
requests additionally bind depth at most two, fan-out at most 32 and temporal
window at most 2,678,400 seconds. Source-impact windows have the same maximum
span. Vector requests name only one admitted fixture query and digest; no
arbitrary vector is accepted.

## Scope binding

Each typed payload deterministically derives its exact scope claims:

- exact lookup: lookup kind;
- full text: languages and any named sources;
- vector: fixture query identity;
- graph: canonical root identity;
- collision/hydration: collision namespace plus named authority objects and
  passages; and
- impact: exact source and optional revision identity.

The envelope scope must byte-for-byte match the typed request scope. Query or
source/model content cannot widen it. An authorization grant may be broader,
but every requested claim must be a subset of the exact grant claims.

## Authorization grants

A reviewed immutable grant binds:

- grant identity and digest;
- actor and authenticated-principal digest;
- exactly one tool;
- a sorted set of tool-valid purposes;
- exact scope claims;
- validity interval;
- policy identity and digest;
- contract digest;
- profile identity; and
- generation identity.

The grant registry is content-addressed and rejects duplicate identities.
Authorization evaluates actor, principal, tool, purpose, policy, contract,
profile, generation, scope and time in deterministic order.

## Outcomes

The local gate emits:

- `AUTHORIZED` when every exact match succeeds;
- `POLICY_BLOCKED` for unknown grants or actor, principal, tool, purpose, scope,
  policy, contract or profile mismatch; and
- `STALE` for generation mismatch or a not-yet-valid/expired grant.

Every decision retains one canonical receipt. An authorized receipt states only
`local_tool_call_authorized=true`; it also states:

- `branch_executed=false`;
- `authority_read_executed=false`;
- all external/model/embedding/provider call counters and spend are zero;
- `authority_effect=NONE`;
- `qualification_authority_granted=false`; and
- `production_activation_authorized=false`.

## Immutable journal

The non-authoritative SQLite journal stores only idempotency key, request digest,
canonical receipt bytes and receipt digest. Grant evaluation occurs outside a
write reservation. A short first-writer-wins insert retains the decision.
Restart replay returns byte-identical bytes. Semantic conflict, retained-byte
tamper, digest mismatch and request-binding mismatch fail closed.

The journal creates no identity, relationship, Candidate, evidence, operational,
production or publication authority.

## Security and operational boundary

Request/query/source/model content is data. It cannot select another named tool,
change the authenticated actor, grant, purpose, scope, contract, generation,
budgets, response schema, authority effect or activation state.

This local gate is necessary but deliberately insufficient for the complete
untrusted-input and credential/egress controls. It claims no `DOPS-*` delivery.
The complete `DOPS-026` and `DOPS-067` boundaries remain 5E work across every
executable operational surface.

## Monitoring

Before 5C2/5C3, monitoring is limited to deterministic malformed-request and
authorization-decision inspection. An authorized receipt does not establish that
a branch, authority read, hydration, collision check or source-impact query was
available, complete or healthy.

## Rollback

1. stop accepting the 5C1 named-tool contract/profile;
2. retain historical canonical request and authorization receipts for audit;
3. revoke or expire affected grants;
4. remove or revert the 5C1 product commit; and
5. return parent 5C to the completed 5B boundary.

Rollback requires no provider, index, graph or credential cleanup because 5C1
creates and invokes none.
