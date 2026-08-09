# Increment 5 bounded-retrieval traceability

- **Status:** amended closed-world ownership map
- **Owner amendment:** #327
- **Machine source:** `newsroom/increment5/traceability.py`
- **Verification:** `newsroom/tests/test_increment5a_traceability.py`
- **Planning record:** `docs/plans/2026-08-06-010-increment-5-scope-and-gates-amendment.md`
- **Rows:** 155 unique accepted requirements

## Meaning

A row separates accepted decision authority from complete delivery ownership.
Increment 5 may define a seam or produce supporting evidence without claiming
that a later triage, Candidate, evaluation or operational requirement has been
completely delivered.

Normative decision anchors point to accepted specifications, the 5A contract or
exact accepted Increment 4 evidence. GitHub issues identify delivery ownership;
they are not a competing source of product authority.

## Closed-world inventory

The inventory contains the selected `GRAG-*`, `GRPROD-*` and `TRI-*` ranges,
all 43 accepted `DEVAL-*` requirements and all 61 accepted `DOPS-*`
requirements.

The amended complete distribution is:

`9 / 0 / 2 / 12 / 9 / 6 / 110 / 7`

for 5A, 5B, 5C, 5D, 5E, Increment 6, Increment 8 and accepted Increment 4
delivery. The groups are disjoint and total 155. There is no ownerless
activation bucket.

## Delivery ownership

| Boundary | Count | Complete ownership |
|---|---:|---|
| 5A / #250 | 9 | accepted contract, Plan/Epoch, non-execution and traceability decisions |
| 5B / #251 | 0 | four required retriever implementation atoms; credited at composition/integration |
| 5C / #252 | 2 | bounded named read-only tools and no unrestricted graph mutation |
| 5D / #253 | 12 | one-request composition, hydration, current collision receipt and truthful outcomes |
| 5E / #254 | 9 | retrieval-specific target/configuration, ablation, provenance, security, rights and recovery |
| Increment 6 / #146 | 6 | cross-request Hypothesis, Candidate, Watch/Hold and later Handoff effects |
| Increment 8 / #148 | 110 | full evaluation, operations, recovery, security and Operational Admission |
| Increment 4 / #144 | 7 | accepted graph authority, canonical contract and actual-service foundations |

## 5A

The nine 5A rows are:

- `DEVAL-010`, `DEVAL-011`, `DEVAL-012`, `DEVAL-051`;
- `DOPS-076`;
- `GRAG-052`, `GRAG-053`, `GRAG-058`; and
- `GRPROD-032`.

These rows bind the accepted contract and safe non-execution semantics. They do
not imply that later evaluation, operational or production systems exist.

## 5B

5B supplies the exact, full-text, fixture-vector and admitted-graph retrievers.
No selected whole requirement is credited to an independent branch before
composition. #251 closes once, after all four branches, under the milestone
gate.

## 5C

The exact 5C set is:

`GRAG-033`, `GRAG-034`.

The tools are purpose-specific, read-only and bounded. They do not create a
composed hybrid response, Candidate authority or unrestricted graph access.

## 5D request-local boundary

The exact 5D set is:

- `GRAG-031`, `GRAG-032`, `GRAG-035`, `GRAG-040`, `GRAG-041`, `GRAG-043`;
- `TRI-020`, `TRI-021`, `TRI-022`, `TRI-023`, `TRI-025`, `TRI-027`.

5D owns exact-first orchestration, deterministic fusion, authoritative
dependency-root deduplication, permitted hydration, current deterministic
collision evidence, inspectable provenance and explicit complete, blocked,
stale, incomplete or unavailable outcomes.

5D creates no Event Hypothesis, Candidate, Watch/Operational Hold, source
collection effect or later Handoff. `GRAG-042`, `TRI-024`, `TRI-026` and
`TRI-028` therefore do not belong to this request-local group.

## 5E retrieval-specific boundary

The exact 5E set is:

- `GRAG-050`, `GRAG-051`, `GRAG-054`, `GRAG-055`, `GRAG-056`;
- `GRPROD-001`, `GRPROD-010`, `GRPROD-015`, `GRPROD-023`.

This boundary covers the repository-native target, mandatory-mode and
configuration enforcement, conditional challenger rule, deterministic
retrieval corpus, exact/full-text/vector/graph/hybrid ablation, provenance and
temporal blockers, named-surface security, rights purge and graph/index
recovery.

