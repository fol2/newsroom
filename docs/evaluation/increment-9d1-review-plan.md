# Increment 9D1 blinded review and measurement authority

Status: **contract complete; reviewer access not authorised**

Issue: [#496](https://github.com/fol2/newsroom/issues/496)
Owner plan digest: `sha256:92510c8b3989bb25cfce187b3477a71d8909a691ad8f3b88ae4917e456e9216d`

## Boundary

`newsroom.increment9.review` defines immutable review, assignment,
adjudication, slice, ablation, metric and sealed-ingest records. It reads no
campaign evidence and starts no reviewer. Every record and receipt has false
authority for live calls, reviewer access, credentials, egress, spend,
publication, Evidence Intake, canary and production mutation or activation.

An `ADMITTED_FOR_LATER_REVIEW` receipt proves only that 9D2 has presented the
exact sealed prospective universe. Runtime reviewer authority, available
provider routes, exact resolved identities, protected-evidence access and the
remaining budget must still be established by #497.

## Reviewer manifest

OD-009 binds these three roles:

| Role | Provider | Route | Selector | Isolated memory namespace |
| --- | --- | --- | --- | --- |
| `PRIMARY_A` | Anthropic | Claude Agent SDK | `claude-sonnet-5` | `increment9/primary-a` |
| `PRIMARY_B` | xAI | Grok Build CLI | `grok-4.6` | `increment9/primary-b` |
| `ADJUDICATOR` | Google | Gemini API | `gemini-3.7-flash` | `increment9/adjudicator` |

The SUT provider is OpenAI. The three reviewer families are distinct from one
another and from the SUT. A selector must resolve to and record one exact model,
CLI or SDK identity before a label is decision-bearing. An unavailable family,
missing primary, invalid output or unresolved identity is `NOT_EVALUATED`.
There is no same-family fallback, adjudicator-as-primary replacement,
deterministic repair or silent substitution.

The owner selected AI consensus as editorial ground truth and no human-labelled
anchor. Reports must state that limitation. Human reviewer time is zero. The
gross metered AI reviewer cap is 2,400 minutes and every invocation remains in
the Epoch cost ledger.

## Blinding and chronology

Every sealed case is assigned to both primaries. They start in parallel against
the same case universe. Assignment is deterministic by canonical case ID and
role. Each primary receives:

- the case evidence permitted by the protected-evidence policy;
- its own profile and memory-snapshot identity;
- no peer result, adjudication or later Hermes decision;
- no operational metadata that reveals system variant or outcome.

`ReviewLabel.peer_result_visible` and
`ReviewLabel.operational_metadata_visible` must both be false. Each result
records the resolved model identity, memory snapshot, confidence in parts per
million and a research-appendix digest. The appendix is required even when no
external research was performed and is the retained authority for queries,
URLs, retrieved-byte digests, observation times and purposes.

Peer labels become visible only after both are sealed. An adjudication timestamp
cannot precede either label. Agreement establishes `PRIMARY_CONSENSUS` without
an adjudicator, except that a supported zero-tolerance flag always requires
Gemini adjudication and blocks when supported. A genuine disagreement requires
Gemini adjudication. A missing/invalid primary or invalid adjudication remains
`NOT_EVALUATED` and is never removed from the denominator.

## Sealed case universe and exposure

`ReviewUniverseSeal` may be built only from an already sealed prospective
evidence inventory and the final Effective Manifest Cohort. It binds every case
to the Epoch, final cohort and Effective Manifest. Case IDs and evidence digests
are unique and cases are canonically ordered. Result knowledge must be absent at
seal time. Retrospective extension, substitution and denominator repair are
false.

The deterministic fixture corpus proves the OD-008 constraints:

- exactly 120 semantic cases;
- at least 30 Hong Kong, 30 UK, 30 `EN_GB`, 30 `ZH_HANT_HK` and 20 `MIXED`;
- at least 60 official cases and no more than one-third comparator cases;
- at least 20 cases in each claimed beat;
- at least 10 changed revisions for each of the ten approved sources;
- at least 10 corrections/supersessions, 20 related-distinct/false-merge cases
  and 12 warning transitions;
- all natural warning transitions retained.

Every count uses unique sealed case IDs. One case may satisfy multiple
pre-registered dimensions, but cannot be duplicated to increase any count.
Underexposure fails universe construction and therefore cannot reach 9D2.

## Slice authority

Each case has exactly one value in every dimension:

| Dimension | Values |
| --- | --- |
| Jurisdiction | `HONG_KONG`, `UK` |
| Language | `EN_GB`, `MIXED`, `ZH_HANT_HK` |
| Source role | `COMPARATOR`, `OFFICIAL` |
| Beat | `EDUCATION_AND_FAMILIES`, `IMMIGRATION_AND_BNO`, `OFFICIAL_WARNINGS`, `POLICY_AND_SERVICES` |
| Case kind | `CORRECTION_OR_SUPERSESSION`, `RELATED_DISTINCT_OR_FALSE_MERGE`, `WARNING_TRANSITION` |

Aggregate success cannot rescue a required slice below 800,000 ppm. Missing or
unreviewable evidence is `INCONCLUSIVE_OR_BLOCKED_NEVER_PASS`.

## Ablation authority

Every sealed case binds evidence for every pre-registered mode, all against the
same case universe:

| Axis | Modes |
| --- | --- |
| Source | all approved; media comparator only; official only |
| Retrieval | admitted graph; exact; full text; hybrid RRF; vector |
| GraphRAG | Graphiti plus admitted graph; without admitted graph |
| Extraction | deterministic source text; Graphiti extraction |
| Triage | deterministic veto; proposal first |
| Operational | full Hermes workflow; warning deterministic default |

No mode can use a favourable replacement case, omit a failed output or change
its membership after result knowledge. Ablations remain comparative evidence;
they cannot rescue a failed decision-bearing full workflow.

## Label and reason authority

Primary and adjudicated verdicts are `PASS`, `FAIL` or `NOT_EVALUATED`.
`PASS` has no failure reason. Every other verdict has at least one sorted,
unique structured reason. The reasons include:

- `IDENTITY_UNRESOLVED`, `MISSING_EVIDENCE`, `OTHER_MATERIAL_ERROR` and
  `UNREVIEWABLE`;
- all pre-registered zero-tolerance classes listed below.

Prose cannot replace the structured verdict/reason fields. Confidence is
bounded from zero to one million ppm and does not override a failed or missing
verdict.

## Metric authority

| Metric | Direction | Threshold | Denominator |
| --- | --- | ---: | --- |
| AI-consensus editorial pass | minimum | 900,000 ppm | all reviewable cases |
| Completed scheduled checks | minimum | 995,000 ppm | all due polls |
| Event precision | minimum | 900,000 ppm | all positive event decisions |
| Event recall | minimum | 800,000 ppm | all eligible events |
| Exact-ID precision at 1 | minimum | 1,000,000 ppm | all exact-ID cases |
| Hybrid recall at 12 | minimum | 900,000 ppm | all retrieval cases |
| MRR at 12 | minimum | 750,000 ppm | all retrieval cases |
| Per-slice pass | minimum | 800,000 ppm | each required slice |
| Non-urgent batch p95 | maximum | 120 minutes | all non-urgent batches |
| Projection age | maximum | 60 minutes | all admitted projections |
| Retrieval p95 | maximum | 5,000 ms | all retrieval attempts |
| Warning p95 | maximum | 15 minutes | all warning transitions |

Uncertainty uses `WILSON_SCORE_95_FIXED_INTEGER`, avoiding floating-point or
post-result method selection. Thresholds, denominators and uncertainty method
cannot change after results are known.

Zero tolerance has deterministic precedence over aggregate and slice metrics:

`BUDGET_OVERRUN`, `DEAD_LETTER`, `DISTRACTOR_FALSE_MERGE`, `GAP`,
`PROHIBITED_EFFECT`, `PROVENANCE_FAILURE`, `RIGHTS_FAILURE`, `SCOPE_FAILURE`,
`SILENT_LOSS`, `TEMPORAL_FAILURE`, `TRUST_LABEL_FAILURE` and
`UNSUPPORTED_MATERIAL_CLAIM`.

## Sealed evidence-ingest boundary

`SealedEvidenceIngestController` checks:

1. exact Review Plan, universe and assignment-manifest digests;
2. exact Epoch, final cohort, Effective Manifest and evidence inventory;
3. two independent primary assignments for every case;
4. chronology after universe and assignment sealing;
5. independently qualifying final cohort;
6. sealed prospective evidence;
7. no material change and no result-informed universe change.

Failure returns `REJECTED` with a closed reason. Success returns
`ADMITTED_FOR_LATER_REVIEW`, still with no reviewer or evidence-access
authority.

## Traceability

| Contract | Authority |
| --- | --- |
| Integrated retrieval, GraphRAG, triage and operational modes | OD-007 |
| Epoch universe, slices, exposure and thresholds | OD-008; #491 |
| Reviewer identities, independence, blinding and adjudication | OD-009; ADR 0006 |
| Comparator and retrieval ablations | OD-010; #494 |
| Reviewer time and monetary budget | OD-011 |
| Protected evidence and research access | OD-012; #489 |
| Immutable plan and non-effect boundary | #488 |

This contract is consumed by #497 only after #493 and #495 have sealed their
eligible prospective evidence. Merging #496 does not start review or authorise
any live route.
