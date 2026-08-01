# Increment 5A production retrieval contract proposal

**Status:** Proposed — explicit owner approval required
**Owner:** Product owner
**Prepared:** 2026-08-01
**Issue:** #250
**Parent:** #145
**Implementation base:** `main@c9e31879421083e82e2538d57087d04e9b454d34`
**Decision packet:** `newsroom/increment5/data/increment5a_production_retrieval_decision_v1.json`
**Decision payload digest:** `sha256:4cc1de54a8d831358bbbe9b65c724d442401e84e3e72918df45807e140bdea56`
**Decision record digest:** `sha256:77fe5544b33a85519b8c1fba57f41fe1a68aa411eb63c64be5429dbbd28ea913`
**Contract bundle digest:** `sha256:c0976abd6c2d450f242351f2cd94b2589cac5e6a03f1a2f98bfe1acbcbc4ea8c`
**Production profile schema digest:** `sha256:2cdaa92a487ff48dd6095e1cc82af6f67362c168c557d9e6c3ecfe83e83cb647`
**Fixture replay profile schema digest:** `sha256:c7faf200a77ddb08fee48394594b85e985aecb9ad342b24cbbf6464bf38f387e`

## Decision requested

Approve the exact pending decision payload identified above as the implementation contract for Increment 5B–5E. Approval is deliberately digest-specific. Any change to the embedding model, package, model revision, vector dimension, normalisation, chunking, full-text configuration, graph bounds, fusion, deduplication, hydration, degraded outcomes, rights matrix, budgets, evaluation thresholds, rollback, or PR boundary creates a new payload digest and requires a new decision.

The checked-in packet currently grants **contract validation and non-qualifying fixture replay only**. It does not grant model loading, vector creation, protected-content processing, external calls, provider credentials, spending, live-source execution, shadow, canary, publication, or production activation. The production schema exists now so later implementation cannot substitute a fake, fixture, disabled, omitted, or incompatible component.

## Proposed exact embedding identity

The proposed production-target embedding is self-hosted and remains disabled until this exact decision is approved:

| Field | Exact value |
|---|---|
| Runtime | local process only; no external embedding API |
| Package | `sentence-transformers==5.6.0` |
| Package wheel SHA-256 | `d2075b5e687a1611005e20ab04a6846994d51adfcf39610aed066af3c0c0b81f` |
| Model | `BAAI/bge-m3` |
| Model revision | `5617a9f61b028005a4858fdac845db406aefb181` |
| Licence recorded by upstream | `MIT` |
| Dense dimensions | `1024` |
| Maximum input tokens | `8192` |
| Pooling | `CLS` |
| Normalisation | L2 normalisation enabled |
| Inference/output | `FLOAT32` / `FLOAT32` |
| Remote code | prohibited |
| Request-time download | prohibited; immutable artifact preload required |
| Credential reference | none |
| External calls and spend | zero |
| Protected content | not authorised by model selection; rights matrix still governs every datum |