The final 5E2 closed-world reconciliation is recorded in
[`increment-5e2-final-closeout.md`](increment-5e2-final-closeout.md). Its
content-addressed inventory binds the deterministic and authenticated
actual-service cases required for the final Tier-M receipt.

It does not claim complete human evaluation, live shadow, canary, Operational
Profiles, scheduling, queues, backup/restore of the complete newsroom,
capacity, licence or Operational Admission.

## Increment 6 transfer

The exact transfer to #146 is:

`GRAG-042`, `GRAG-044`, `GRPROD-021`, `TRI-024`, `TRI-026`, `TRI-028`.

These requirements need cross-request state or effects:

- complete Source/Revision/Signal/Lead to Hypothesis/Candidate integration;
- exact fallback, Watch or Operational Hold decisions;
- a graph-native vertical slice through Candidate admission;
- empty-retrieval non-creation;
- Candidate-admission enforcement of current collision evidence; and
- durable later reconciliation/Handoff after guarded urgent degradation.

A Retrieval Context may carry a collision receipt and
`reconciliation_required`; only Increment 6 can prove the corresponding
downstream effect.

## Increment 8 transfer

Every non-5A `DEVAL-*` row and every operational `DOPS-*` row belongs to #148.

The additional graph/product rows owned by #148 are:

`GRAG-045`, `GRAG-046`, `GRAG-057`, `GRPROD-002`, `GRPROD-004`,
`GRPROD-011`, `GRPROD-012`, `GRPROD-022`, `GRPROD-024`, `GRPROD-030`,
`GRPROD-031`.

They require system-level or admission evidence: collection/Lead isolation
during graph outage, complete live-shadow gates, operational/licence
qualification, production-profile enforcement, repair/replacement and
production-equivalent evaluation, outage semantics, activation identity and
readiness.

The 110-row Increment 8 group includes:

- prospective event universes, sampling and production labels;
- human review, blinding, second review, adjudication and disagreement;
- source-role and release-evidence decisions;
- exact Operational Profiles and numerical objectives;
- schedules, leases, retries, circuits, quarantine, queues and capacity;
- multidimensional health and coverage posture;
- observability, alerts, incidents, owners and runbooks;
- credentials, access, egress and authenticated manual actions;
- complete reconciliation, backup/restore, fault injection and rollback; and
- intended-hardware, cost, licence and Operational Admission evidence.

`GRPROD-022` now has explicit #148 ownership.

## Accepted prior delivery

Seven rows retain exact accepted Increment 4 evidence:

`GRAG-030`, `GRPROD-003`, `GRPROD-005`, `GRPROD-013`, `GRPROD-014`,
`GRPROD-016`, `GRPROD-020`.

Each anchor is pinned to
`main@c9e31879421083e82e2538d57087d04e9b454d34` and the exact requirement
fragment in `newsroom/increment4/traceability.py`.

## Gate granularity

- **Tier L:** focused leaf tests, complete deterministic CI once, source
  integrity, substantive review, no P1/material P2.
- **Tier S:** focused/full deterministic CI, only affected service/authority
  lanes, substantive review, no P1/material P2.
- **Tier M:** once per integrated milestone, all applicable workflows on one
  exact `main` head, affected actual services, signed SDLC, integrated
  replay/rights/failure evidence, and no P1/P2 or open review thread.

The gate follows risk and integration scope; it is not duplicated as a final
release exercise on every leaf.

## Verification invariants

Tests reject:

- a missing, duplicate or unknown accepted requirement;
- any difference between accepted DEVAL/DOPS headings and machine inventory;
- overlapping or incomplete ownership groups;
- a count different from `9 / 0 / 2 / 12 / 9 / 6 / 110 / 7`;
- a cross-request effect in 5D;
- a complete DEVAL or operational DOPS claim in 5E;
- an Increment 6 transfer not owned by #146;
- a full evaluation/operations row not owned by #148;
- an ownerless `GRPROD-022`;
- changed accepted Increment 4 evidence; or
- an issue reference substituted for normative decision authority.

The amendment changes no runtime behavior and authorises no source, provider,
credential, call, spend, publication, shadow, canary or activation.
