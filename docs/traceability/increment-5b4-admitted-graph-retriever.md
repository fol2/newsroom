# Increment 5B4 traceability — bounded admitted-graph retriever

## Delivery boundary

Increment 5B4 supplies only the independently attributable
`ADMITTED_GRAPH` branch inside parent Increment 5B / issue #251. It does not
supply exact lookup, full-text retrieval, vector retrieval, cross-mode score
comparison, reciprocal-rank fusion, dependency-root deduplication, named tools,
authoritative hydration, complete Retrieval Context, Candidate admission,
relationship mutation, operational admission, shadow, canary, publication or
production activation.

## Requirement-to-evidence map

| Requirement | Delivery evidence | Verification evidence |
|---|---|---|
| Accepted canonical root only | `AdmittedGraphRequest` root and exact identity digest | request-shape, root identity, unknown/held root tests |
| Fixed admitted relationship allow-list | `ALLOWED_PREDICATES` and relation-contract digest | exact allow-list/digest tests and actual Neo4j filtering |
| Fixed projected node labels | `ALLOWED_NODE_LABELS` | contract and fixed-port parameter tests |
| Maximum depth two | two fixed expansion phases | complete traversal and cycle/depth tests |
| Maximum fan-out 32 | per-frontier grouped edge check | thirty-third edge sentinel test |
| Temporal window 2,678,400 seconds | exact lower-bound construction and relation validation | old-observation exclusion and actual Neo4j temporal filter |
| Eight results plus ninth overflow | deterministic endpoint ordering and overflow guard | ninth-result sentinel test |
| Cumulative 5,000 ms including lock wait | retriever deadline plus Neo4j adapter lock/Query timeout | pre-port, port and lock-wait timeout tests |
| 262,144-byte response bound | canonical receipt size guard | receipt round-trip/size and fixed request-bound tests |
| Exact active complete generation | typed authority view and projection generation checks | inactive/incomplete and generation-crossing tests |
| Exact graph/profile/relation contracts | request and authority preflight | request/authority drift matrices |
| Contiguous watermark, zero gaps/dead letters, freshness | authority preflight | health-state matrix and no-match guard tests |
| SQLite/governed authority remains authoritative | node/relation authority records and binding verification | missing node/relation and projection-authority mismatch tests |
| Current rights and active lifecycle | node/relation eligibility checks | rights, held and tombstone tests |
| `ADMITTED` trust only | relation trust check | proposal/unadmitted exclusion test |
| No tombstone resurrection | current authority required for every endpoint/relation | tombstone projection regression |
| Fixed read-only Neo4j port | two-method protocol and immutable repository Cypher | public-surface, no-write-clause and fixed-parameter tests |
| No arbitrary Cypher or driver capability | caller receives no query/driver/session/transaction field | request, protocol and adapter introspection tests |
| Deterministic path ordering and endpoint dedupe | path order key and best-path selection | incoming/outgoing, duplicate endpoint and ordering tests |
| Cycle/root-repeat rejection | path node identity checks | cycle and root-repeat test |
| Truthful failure/no-match semantics | typed outcomes and ordered guards | projection failure, malformed, gap and complete no-match tests |
| Immutable byte-identical replay | SQLite first-writer-wins receipt journal | replay/restart, conflict, tamper, concurrency and nested-read tests |
| Production outside SQLite write reservation | authority/Neo4j execution precedes short insert | nested same-journal retrieval test |
| Actual Neo4j proof | `Neo4jAdmittedGraphReadPort` and service fixture | `test_increment5b4_neo4j_service.py` with generation, predicate and temporal isolation |
| Zero provider/model/embedding/external work and spend | fixed receipt counters and no clients | zero-counter and authority-claim rejection tests |
| Operations and rollback | `docs/operations/increment-5b4-admitted-graph-retriever.md` | documentation/source-integrity gates |

## Exact identities

- retrieval contract: `sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c`;
- graph-query component: `sha256:98a92b1c46c08b614a0e15714a5cd071d49e916d6d2b45ead4924b194cf4525b`;
- profile: `increment5-admitted-graph-retrieval-v1`;
- policy: `increment5-admitted-graph-read-v1`;
- relation contract: canonical SHA-256 over the fixed labels, predicates,
  direction, depth, fan-out and temporal window;
- generation: canonical SHA-256 over the generation identity, profile,
  components, rights manifest, watermark and every current node/relation
  authority binding.

## Applicable accepted specification boundary

This atom provides the admitted-graph-specific part of the accepted 5B
implementation boundary under the merged 5A contract. It preserves the accepted
`GRAG-*`, applicable `GRPROD-*`, `TRI-*`, rights, security, replay, generation
and actual-service boundaries selected for parent #251.

It does **not** claim `GRAG-031` hybrid composition. It does not claim any named
tool, complete hydration or `DOPS-*` operational admission. Those remain 5C,
5D and 5E work.

## Completion evidence

Issue #308 can close only after one clean canonical product commit over the exact
post-5B3 `main` has:

- focused deterministic 5B4 tests passing;
- authenticated actual-Neo4j mandatory tests passing with zero required skips;
- the complete deterministic repository suite passing;
- all permanent workflows passing on the exact reviewed head;
- current-head substantive review with zero unresolved P1/P2 findings;
- zero unresolved review threads; and
- product-only squash merge with exact commit/tree evidence.

Parent #251 remains open until 5B1–5B4 are all merged and independently
attributable. No 5B4 evidence grants production, provider, source, model,
credential, spending, write, publication or public-effect authority.
