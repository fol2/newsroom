# Local agentic GraphRAG database options

**Status:** Reviewed
**Type:** Research
**Owner:** Product owner
**Canonical language:** English (declared exception for engineering research)
**Translation status:** None
**As of:** 2026-07-15
**Last reviewed:** 2026-07-15
**Related specs or plans:** [`../specs/editorial-automation/story-eligibility-and-evidence.md`](../specs/editorial-automation/story-eligibility-and-evidence.md), [`../specs/editorial-automation/publication-lifecycle-and-audit.md`](../specs/editorial-automation/publication-lifecycle-and-audit.md), [`../plans/2026-07-15-001-integrated-newsroom-architecture.md`](../plans/2026-07-15-001-integrated-newsroom-architecture.md)
**Related architecture review:** [`2026-07-15-database-architecture.md`](2026-07-15-database-architecture.md)
**Related decisions:** [`../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md`](../adr/0001-authoritative-editorial-ledger-and-rebuildable-projections.md) (`Proposed`), [`../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md`](../adr/0002-sqlite-ledger-in-the-integrated-target-architecture.md) (`Proposed`)
**Source policy:** Current first-party documentation, source repositories and licences only; all external sources accessed 2026-07-15.

> This is non-normative reference material. It does not create an implementation requirement unless an accepted spec explicitly adopts one. It is not legal advice; licence conclusions require review against the intended commercial deployment.

## Executive finding

The Newsroom should not choose between a “vector database” and an “agentic graph database”. Those terms describe different layers:

