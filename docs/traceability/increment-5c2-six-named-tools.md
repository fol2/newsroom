# Increment 5C2 traceability — six bounded named read-only tools

## Delivery boundary

5C2 completes the tool-local implementation under parent Increment 5C/#252. It
binds the accepted 5C1 request and authorization substrate to four stable 5B
retrievers, two fixed relational authority ports and one exact six-route
dispatcher.

The complete 5C ownership set remains exactly:

`GRAG-033`, `GRAG-034`.

`GRAG-035` and `TRI-022` remain owned by the composed Retrieval Context boundary
in 5D/#253. 5C2 creates no cross-tool hybrid result, factual hydration pack,
Candidate effect, downstream Watch/Hold decision or operational admission.

## Exact tool inventory

| Tool identity | Route | Fixed implementation |
|---|---|---|
| `EXACT_AUTHORITY_LOOKUP` | branch | typed adapter to `SQLiteExactRetriever` |
| `BOUNDED_FULL_TEXT_RETRIEVAL` | branch | typed adapter to `FullTextRetriever` and owned Neo4j read port |
| `BOUNDED_FIXED_POINT_VECTOR_RETRIEVAL` | branch | typed adapter to `VectorFixtureRetriever` |
| `BOUNDED_ADMITTED_GRAPH_TRAVERSAL` | branch | typed adapter to `AdmittedGraphRetriever` |
| `CURRENT_COLLISION_AND_AUTHORITY_HYDRATION_LOOKUP` | authority | fixed read-only collision/object/passage metadata port |
| `BOUNDED_SOURCE_REVISION_IMPACT_LOOKUP` | authority | fixed read-only source/revision lineage port |

The closed `NAMED_TOOL_ROUTES` and request-type inventories must equal
`NamedToolId` exactly. There is no generic route and no content-selected backend.

## Requirement-to-evidence map

| Accepted requirement | Delivery evidence | Verification evidence |
|---|---|---|
| `GRAG-033` purpose-specific bounded read tools | six strict request schemas, local grant gate, four branch adapters, two authority adapters and exact dispatcher | six-tool route/inventory, authorization-first, bounds, outcome, replay and integration tests |
| `GRAG-033` fixed graph controls | admitted-graph adapter binds reviewed relation contract, depth, fan-out, window, profile and generation | graph translation, stale/unavailable and actual-Neo4j tests |
| `GRAG-033` fixed full-text controls | typed bilingual request, 65-candidate source scan, authoritative source filtering and eight-result bound | lower-ranked in-scope match, scan overflow, result overflow, query-envelope and actual-Neo4j regressions |
| `GRAG-033` trust and provenance | exact upstream request/receipt, profile, generation, component, watermark, rights and provenance identities | attribution mismatch, rights/currentness, tamper and restart tests |
| `GRAG-033` temporal cutoff | source, revision, representation and occurrence visibility closes at query-valid time; future or late-recorded successors cannot alter historical supersession state | future-observation, late-recording, future-lineage and receipt self-consistency regressions |
| `GRAG-033` truthful outcomes | normalized complete, incomplete, blocked, stale and unavailable dispatch receipt | no-match-only-after-complete matrix and failure mapping tests |
| `GRAG-034` no general write Cypher | no Cypher field in requests; graph adapter exposes one typed read; no write credential or mutation method | injection/extra-field, route-selection, source inspection and actual-service tests |
| `GRAG-034` no unrestricted relational mutation | SQLite authority ports use fixed statements, `mode=ro`, `query_only`, write-denying authorizer and one read snapshot | write-attempt, schema compilation, immutable database and source-inspection tests |
| Internal audit evidence separated from caller payload | execution/dispatch journals retain raw canonical upstream bytes outside the typed response outcome | low-response-bound, replay, raw-byte tamper and journal-schema tests |
| No operational or downstream authority | all call/spend counters zero, `authority_effect=NONE`, no qualification or activation authority | claim-rejection and forbidden-surface tests |

## Core implementation evidence

- `newsroom/increment5/named_tool_authorization.py` — accepted 5C1 local
  authorization and immutable authorization receipt;
- `newsroom/increment5/named_tool_branch_execution.py` — branch execution
  kernel and audit journal;
- `newsroom/increment5/named_tool_branch_adapters.py` — four typed 5B adapters;
- `newsroom/increment5/named_tool_authority_execution.py` — authority execution
  kernel and audit journal;
- `newsroom/increment5/named_tool_authority_adapters.py` — two fixed SQLite
  authority ports;
- `newsroom/increment5/named_tool_dispatch.py` — exact six-route normalized
  dispatcher and journal; and
- the corresponding `test_increment5c2_*` suites plus affected 5B and actual
  Neo4j regressions.

## Evidence identities

Every successful or failed invocation binds:

- exact typed request and envelope digest;
- exact 5C1 authorization decision and receipt digest;
- branch, authority and dispatch registry digests;
- route and port identity;
- translated upstream request and canonical upstream receipt digest;
- branch or authority profile, generation and component identities;
- authority watermark where applicable;
- query-valid and serving times;
- result, timeout and response bounds; and
- normalized outcome and reason.

The immutable journals retain canonical dispatch, child execution and raw
upstream receipt bytes separately. Their presence is audit evidence only and
does not expand the caller payload or grant factual-use authority.

## Non-delivery boundary

5C2 does not deliver:

- `GRAG-035` composed graph/hybrid response metadata;
- `TRI-022` complete request-level Retrieval Context and explanation;
- exact-first cross-tool orchestration or reciprocal-rank fusion;
- authoritative dependency-root deduplication;
- factual object or passage hydration;
- Hypothesis or Candidate creation, admission, merge or suppression;
- provider/model calls, live-source access or spending;
- publication, canary or production activation; or
- complete `DOPS-*` credential, egress, recovery or Operational Admission.

Those responsibilities remain with 5D/#253 and Increment 6/#146, while
complete operational admission remains Increment 8/#148 according to the
accepted closed-world ownership map.

## Completion evidence

The 5C2 child can close only after one exact final head has:

- focused request, adapter, authority, dispatcher and failure-path tests passing;
- complete deterministic CI passing;
- affected Authority and actual-Neo4j lanes passing;
- source-integrity and exact changed-file inventory evidence;
- one substantive exact-head review with zero unresolved P1/material-P2
  findings;
- zero unresolved review threads; and
- product-only squash merge with exact commit/tree evidence.

Parent #252 remains open after the child merge for one aggregate Tier-M gate on
one exact `main` head. That parent gate is not duplicated on every internal 5C
commit.
