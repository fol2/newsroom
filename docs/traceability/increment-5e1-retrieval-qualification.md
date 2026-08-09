# Increment 5E1 traceability

- Issue: #332
- Parent: #254
- Programme: #145
- Accepted base: `main@fda53b723c7f27c9fc0d5e9bc204721d254332dd`
- Gate: Tier S

## Retrieval-specific ownership

5E1 supplies bounded evidence for the nine Increment 5E requirements:

- `GRAG-050` and `GRPROD-010`: exact Neo4j Community target identity;
- `GRAG-051`: challenger remains disabled without a measured blocker or owner-approved comparison purpose;
- `GRAG-054`: all three mandatory retrieval families and multilingual, temporal, correction, false-merge, dependency, and rights slices;
- `GRAG-055`: separately attributable exact, full-text, fixed-point fixture-vector, admitted-graph, and hybrid metrics;
- `GRAG-056`: provenance, trust, temporal, rights, scope, write, no-false-success, and reproducible-rebuild blockers;
- `GRPROD-001`: all four mandatory modes are present in the production-shaped target;
- `GRPROD-015`: missing, fake, graph-free, silent-fallback, or incompatible target configuration cannot load; and
- `GRPROD-023`: GraphRAG is mandatory even though adapters remain replaceable.

Complete requirement credit remains at parent #254 after #333 proves final security, rights purge, graph/index recovery, signed evidence, and integrated closeout.

## Source map

- Target: `newsroom/increment5/data/increment5_retrieval_qualification_target_v1.json` — `sha256:fd88328d9ed74573a9b0aa2e7900dc437a7f8a4963c96da59869b9dddbad7271`
- Corpus: `newsroom/increment5/data/increment5_retrieval_qualification_corpus_v1.json` — `sha256:07f5f0cceb26c0744aadd6feacb056aa09503b0552ec1223a4f3228af6fbeb70`
- Public facade: `newsroom/increment5/retrieval_qualification.py`
- Typed target, corpus, Epoch, observation, report, measurement, gate, evaluator, and journal modules: `newsroom/increment5/_retrieval_qualification_*.py`
- Deterministic contract and gate tests: `newsroom/tests/test_increment5e1_retrieval_qualification.py`
- Immutable report-history tests: `newsroom/tests/test_increment5e1_retrieval_qualification_journal.py`
- Actual Neo4j test: `newsroom/tests/test_projection_b2_increment5e1_qualification.py`
- Reproducible runner: `scripts/increment5_retrieval_qualification.py`

## Non-effects

No live source, provider/model/embedding call, credential, external egress, spend, protected expression, graph write, Candidate/Hypothesis creation, publication, qualification authority, or production activation. Comparative ablations are not decision-bearing and vector results remain fixture/replay-only.