1. A **graph database** is a storage and query engine for nodes, relationships and their properties. [Neo4j's current definition](https://neo4j.com/docs/getting-started/graph-database/) is representative.
2. A **knowledge graph** is the governed domain model and data — entities, claims, events, sources and meaningful relationships. It can be stored in a graph database, but the model and the engine are not the same thing. [Neo4j explicitly distinguishes them](https://neo4j.com/blog/knowledge-graph/knowledge-graph-vs-graph-database/).
3. **GraphRAG** is a retrieval and context-construction method that uses graph structure. Microsoft describes its implementation as extracting a knowledge graph, building a community hierarchy and summaries, and then using several query modes. [Microsoft GraphRAG overview](https://microsoft.github.io/graphrag/).
4. **Agentic RAG** is orchestration: an LLM plans retrieval steps and chooses tools or retrievers. Neo4j's current `ToolsRetriever`, for example, lets an LLM select and execute one or more retrieval tools. [Neo4j GraphRAG RAG guide](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html#tools-retriever)

There is therefore no useful product category called an “agentic graph database” to select. A defensible target is:

> **A governed temporal Newsroom knowledge graph, stored locally in a graph-capable engine, exposed through bounded read-only retrieval tools, with Hermes orchestrating hybrid full-text, vector, exact and graph retrieval.**

Vector retrieval is not obsolete. Every current first-party GraphRAG stack reviewed still uses it alongside other retrieval modes:

- Microsoft GraphRAG extracts entities, relationships and claims, detects communities, embeds text, and writes embeddings to a configured vector store. [Indexing overview](https://microsoft.github.io/graphrag/index/overview/)
- Neo4j GraphRAG offers vector, vector-plus-Cypher, full-text-plus-vector hybrid, text-to-Cypher and tool-selecting retrievers. [Retriever list](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html#retriever-configuration)
- Graphiti combines semantic similarity, BM25 and graph-distance or breadth-first traversal. [Graphiti search documentation](https://help.getzep.com/graphiti/working-with-data/searching)
- LlamaIndex's Property Graph defaults include synonym and vector-context retrieval, and it can combine several sub-retrievers. [Property Graph retrieval guide](https://developers.llamaindex.ai/python/framework/module_guides/indexing/lpg_index_guide/#retrieval-and-querying)

The architecture should treat graph, vector and full-text data as **rebuildable retrieval projections**, not as independent publication truth. This boundary is drafted in the related ADR and remains proposed until the product owner explicitly accepts it.

## Newsroom-specific requirement

The existing Newsroom already has a short-lived relational discovery model, with `links`, `events`, clustering decisions and a deterministic token/anchor candidate retriever. Its pool has a default 48-hour link TTL and a seven-day hard event TTL, so it is not a durable knowledge archive. See [`../../newsroom/news_pool_db.py`](../../newsroom/news_pool_db.py) and [`../../newsroom/event_manager.py`](../../newsroom/event_manager.py).

The target specs create a stronger requirement than generic “chat with documents” RAG:

- every central claim must link to exact supporting evidence; [`EVID-040`–`EVID-046`](../specs/editorial-automation/story-eligibility-and-evidence.md#claim-to-evidence-contract);
- related stories require the same event, case, policy, bill or formal process, rather than shared keywords; [`LIFE-033`](../specs/editorial-automation/publication-lifecycle-and-audit.md#developments-and-related-stories);
- automated relationships require identity plus evidence or a deterministic rule; [`LIFE-034`](../specs/editorial-automation/publication-lifecycle-and-audit.md#developments-and-related-stories); and
- public versions are immutable and traceable; [`LIFE-001`–`LIFE-004`](../specs/editorial-automation/publication-lifecycle-and-audit.md#story-identity-and-versions).

Those constraints favour a knowledge graph, particularly for multi-hop questions such as:

- which later decision changed this policy;
- which claims depend on the same original source;
- which stories concern the same court case despite different wording;
- which source revisions invalidate downstream claims; and
- which article version and publication bundle used a particular claim.

They do **not** justify allowing an LLM to create authoritative relationships directly.

## Proposed logical architecture for evaluation

This is a logical shape, not a database decision:

```text
source capture -> governed source object + SourceObservation in ledger
                                      |
                                      v
                         Graphiti extraction workspace
                                      |
                         persist exact RelationProposal
                         and extraction provenance in ledger
                                      |
                         persist RelationAdmissionDecision
                                      |
            idempotent projector emits ledger-governed observations
                     and ADMITTED derived assertions only
                                      |
                governed graph + lexical/vector index projection
                                      |
                           named read-only retrieval tools
                                      |
                              Hermes agent planner
                                      |
                    research/draft output or a new proposal
```

Keep the long-term relational editorial ledger as the authority for identities, observations, proposals, admission decisions, story versions and publication records. The governed source-object store is authoritative only for the exact retained bytes and their content hashes; it does not make a source claim true. This is a new durable editorial store, not the short-lived `news_pool.sqlite3` discovery pool.

Graphiti must not write directly into the governed retrieval graph. If the framework requires a graph database during extraction, it must use a logically isolated, disposable proposal workspace. Every immutable proposal, including a rejected proposal, is persisted with its exact extraction output and provenance before a separate admission decision. Only an idempotent projector credential may expose ledger-governed source observations and admitted derived assertions in the governed projection; unadmitted proposals remain excluded. This avoids distributed dual-write truth and makes the graph disposable and rebuildable without rerunning a stochastic extractor.

### Suggested graph model

Candidate record and node types:

- `SourceDocument`, `SourceSnapshot`, `SourcePassage`, `Claim`, `Event`, `Story`, `StoryVersion`, `SurfacePayload` and `PublicationBundle`;
- `Person`, `Organisation`, `Place`, `Policy`, `Bill`, `Case` and `Incident`; and
- `ExtractionRun`, `RelationProposal`, `RelationAssertion` and `RelationAdmissionDecision` for provenance and governance.

Direct structural relationships may represent ledger-proven structure:

- `HAS_SNAPSHOT`, `HAS_PASSAGE`, `HAS_VERSION`, `CONTAINS_PAYLOAD` and `DERIVED_FROM`.

Relationships with editorial meaning must be reified as `RelationProposal` or admitted `RelationAssertion` records rather than ordinary edges whose safety depends on every query remembering a status filter. Their predicate may be `MENTIONS`, `REPORTS`, `SUPPORTS`, `DISPUTES`, `CONTRADICTS`, `ABOUT_EVENT`, `DEVELOPMENT_OF`, `SAME_PROCESS_AS` or `SUPERSEDES`. An assertion links to its subject, object, exact supporting passages, extraction run and admission decision. Entity resolution and entity merging follow the same proposal/admission path.

Reader-facing related-story links must be admitted ledger records included in the immutable publication bundle. They must not be produced at request time from a live graph query.

Every derived node or edge should carry, or point to:

- canonical source and passage IDs;
- source/object content hashes;
- source publication and revision times;
- retrieval and revision-observation times;
- asserted validity start and end times;
- ledger recording, admission and admission-revocation times;
- extraction model, prompt, policy and code versions;
- model confidence, immutable proposal identity and the separate admission-decision outcome; and
- the deterministic rule or decision record that admitted it.

Large source bodies and assets should remain in the content-addressed local object store. The graph should hold identifiers, short derived text, rights/retention state and hashes rather than becoming another uncontrolled copy of protected source expression.

### Retrieval should remain hybrid and bounded

An agentic retrieval turn should be able to:

1. classify the question and choose one or more read-only retrieval tools;
2. use exact identifiers, entity aliases, dates and full-text terms where precision is available;
3. use embeddings to seed semantically similar passages, claims or events when the wording differs;
4. traverse only allow-listed relationship types to a configured depth and time window;
5. fetch exact source passages and decision records from the authoritative ledger/object store;
6. rerank and deduplicate the context; and
7. return a size-limited context pack with provenance for every fact.

Generated Cypher must not have a general write credential. LlamaIndex itself warns that arbitrary text-to-Cypher execution needs read-only roles or sandboxing, and offers constrained Cypher templates as a safer alternative. [LlamaIndex Property Graph guide](https://developers.llamaindex.ai/python/framework/module_guides/indexing/lpg_index_guide/#texttocypherretriever)

Hermes should receive named tools such as `find_related_story_candidates`, `get_event_timeline`, `find_source_revision_impact` and `get_story_provenance`, not a generic `run_cypher` capability. Every result must identify a contiguous `projected_through_ledger_seq`, the projector and ontology versions, any projection gap or dead-letter state, the query validity time and the serving time. A later sequence must not conceal an earlier failed projection event.

Proposal exploration, when explicitly enabled for research, must use a labelled trust scope. A source observation may still be malicious, stale, rights-restricted or evidentially insufficient, and an admitted relationship is not by itself a publishable evidence package. Publication validation must hydrate the exact governed evidence package from the ledger and object store.

## Database decision matrix

“No monthly licence fee” below means the reviewed distribution can be run on local hardware without buying a managed plan; it does not waive licence obligations or local hardware/operations costs.

| Candidate | Local shape and model | Retrieval fit | Licence and current status | Newsroom decision signal |
|---|---|---|---|---|
| **Neo4j Community** | Standalone property-graph server; Cypher; official Python driver. Community is limited to one standard database and a single-instance deployment. | Native full-text and vector indexes; strongest direct fit with Neo4j GraphRAG and Graphiti. | Community is GPLv3. Current operations docs list CE as fully functional for single-instance use but reserve clustering, online backup and richer security for Enterprise. [Edition matrix](https://neo4j.com/docs/operations-manual/current/introduction/) | **First POC baseline.** Highest framework fit and lowest GraphRAG integration uncertainty; accepts a Java/server process and CE operational limits without creating a production commitment. |
| **FalkorDB** | Redis-module property graph using sparse matrices; openCypher and Python client; local Docker deployment. | Full-text and vector indexes in the same engine; officially supported by Graphiti. [FalkorDB docs index](https://github.com/FalkorDB/docs/blob/main/llms.txt) | SSPLv1; active official releases, including [v4.20.1 on 2026-07-15](https://github.com/FalkorDB/FalkorDB/releases/tag/v4.20.1). [Repository and licence](https://github.com/FalkorDB/FalkorDB) | **Landscape reference.** Strong Graphiti/hybrid fit, but SSPL obligations and Redis/server operations keep it outside the initial qualification lane. |
| **Memgraph Community** | Cypher-compatible, memory-first graph database with on-disk persistence; self-hosted Community edition. | Native vector search and graph traversal; current marketing lists MAGE graph algorithms and stream connectors. [Current pricing/features](https://memgraph.com/pricing) | Source-available under a BSL additional-use grant for internal business purposes, with restrictions on distribution, DBaaS and competing uses. [Current licence text](https://github.com/memgraph/memgraph/blob/master/licenses/BSL.txt). Active [v3.11.0 release](https://github.com/memgraph/memgraph/releases/tag/v3.11.0). | **Benchmark candidate, not first integration choice.** Attractive for live/streaming and algorithm-heavy workloads; memory sizing, BSL scope and weaker direct framework fit need proof. |
| **TypeDB Community** | Strongly typed entities, relations with named roles, attributes, schema validation and TypeQL; local server and official Python driver. [Graph model](https://typedb.com/docs/use-cases/graph/) | Strong semantic constraints, but its own docs say it does not currently ship graph analytics; TypeDB 3 replaced implicit rules with explicit functions. [TypeDB 2-to-3 changes](https://typedb.com/docs/reference/typedb-2-vs-3/diff/) | Free Community edition; MPL 2.0; active [3.12.1 release](https://github.com/typedb/typedb/releases/tag/3.12.1). [Installation](https://typedb.com/docs/home/install/ce/) | **Schema-integrity challenger.** Worth revisiting if typed multi-party relations and database-enforced semantics outweigh Cypher/GraphRAG ecosystem compatibility. |
| **Apache AGE on PostgreSQL** | Apache 2.0 PostgreSQL extension combining SQL and openCypher over one transactional storage layer. [Official overview](https://age.apache.org/overview/) | Relational and graph queries can coexist; GraphRAG orchestration and hybrid vector retrieval would still need to be assembled and evaluated. | Apache top-level project; Apache 2.0; [v1.7.0 released 2026-01-21](https://age.apache.org/release-notes/). | **PostgreSQL-pivot option.** Compelling only if the canonical local ledger is moved from SQLite to PostgreSQL; otherwise it adds another server without direct framework benefit. |
| **SurrealDB** | Multi-model document/graph/vector/full-text engine; the Python SDK supports embedded in-process, persistent `surrealkv://` storage, with stated embedded feature limits. [Python embedded docs](https://surrealdb.com/docs/languages/python/concepts/embedded-databases) | Native graph edges, full-text and vector search can live in one engine. [Current data-model overview](https://surrealdb.com/docs) | Core is BSL 1.1; the licence prohibits offering the database functionality as a database service, while the current support page describes Community as free but says commercial SaaS/cloud providers need a commercial licence. [Licence](https://github.com/surrealdb/surrealdb/blob/main/LICENSE), [pricing/licensing note](https://support.surrealdb.com/en/articles/11538829-pricing-and-licensing). Active [v3.2.0 release](https://github.com/surrealdb/surrealdb/releases/tag/v3.2.0). | **Landscape reference.** Attractive all-in-one primitives, but commercial scope and less direct Graphiti support keep it outside the initial qualification lane. |
| **LadybugDB** | Embedded, disk-backed columnar property graph with Cypher, Python bindings, full-text and vector indexes. [Official repository](https://github.com/LadybugDB/ladybug) | Strong zero-server local shape and native retrieval primitives, but Graphiti's current supported-backend list does not include LadybugDB. [Graphiti repository](https://github.com/getzep/graphiti) | MIT; active [v0.18.1 release on 2026-07-10](https://github.com/LadybugDB/ladybug/releases/tag/v0.18.1). It is the active fork/successor after Kuzu was archived. [Ladybug migration/status note](https://blog.ladybugdb.com/post/ladybug-spreading-its-wings/) | **Conditional challenger.** Best operational and licence shape, but run it only if the Neo4j POC exposes a measured blocker. |

### Embedded caution: Kuzu and FalkorDBLite

Do not start new work on Kuzu. Its official repository is archived and its last release was 0.11.3 in October 2025. [Archived Kuzu repository](https://github.com/kuzudb/kuzu) Graphiti now marks Kuzu deprecated and recommends Neo4j or FalkorDB. [Graphiti backend warning](https://github.com/getzep/graphiti#installing-with-kuzu-support)

FalkorDBLite is active and Graphiti can use it, but FalkorDB's own documentation positions it for local development, prototyping, offline demos and CI, and says to move production or multi-user workloads to a full server. [FalkorDBLite documentation](https://docs.falkordb.com/operations/falkordblite/) It is suitable for a Graphiti proof of concept, not the default durable recommendation.

## GraphRAG and agentic framework matrix

| Framework | What it actually supplies | Storage coupling | Fit for this Newsroom |
|---|---|---|---|
| **Microsoft GraphRAG** | Batch/incremental pipelines that extract entities, relationships and claims, detect graph communities, generate community reports and embeddings; local, global, DRIFT and basic query modes. [Overview](https://microsoft.github.io/graphrag/), [query modes](https://microsoft.github.io/graphrag/query/overview/) | Default outputs are Parquet tables plus a configured vector store; it does **not** require a graph database. [Index outputs](https://microsoft.github.io/graphrag/index/overview/) | Useful as an evaluation/reference algorithm for corpus-wide themes. It is not the database or the Hermes agent layer, and Microsoft warns that indexing can consume substantial LLM resources. [Getting started warning](https://microsoft.github.io/graphrag/get_started/) |
| **Neo4j GraphRAG for Python** | Knowledge-graph construction plus vector, hybrid, vector-plus-Cypher, text-to-Cypher and LLM tool-selection retrieval. [RAG guide](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html) | Neo4j-first, though some retrievers can seed from an external vector store. | Best low-friction package when Neo4j is the database; `ToolsRetriever` is a useful example of agentic orchestration but should remain behind read-only tools. Active [1.18.0 release](https://github.com/neo4j/neo4j-graphrag-python/releases/tag/1.18.0). |
| **Graphiti** | Incremental temporal context/knowledge graph construction with validity windows, episode provenance and hybrid semantic/keyword/graph retrieval. [Project documentation](https://github.com/getzep/graphiti), [search](https://help.getzep.com/graphiti/working-with-data/searching) | Current supported durable backends include Neo4j, FalkorDB and Amazon Neptune; Kuzu is deprecated; FalkorDBLite is available for embedded use. | Closest off-the-shelf match to evolving news facts and provenance, but its LLM-extracted facts must remain immutable proposals until a separate Newsroom admission decision. Apache 2.0 and active [v0.29.2 release](https://github.com/getzep/graphiti/releases/tag/v0.29.2). |
| **LlamaIndex Property Graph** | Framework-level construction and retrieval orchestration; schema-aware extractors, vector-context, synonym, text-to-Cypher and templated-Cypher retrievers. [Property Graph guide](https://developers.llamaindex.ai/python/framework/module_guides/indexing/lpg_index_guide/) | Pluggable property-graph and optional vector stores; its simple in-memory store is not a Cypher graph database. | Useful for a backend-neutral evaluation harness or custom Newsroom retriever. It does not itself solve database operations, provenance policy or authoritative validation. Active MIT project with [v0.14.23 released 2026-06-24](https://github.com/run-llama/llama_index/releases/tag/v0.14.23). |

## Projection-engine qualification within one target architecture

No option should be selected from documentation alone, but implementing every candidate in parallel would test adapters before the Newsroom ontology, identity resolution, temporal semantics and admission boundary are proved. This qualification is a pre-activation workstream inside one target architecture. It does not follow a publication-only production release.

1. **Initial implementation and qualification lane: Neo4j Community + Graphiti.** This is the compatibility-first control with the strongest documented temporal and GraphRAG integration path. Graphiti is restricted to a proposal workspace; it is not the governed projector. Neo4j must pass the declared operational and commercial gates before the single production activation.
2. **Conditional challenger: LadybugDB + a thin Newsroom Adapter.** Run this only if the Neo4j POC produces a measured blocker in server footprint, backup, licence or deployment. It tests whether embedded operation is worth owning the temporal/provenance Adapter.

FalkorDB and SurrealDB remain useful landscape references but are not simultaneous implementation lanes. TypeDB should receive a separate schema-modelling spike only if database-enforced relation roles and cardinalities become the primary criterion. Apache AGE should be reconsidered only alongside an explicit relational-ledger move to PostgreSQL. Memgraph is relevant only if streaming or graph algorithms become a demonstrated bottleneck.

## Integrated workstreams and dependency gates

GraphRAG must not define reader-facing publication correctness, but its identity, event and projection contracts must exist from the same first durable schema:

1. obtain explicit owner acceptance of the authority/projection ADR;
2. define the one canonical identity, temporal, trust and ordered-event contract used by publication, serving and knowledge projections;
3. implement publication/serving and governed graph workstreams in parallel against that contract; and
4. run the integrated publication, reconciliation, Neo4j/Graphiti and Hermes acceptance proof before one production activation.

PR [#75](https://github.com/fol2/newsroom/pull/75) provides shadow-only package, audit, authority, pause and recording-intent primitives. It does not supply the final graph, serving or publication architecture and must not be merged unchanged as an intermediate base. Approved algorithms and tests may be ported to the final contract after their residual authority/replay findings are resolved; its experimental schema creates no production migration obligation.

The three initial graph use cases are:

1. `same_event` and `development_of` related-story precision;
2. source-revision impact on claims, story versions and surface payloads; and
3. long-running case or policy timeline retrieval.

Generic document chat and broad community-summary generation are not first-round success criteria.

## Proof-of-concept decision gates

Build one small, versioned evaluation corpus and ontology in the first POC. Reuse it unchanged for a conditional challenger; do not compare vendor demonstrations. The corpus should include multilingual aliases, one long-running policy, one court case, corrections, contradictory reports, copied wire stories and unrelated articles sharing keywords.

Measure:

- precision and recall for `same_event`, `development_of`, `same_process_as`, `supports`, `contradicts` and `supersedes`;
- provenance completeness down to the exact source passage;
- temporal correctness before and after a correction or source revision;
- hybrid retrieval quality against full-text-only, vector-only and graph-only ablations;
- incremental ingest cost and the ability to rebuild from the SQLite ledger and object store;
- p50/p95 query latency, resident memory, disk growth and backup/restore time on the intended Mac mini;
- failure recovery after a killed write, corrupt/replaced index and interrupted rebuild;
- contiguous projection-watermark behaviour when one earlier event fails and a later event is available;
- Python/ARM64 packaging, upgrade and export portability;
- read-only agent isolation, query budgets and resistance to generated-query abuse;
- exact licence approval for a paid consumer news product;
- scoped rights-expiry and privacy-deletion purge followed by a clean rebuild; and
- degraded publication and correction behaviour with the graph unavailable.

The decisive experiment is not “can the LLM answer a graph question?” It is:

> Can a bounded, read-only Hermes retrieval plan recover the correct connected evidence, including time and provenance, while the entire graph remains reproducible from authoritative local records?

## Decision boundaries retained from this research

- Do not describe vector retrieval as outdated; treat it as one recall-oriented index in a hybrid system.
- Do not call a database agentic. Agents plan and use database-backed tools.
- Do not let similarity, graph proximity or an LLM-extracted edge become reader-facing truth without validation and provenance.
- Do not make the graph the sole backup. Back up authoritative objects and the editorial ledger; prove graph rebuilds separately.
- Do not rerun Graphiti or another stochastic extractor during projection replay; replay retained extraction output and admission decisions.
- Do not let a later projected sequence conceal an earlier gap or dead letter.
- Do not let a rebuild resurrect source material removed under rights, privacy or retention policy.
- Do not select Kuzu for new work.
- Do not embed arbitrary agent-generated Cypher in a write-capable production path.
- Do not let a research framework become the publication authority.
