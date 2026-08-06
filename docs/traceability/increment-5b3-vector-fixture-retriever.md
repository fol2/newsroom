# Increment 5B3 traceability — deterministic vector fixture/replay retriever

## Delivery boundary

Increment 5B3 supplies only the independently attributable `VECTOR` branch
inside parent Increment 5B / issue #251. It does not supply full-text, exact,
admitted-graph, fusion, dependency-root deduplication, named tools, hydration,
complete Retrieval Context, Candidate admission, relationship authority,
operational admission, shadow, canary, publication, or production activation.

The accepted 5A decision authorises no real model, embedding service, provider,
credential, external vector destination, or spend. Consequently, the 5B3 lane is
deterministic repository fixture/replay only.

## Requirement-to-evidence map

| Requirement | Delivery evidence | Verification evidence |
|---|---|---|
| Independently attributable vector branch | `newsroom/increment5/vector_retriever.py` typed request, authority view, hit, exclusion, and receipt contracts | `test_complete_vector_receipt_is_independently_attributable` |
| Exact 16 → 1,024 binary32 materialisation | `materialize_fixed_point_vector` | materialisation dimension, byte length, digest, zero-padding, and round-to-nearest-even tests |
| Exact 4,096-byte vector identity | SHA-256 over canonical big-endian bytes | `test_every_document_vector_is_content_addressed` |
| Repository-owned admitted queries only | content-addressed catalog and request query digest | unknown query, query-digest mismatch, arbitrary-vector, and injection tests |
| Exact rational cosine ordering | `rank_fixture_documents` and `ExactCosineProof` | identical/inverse ordering, stable tie, and branch-local rational-proof tests |
| Eight-result plus ninth overflow sentinel | fixed request bound and explicit overflow outcome | `test_ninth_result_is_an_overflow_failure_not_silent_truncation` |
| 5,000 ms cumulative timeout | monotonic deadline and typed timeout receipt | timeout-before-authority and timeout-after-authority tests |
| 262,144-byte response bound | fixed request and receipt-size guard | request-bound and canonical-receipt-size tests |
| Current generation, profile, component, and catalog compatibility | `VectorAuthorityView` and retriever preflight | inactive/incomplete, request drift, and authority drift matrices |
| Contiguous watermark, zero gaps, zero dead letters, freshness | typed preflight with explicit non-complete outcomes | watermark/gap/dead-letter and stale-view tests |
| Current passage authority binding | document, dependency root, revision, rights, provenance, lifecycle binding | missing, document-integrity, rights-integrity, and generation-digest tests |
| Rights and lifecycle exclusion | current rights plus active-only lifecycle | non-current rights, held/proposal/revoked, tombstone, and mixed exclusion tests |
| Temporal eligibility | query-valid time checked against passage window | complete no-match and gap-before-no-match tests |
| No silent no-match during failure | outcome ordering and `NO_MATCH` guard | authority, gap, stale, and temporal tests |
| Immutable restart replay | SQLite first-writer-wins canonical journal | byte-identical replay/restart, concurrency, conflict, tamper, and nested retrieval tests |
| Production outside SQLite write reservation | authority provider executes before `BEGIN IMMEDIATE` | nested same-journal retrieval test |
| Zero provider/model/embedding/external calls and spend | fixed zero counters and no live client import | zero-counter, no-live-claim, import-boundary, and external-construction tests |
| No authority creation | replay-only receipt flags and receipt-journal schema | activation-claim rejection and journal-schema tests |
| Operations and rollback | `docs/operations/increment-5b3-vector-fixture-retriever.md` | repository documentation/source-integrity gates |

## Exact identities

- retrieval contract: `sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c`;
- vector component: `sha256:efa34511338c4f28f7698db3aab7afbdde36c36e7d9ea36745367180b678db82`;
- embedding component: `sha256:cb084be3748ace7a75f68e2f2641566248c53566365f8f802c6c24b75e99c5e9`;
- provider identity: `vector-2026.06`;
- profile identity: `increment5-vector-fixture-replay-v1`;
- catalog identity: computed from canonical catalog bytes and retained in every request and receipt;
- generation identity: computed from exact catalog, components, rights manifest, watermark, and current passage bindings.

## Applicable accepted specification boundary

This atom is evidence for the vector-specific portion of the accepted 5B
implementation boundary under the 5A contract, including the applicable
retrieval, production-profile, triage-context, rights, security, and replay
requirements selected for parent #251. Parent 5B remains open until exact,
full-text, vector, and admitted-graph branches are all merged and independently
attributable.

No 5B3 file claims hybrid composition (`GRAG-031`), named tools, complete
hydration, `DOPS-*` operational admission, production embedding qualification,
provider approval, or activation authority.

## Required completion evidence

Before issue #303 can close, the canonical product commit over the exact post-5B2
base must retain:

- focused 5B3 deterministic tests passing;
- the complete deterministic repository suite passing;
- all permanent workflows passing on the exact reviewed head;
- a fresh substantive review with zero unresolved P1/P2 findings;
- zero unresolved review threads; and
- a product-only merge to `main` with exact commit and tree identities.

A fixture/replay pass remains a fixture/replay pass. It must never be described
as live provider, model, embedding, vector-index, production, or activation
qualification.