Upstream evidence for the proposed identity is the exact [BAAI/bge-m3 model revision](https://huggingface.co/BAAI/bge-m3/tree/5617a9f61b028005a4858fdac845db406aefb181), its [model card](https://huggingface.co/BAAI/bge-m3), pooling and normalisation configuration in the same revision, the [FlagEmbedding repository](https://github.com/FlagOpen/FlagEmbedding), and the pinned [Sentence Transformers release](https://pypi.org/project/sentence-transformers/5.6.0/). Those sources establish the software/model identity only. They do not grant rights to submit or retain newsroom source text.

## Exact retrieval component contract

| Component | Contract | Decision |
|---|---|---|
| Embedding | `retrieval.embedding.production` | Exact self-hosted BGE-M3 identity proposed; execution disabled pending owner approval. |
| Passage | `retrieval.passage.production` | UTF-8 byte offsets; paragraph → sentence → safe UTF-8 boundaries; 3,072-byte target, 4,096-byte maximum, 384-byte maximum overlap; no cross-representation or cross-revision passage. |
| Bilingual normalisation | `retrieval.normalization.production` | NFKC search projection, LF line endings, Latin casefold, collapsed whitespace, Traditional Chinese preserved, no free transliteration or automatic Han script conversion, authority aliases only, Han bigrams; source bytes remain unchanged. |
| Full text | `retrieval.fulltext.production` | Neo4j `2026.06.0-community-trixie`, driver `6.2.0`, `fulltext-2.0`, `standard-no-stop-words`, synchronous and generation-scoped; callers cannot supply Lucene syntax. |
| Vector index | `retrieval.vector.production` | Neo4j `vector-2026.06`, 1,024 dimensions, cosine, float32, no quantisation, generation-scoped; index creation remains disabled while embedding is disabled. |
| Graph query | `retrieval.graph-query.production` | Fixed read-only queries only; maximum depth 2, fan-out 32, 31-day default window, exact ACTIVE/complete generation, zero gaps/dead letters, admitted/observed trust allow-list, no generated Cypher or write capability. |
| Fusion | `retrieval.fusion.production` | Exact, full-text, vector and admitted-graph branches; equal-weight reciprocal-rank fusion with `k=60`; reduced rational scores; fusion is never authority. |
| Deduplication | `retrieval.deduplication.production` | Deduplicate by authoritative dependency root; best hit per mode; retain branch and exclusion receipts; dependency-root lexical tie-break; maximum 12 retained candidates. |
| Hydration | `retrieval.hydration.production` | Hydrate exact permitted bytes from SQLite ledger/governed objects; recheck rights at read; projection text cannot become factual authority; missing authority is `INCOMPLETE`, denied rights are `POLICY_BLOCKED`. |
| Degraded policy | `retrieval.degraded-policy.production` | Explicit `COMPLETE`, `DEGRADED`, `INCOMPLETE`, `POLICY_BLOCKED`, `STALE`, or `UNAVAILABLE`; no silent branch fallback, no graph-free production, and no-match is valid only after complete required retrieval. |

## Named read-only tools

The accepted family is closed and exact:

1. `find_related_event_candidates`
2. `get_event_or_process_timeline`
3. `find_source_revision_impact`
4. `find_shared_origin_dependencies`
5. `find_conflicting_relation_candidates`
6. `get_candidate_provenance`

Increment 5C may implement only these purpose-specific surfaces under exact authentication, type, trust, depth, fan-out, date, result, timeout, provenance, watermark, and generation controls. No raw Cypher, arbitrary label/property selection, general index search, driver/session access, or mutation tool is approved.

## Authority and budget boundary

SQLite ledger records and governed objects remain authoritative. Neo4j graph, full-text and vector data remain rebuildable projections. Similarity, path, rank, fusion, embeddings and models can rank or explain context but cannot allocate Event Hypothesis identity, merge records, admit a relation, create a Candidate, satisfy an exact collision check, or provide factual bytes without hydration.

The 5A request budget is deliberately zero-runtime: 5,000 ms contract timeout, 8 results per branch, 12 retained candidates, 262,144 response bytes, zero external calls and zero gross external-provider cost. Later local qualification still requires an approved Operational Profile and signed Run manifest; these numbers do not authorise production traffic.

## Rights decision matrix

- Governed synthetic qualification text may be indexed and embedded locally only under a signed dataset manifest.
- Public governed source text may enter local full-text/vector projections only with current source rights and a signed rights-cleared qualification manifest.
- Repository fixture text may replay fixed-point fixture vectors, but fixture evidence can never substitute for production-vector qualification.
- Rights-restricted source text may not enter the Increment 5 v1 vector index or qualification corpus.
- Personal data, secrets and credentials may not enter the vector index or public qualification artefacts.
- Tombstoned or revoked material must be purged from graph, full-text and vector derivatives, and rebuild must prove non-resurrection.
- The self-hosted destination reduces disclosure risk but does not expand source rights, privacy authority, retention, or evaluation authority.

## Evaluation and rollback

The digest-bound Evaluation Plan is in `docs/evaluation/2026-08-01-increment-5-retrieval-evaluation-plan-v1.md`. Calibration and qualification are separate. Exact, full-text, vector, admitted-graph and hybrid paths are ablated. English, Hong Kong Traditional Chinese, mixed-language, temporal, correction/supersession, shared-origin, distractor false-merge, long-running timeline and rights purge/rebuild slices are mandatory. Zero-tolerance provenance, trust, rights, security, write-containment and false-no-match failures block the affected scope.

Material component change creates a new evaluation epoch and isolated index generation. Same-generation contract mutation is prohibited. Rollback may serve a prior generation only when its exact contracts and rights remain current; history is never rewritten; disabled-component derivatives must be purged.

## PR boundaries after approval

- **5B / #251:** typed exact, full-text, vector and graph retrievers plus the disabled self-hosted embedding seam; no model load or vector creation until the approved decision record is committed.
- **5C / #252:** the six bounded named read-only tools; no raw graph/index capability.
- **5D / #253:** immutable Retrieval Contexts, authoritative hydration, freshness and explicit degraded outcomes; no false no-match.
- **5E / #254:** pre-registered ablation, security, rights purge, fault injection and authenticated actual-Neo4j qualification for the exact approved implementation.

## Approval effect and non-effect

Approval of this exact payload authorises implementation work under issues #251–#254 and creation of a later immutable approved decision record. It does **not** activate the runtime. Shadow, canary and production remain separate owner decisions with their own operational evidence.

A suitable explicit approval statement is:

> I approve Increment 5A decision payload `sha256:4cc1de54a8d831358bbbe9b65c724d442401e84e3e72918df45807e140bdea56`, contract bundle `sha256:c0976abd6c2d450f242351f2cd94b2589cac5e6a03f1a2f98bfe1acbcbc4ea8c`, production profile schema `sha256:2cdaa92a487ff48dd6095e1cc82af6f67362c168c557d9e6c3ecfe83e83cb647`, and fixture replay schema `sha256:c7faf200a77ddb08fee48394594b85e985aecb9ad342b24cbbf6464bf38f387e` as the exact implementation and qualification contract for issues #251–#254. This approval does not authorise shadow, canary, production activation, external embedding calls, protected-content vectors, or spending.

Until that approval is recorded, issue #250 remains open, the production profile remains mechanically blocked, and #251 must not begin.
