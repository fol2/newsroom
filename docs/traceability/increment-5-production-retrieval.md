# Increment 5 production retrieval traceability

- **Status:** exact 5A decision and closed-world delivery map
- **Machine source:** `newsroom/increment5/traceability.py`
- **Verification:** `newsroom/tests/test_increment5a_traceability.py`
- **Contract:** `newsroom/increment5/data/increment5a_retrieval_contract_v1.json`
- **Rows:** 155 unique accepted requirements

## Meaning

A row separates the decision bound by 5A from executable delivery. It does not
claim that a deferred retriever, tool, hybrid composer, operational policy,
health control, queue control, reconciliation control, containment control,
Operational Profile, review process, or qualification Run already exists.

The inventory is closed-world:

- the readiness ladder selects the exact Increment 5 `GRAG-*`, `GRPROD-*`, and
  `TRI-*` ranges;
- it selects **every `DEVAL-*` requirement** in the accepted shadow-evaluation
  specification; and
- it selects **every `DOPS-*` requirement** in the accepted reliability and
  operations specification.

The accepted specifications currently contain 43 `DEVAL-*` and 61 `DOPS-*`
requirements. Tests parse both specification files and require exact equality
with the machine inventory. A manually selected subset cannot appear complete.

## Delivery derivation

The smaller delivery boundaries are explicit:

- 5A contains the twelve contract, Plan, profile, non-activation, and
  traceability requirements it actually delivers;
- 5B contains only `TRI-021`;
- 5C contains exactly four named-tool requirements;
- 5D contains exactly sixteen one-request retrieval requirements;
- seven rows cite accepted Increment 4 delivery; and
- `GRPROD-022` remains outside Increment 5 activation.

**5E is the closed-world remainder.** Once those exact groups are removed from
the 155-row inventory, the remaining 114 requirements belong to 5E. A newly
accepted `DEVAL-*` or `DOPS-*` row therefore cannot disappear through omission.

## Delivery distribution

| Boundary | Count | Ownership |
|---|---:|---|
| 5A / #250 | 12 | contract, safe profiles, frozen Plan/Epoch protocol, and traceability |
| 5B / #251 | 1 | four independent typed retrievers and receipts |
| 5C / #252 | 4 | six named read-only tools and tool-local caller/purpose/scope controls |
| 5D / #253 | 16 | one-request hybrid composition, lineage, hydration, collision, and outcomes |
| 5E / #254 | 114 | closed-world evaluation, operational policy, monitoring, admission, queues, durability, reconciliation, containment, security, recovery, and qualification |
| Increment 4 / #144 | 7 | accepted graph authority, ontology, and actual-service CI foundations |
| Outside Increment 5 activation | 1 | production activation remains unauthorized |

The groups are disjoint and total 155.

## Exact 5C boundary

The complete 5C traceability inventory is `GRAG-033`, `GRAG-034`, `GRAG-035`,
and `TRI-022`. It proves bounded named read-only interfaces, tool-local
caller/purpose/scope checks, and inspectable receipts. It does not claim that
source or model content is already unable to alter every operational policy,
egress rule, budget, credential, destination, or authority surface.

`DOPS-026` therefore belongs to 5E. Its complete evidence must cover all
executable operational surfaces, not merely the local named-tool parser.

## Exact 5D request boundary

The complete 5D inventory is:

- `GRAG-031`, `GRAG-032`, and `GRAG-040`–`GRAG-045`;
- `GRPROD-021` and `GRPROD-024`; and
- `TRI-020` and `TRI-023`–`TRI-027`.

No `DOPS-*` row is assigned to 5C or 5D. `DOPS-076` is delivered in 5A because
it states that admission is not activation. Every other `DOPS-*` row belongs to
5E.

`TRI-028` also belongs to 5E. A 5D request may record that urgent work proceeded
without advisory semantic retrieval, but delivery requires the mandatory later
reconciliation to be durably arranged and completed or retained as blocked.

## Closed-world 5E evaluation ownership

Every `DEVAL-*` row not delivered by 5A belongs to 5E. This includes the
requirements previously omitted from the hand-selected map:

- `DEVAL-001`, `DEVAL-002`, and `DEVAL-004`;
- `DEVAL-020`–`DEVAL-026`;
- `DEVAL-030`–`DEVAL-033`; and
- `DEVAL-060`–`DEVAL-063`.

They require no-public-effect and authority isolation, an event-level reviewed
universe, prospective and contemporaneous labels, explicit unreviewable and
negative/failure sampling, authorised human review, practical blinding,
independent review or adjudication, retained disagreement, evidence-based source
role changes, quiet-period protection, Comparator non-promotion, and exact
search-purpose attribution.

The Epoch freezes the exact dataset manifest and label/adjudication policy before
a Run. 5E must execute and retain these controls; a model, provider, legacy
pipeline, feed, index, or metric cannot become sole ground truth.

## Closed-world 5E operational ownership

Every `DOPS-*` row except `DOPS-076` belongs to 5E. This includes the
requirements previously omitted from the hand-selected map:

