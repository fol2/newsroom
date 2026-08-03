# Increment 5 retrieval evaluation plan v1

- **Status:** reviewed machine-plan binding for Increment 5A
- **Execution owner:** 5E / #254
- **Contract:** `newsroom/increment5/data/increment5a_retrieval_contract_v1.json`
- **Contract digest:** `sha256:c7dabaf97301f851c67a2d831f6ac87b34b38c78626ea7edf8f5725ff97f1c58`
- **Machine plan:** `newsroom/increment5/data/increment5_retrieval_evaluation_plan_v1.json`
- **Machine-plan digest:** `sha256:ce10ec46ad56d5a8182f8927d2569f3f9cec3a051ae7ad5a85837b5d0889042e`

The machine JSON is the authoritative preregistration. This document explains it
without adding thresholds, exceptions, or authority.

## Decision scope

`HYBRID` is the only qualification-bearing system. `EXACT_ONLY`,
`FULL_TEXT_ONLY`, `VECTOR_ONLY`, and `ADMITTED_GRAPH_ONLY` are mandatory
comparative ablations.

Every contract threshold, mandatory-family criterion, required-slice criterion,
temporal gate, and rebuild gate applies independently to `HYBRID`. Comparative
quality is reported separately, is not decision-bearing, cannot be pooled, and
cannot rescue a failed hybrid target. A safety or rights violation in any
executed system remains blocking.

## Frozen Epoch protocol

Before a Run exists, 5E creates a canonical
`newsroom.increment5.retrieval-evaluation-epoch.v1` record. Its SHA-256 identity
binds:

- the reviewed contract digest;
- the externally reviewed evaluation-plan digest;
- every component digest;
- the exact source inventory;
- source/provider, adapter, and parser versions;
- the exact query set;
- the threshold set;
- the policy set;
- the dataset manifest;
- the label and adjudication policy;
- the exact code tree; and
- the generation identity.

Any difference in a frozen identity is a material change. A material component,
source, query, threshold, or policy change starts a new Epoch. Every Run binds
the exact Epoch digest and all frozen identities must remain equal within that
Epoch.

Cross-Epoch pooling is prohibited. A missing or mismatched Epoch is
`NOT_EVALUATED`. Superseded Epoch Runs remain retained. The Epoch record binds
the plan digest externally at Run creation, so the machine plan does not contain
a self-referential digest.

## Evaluation evidence semantics

Every retained metric identifies its count, denominator, unit, system role,
query family, slice, Epoch, generation, exact component identities, and sampling
status. Raw branch scores are never compared.

Ground truth is the owner-frozen corpus of authoritative identities, revisions,
dependency roots, valid-time labels, rights decisions, expected Candidate
dispositions, and relevance judgements. No graph, index, provider, or retrieval
branch is ground truth.

Performance outcomes, change-evaluation outcomes, operational evidence, and
exploratory recommendations remain separate. A missing, invalid, withdrawn,
under-exposed, rights-blocked, wrong-Epoch, or failed Run is retained as such
and cannot be pooled into a pass.

## Mandatory GraphRAG query families

A missing or under-exposed family is `NOT_EVALUATED`.

1. **Event and development precision** — same-event state, development of an existing event, and related-but-distinct event; precision ≥ 0.90, recall ≥ 0.80, every required family/slice recall ≥ 0.80, and distractor false-merge precision = 1.00.
2. **Source-revision impact** — correction, supersession, and downstream-Candidate impact; precision and recall ≥ 0.80, every required family/slice recall ≥ 0.80, and provenance completeness = 1.00.
3. **Long-running policy, case, or process timeline** — ordered development, correction, supersession, and temporal cutoff; precision and recall ≥ 0.80, every required family/slice recall ≥ 0.80, and temporal-correctness errors = 0.

Each sufficiently exposed family is an independent blocking surface. Aggregate
MRR, aggregate recall, another family, a comparative branch, or reviewer
judgement cannot rescue it.

## DEVAL-046 triage-error protocol

The hybrid target preregisters and reports all six classes separately. Each
class retains eligible-opportunity count, error count or counts, rate in parts
per million, exact case labels, and definition. Cross-class rate pooling is
prohibited. Each class requires at least 10 relevant preregistered qualification
cases; a shortfall is `NOT_EVALUATED`.

