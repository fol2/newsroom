# Increment 5B1 traceability — exact branch and receipt substrate

- **Issue:** #289
- **Parent:** #251
- **Accepted contract:** Increment 5A / PR #255
- **Implementation files:** `newsroom/increment5/retrieval_*.py`,
  `newsroom/increment5/exact_*.py`,
  `newsroom/increment5/sqlite_exact_retriever.py`,
  `newsroom/increment5/candidate_collision.py`
- **Tests:** `newsroom/tests/test_increment5b1_exact_retriever.py`

## Truthful credit

This atom earns **zero complete selected normative requirements**. The 5A
closed-world map intentionally assigns zero complete rows to 5B because four
independent branches are a mandatory partial dependency. `GRAG-031` and
`TRI-021` remain 5D/#253 work: this exact branch neither composes a hybrid nor
enforces exact-before-approximate ordering across branches.

## Partial implementation evidence

| Contract area | 5B1 evidence | Still required |
|---|---|---|
| `GRAG-030`–`GRAG-035` | typed independent exact request/hit/receipt; SQLite remains authority; lineage and dependency roots retained | full-text, vector, graph, 5D fusion/dedup/hydration and six named tools |
| `GRAG-040`–`GRAG-046` | exact Source Revision, Representation, formal process and Candidate-version seams | complete Source→Candidate composition, downstream decisions and reconciliation |
| `GRPROD-*` | fixed versions/digests/budgets, zero-call/spend, explicit unavailable/stale outcomes, no activation | actual-service qualification, complete operational controls, production/canary enforcement |
| `TRI-020`–`TRI-028` | separate exact Candidate collision receipt without score/similarity/admission | 5D request composition and 5E Candidate-admission/outage/reconciliation enforcement |
| `DEVAL-*` | deterministic fixtures suitable for later ablation/security cases | no evaluation requirement is claimed before 5E |
| `DOPS-*` | request-local bounds, immutable replay receipt and fixed read-only SQL | no operational requirement is claimed; profiles, health, security, queues, recovery and containment remain 5E |

## ADR alignment

- **ADR 0001 / 0002:** SQLite and governed objects remain authoritative;
  receipts are non-authoritative and Neo4j is not consulted by the exact lane.
- **ADR 0004:** source-native Revision/Item identity remains explicit and
  separate from semantic retrieval.
- **ADR 0005:** the branch is GraphRAG context infrastructure only; it creates no
  editorial or publication authority and does not activate production.

## Exclusions and deferrals

This atom explicitly excludes full-text index execution, fixed-point vector
execution, admitted-graph traversal, raw/generated Cypher, caller Lucene,
external embeddings/models/providers, source access, credentials, spending,
fusion, dependency-root deduplication, authoritative hydration, complete
Retrieval Context, named tools, triage, Candidate creation/admission, shadow,
canary, publication and production activation.

The parent #251 must remain open until the full-text, vector and graph atoms are
merged and all four final interfaces/receipts pass the parent completion gate.