- `DOPS-003`–`DOPS-006` and `DOPS-008`;
- `DOPS-020`–`DOPS-025`;
- `DOPS-041`, `DOPS-042`;
- `DOPS-051`, `DOPS-053`, `DOPS-055`;
- `DOPS-061`–`DOPS-063`;
- `DOPS-065`, `DOPS-066`, `DOPS-068`; and
- `DOPS-071`.

They cover logical-operation idempotence, no-model scheduling, missed-work
visibility, bounded ownership, strict source access, status and parser safety,
webhook provenance, queue fairness and Urgent capacity, ambiguous-effect
reconciliation, bounded catch-up, post-restore reconciliation, health metrics,
correlated records, consequence-based alerts, retained incidents, regression
learning, authenticated manual actions, and scoped canary evidence.

These are system-operation controls. A successful request or green unit test
cannot substitute for their executable 5E evidence.

## Delivered in 5A

`DEVAL-010`, `DEVAL-011`, `DEVAL-012`, `DEVAL-051`, `DEVAL-072`,
`DOPS-076`, `GRAG-052`, `GRAG-053`, `GRAG-058`, `GRPROD-002`,
`GRPROD-023`, and `GRPROD-032`.

`DEVAL-011` points directly to the machine Plan’s `#/epoch_protocol`. Before a
Run, the Epoch binds exact contract, Plan, component, source, provider, adapter,
parser, query, threshold, policy, dataset, label/adjudication, code-tree, and
generation identities. Any frozen identity difference starts a new Epoch;
cross-Epoch pooling is prohibited and mismatch is `NOT_EVALUATED`.

## Exact prior delivery

Only seven rows are satisfied by prior increments, all from accepted Increment
4: `GRAG-030`, `GRPROD-003`, `GRPROD-005`, `GRPROD-013`, `GRPROD-014`,
`GRPROD-016`, and `GRPROD-020`.

Every row retains issue #144, accepted
`main@c9e31879421083e82e2538d57087d04e9b454d34`, the exact repository file,
and an existing requirement fragment. Tests open each referenced path and prove
the fragment exists.

Increment 3 remains a graph foundation but is not credited with `GRAG-042`:
its accepted evidence excluded the Event Hypothesis handoff and contained no
Event Hypothesis node.

## Key ownership boundaries

- `GRAG-031` → 5D/#253: independent branches are not a hybrid until fusion and authoritative dependency-root deduplication exist.
- `GRAG-042` → 5D/#253: complete `Source → Revision → Signal → Lead → Hypothesis → Candidate` projection and hydration remains required.
- `TRI-028` → 5E/#254: guarded urgent request degradation is not complete delivery without durable later reconciliation.
- `DOPS-010`–`DOPS-016` → 5E/#254: multidimensional health, successful observation, freshness, stale-state honesty, coverage posture, Active-path containment, and comparator non-substitution are Operational Profile work.
- `DOPS-026` → 5E/#254: local tool validation does not prove source/model content cannot alter operational policy, egress, budgets, or authority.
- `DOPS-043` and `DOPS-044` → 5E/#254: queue backpressure and current-authority revalidation precede commit.
- `DOPS-046`–`DOPS-048` → 5E/#254: durable transition delivery, authoritative-store/audit failure policy, and cross-system failure classification are operational recovery controls.
- `DOPS-050` → 5E/#254: full reconciliation includes orphaned ownership, ambiguous calls, duplicate delivery, stale work, and pending Handoffs.
- `DOPS-061`–`DOPS-068` → 5E/#254: monitoring, incidents, regression learning, least privilege, and manual actions require retained operational evidence.
- `DOPS-073` → 5E/#254: a request outcome is not a system-level ability to pause the narrowest safe scope and broaden containment.
- `GRAG-051` → 5E/#254: a challenger requires a measured blocker or owner-approved bounded comparison purpose.
- `DEVAL-020`–`DEVAL-033` → 5E/#254: trusted evaluation requires frozen universe, labels, sampling, human review, and adjudication.
- `DEVAL-046` → 5E/#254: all six error classes are reported separately with counts, opportunity denominators, and rates.

## Decision state

Repository governance decides accepted source through owner control,
substantive review, required exact-head checks, resolved threads, and merge to
`main`. Non-inherited rows are `BOUND_BY_5A`; prior rows are
`INHERITED_ACCEPTED_AUTHORITY`. Digests identify content and do not form a
competing runtime admission system.

## Verification invariants

Tests reject missing or duplicate IDs; any difference between the accepted
specification headings and the machine `DEVAL-*`/`DOPS-*` inventories;
overlapping or incomplete delivery groups; a 5E set that is not the exact
closed-world remainder; generic or competing anchors; nonexistent prior
evidence; changed counts; deferred rows without the exact issue; any `DOPS-*`
row in 5C or 5D; any operational `DOPS-*` row other than `DOPS-076` assigned
before 5E; `TRI-028` assigned before durable later reconciliation; material
source/query/config changes reusing one Epoch; cross-Epoch pooling; independent
branches reported as a hybrid; incomplete lineage reported as prior delivery;
challenger work without its precondition; incomplete six-class `DEVAL-046`
measurement; production activation inside Increment 5; and runtime GitHub
approval or admission targets.