| Class | Eligible opportunity | Error metrics | Frozen decision treatment |
|---|---|---|---|
| `FALSE_MERGE` | authority roots or events labelled related-but-distinct | `false_merge_count`, `false_merge_opportunity_count`, `false_merge_rate_ppm` | automatic blocker through perfect distractor false-merge precision |
| `FRAGMENTATION` | one authority-labelled event or development expected to remain one result root or disposition | `fragmentation_count`, `fragmentation_opportunity_count`, `fragmentation_rate_ppm` | mandatory separate report; no invented post-hoc threshold |
| `SNOWBALL_ABSORPTION` | related-but-distinct or shared-origin cases where a broad root must not absorb another event | `snowball_absorption_count`, `snowball_absorption_opportunity_count`, `snowball_absorption_rate_ppm` | mandatory separate report; no invented post-hoc threshold |
| `FALSE_OR_MISSED_DEVELOPMENT` | labelled developments, corrections, and supersessions | `false_development_count`, `missed_development_count`, `development_opportunity_count`, `false_or_missed_development_rate_ppm` | automatic blocker through frozen event/development precision and recall |
| `DUPLICATE_CANDIDATE_CREATION` | one expected downstream Candidate disposition for one authoritative dependency root and material development | `duplicate_candidate_creation_count`, `single_candidate_opportunity_count`, `duplicate_candidate_creation_rate_ppm` | mandatory separate report; no invented post-hoc threshold |
| `UNNECESSARY_CANDIDATE_CREATION` | frozen labels require no new Candidate | `unnecessary_candidate_creation_count`, `no_candidate_expected_opportunity_count`, `unnecessary_candidate_creation_rate_ppm` | mandatory separate report; no invented post-hoc threshold |

Candidate-related evaluation uses read-only expected dispositions. It creates,
mutates, admits, or publishes no Candidate.

## Exposure minima

The frozen qualification partition contains at least:

- 100 unique qualification cases;
- 30/30/40 cases across the three mandatory families;
- 10 cases per required case type;
- 20 relevant cases per global required slice;
- 10 cases per mandatory family / required-slice intersection; and
- 10 relevant cases per triage-error class.

Each case counts once in exactly one mandatory family. It may carry multiple
independently frozen slice and error-opportunity labels. Cross-family reuse,
calibration counting, and cross-Epoch pooling are prohibited. Duplicate,
invalid, withdrawn, and post-freeze cases do not count.

## Frozen gates

The hybrid target must satisfy all contract thresholds, every mandatory-family
criterion, and these zero-tolerance gates:

- temporal-correctness errors = 0; and
- rebuild-reproducibility mismatches = 0.

A sufficiently exposed failing family is `FAIL`. An exposure or Epoch-identity
shortfall is `NOT_EVALUATED`. Aggregate or comparative success cannot override
a family, slice, temporal, rebuild, safety, or rights failure.

## Safety and failure experiments

5E executes generated/raw Cypher rejection; caller Lucene rejection; arbitrary
index, predicate, depth, fan-out, and date-window rejection; write and
credential rejection; stale/incomplete generation behaviour; branch timeout;
collision conflict; rights withdrawal and purge; graph/index loss and
reproducible rebuild; rollback; source/dataset/component identity mismatch;
least-privilege source/provider access; and scoped containment.

Every experiment retains its exact system role, Epoch, contract, components,
dataset, generation, service, code tree, and outcome. Failed Runs remain
evidence.

## Public artifact safety

Repository-visible datasets, manifests, reports, receipts, and regression cases
exclude secrets, credentials, prohibited source expressions, unrestricted query
payloads, personal data, protected or rights-restricted text, and confidential
review material.

Protected material may be represented only through permitted hashes, protected
references, bounded permitted extracts, or independently reproducible fixtures.
A safety or rights omission blocks the Run; final-report redaction cannot repair
prohibited material entering an index, log, or retained context.

## Decision output

The 5E report retains exact Plan, Epoch, Run, contract, profile, component,
source/provider, adapter/parser, dataset, query-set, threshold, policy,
generation, service, and code identities. It includes methods, samples, labels,
adjudication, counts, denominators, uncertainty, family/slice/error-class
results, latency, cost, deviations, incidents, reconciliation, containment,
recovery, and every failed or superseded Run needed for reproduction.

It identifies `HYBRID` as the sole decision-bearing result and reports each
comparative ablation separately. It separates contract conformance, hybrid
qualification, comparative results, unqualified embedding quality, operational
security, reconciliation, containment, recovery, and production activation,
which remains explicitly unauthorized.

A completed Run ends with a retained owner decision or explicit unresolved
status. Passing 5E still does not activate production.
