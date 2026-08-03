# Increment 5 production retrieval traceability

- **Status:** exact 5A decision and delivery map
- **Machine source:** `newsroom/increment5/traceability.py`
- **Verification:** `newsroom/tests/test_increment5a_traceability.py`
- **Contract:** `newsroom/increment5/data/increment5a_retrieval_contract_v1.json`
- **Rows:** 114 unique accepted requirements

## Meaning

A row separates the decision bound by 5A from executable delivery. It does not
claim that a deferred retriever, tool, hybrid composer, operational health
control, queue control, reconciliation control, containment control,
Operational Profile, or qualification Run already exists.

The dependency split follows one categorical boundary:

- **5D ends at one bounded retrieval request.** It owns hybrid composition,
  dependency-root deduplication, complete discovery lineage, authoritative
  hydration, collision separation, and truthful request outcomes.
- **5E owns system operation.** It owns Operational Profiles, health and
  coverage posture, queue policy, durable transition delivery, mandatory later
  reconciliation, containment, dependency-specific failures, security,
  recovery, and qualification.

This prevents request-local `DEGRADED` or `INCOMPLETE` semantics from being
mistaken for cross-source operational recovery.

## Delivery distribution

| Boundary | Count | Ownership |
|---|---:|---|
| 5A / #250 | 12 | contract, safe profiles, frozen Plan/Epoch protocol, and traceability |
| 5B / #251 | 1 | four independent typed retrievers and receipts |
| 5C / #252 | 5 | six named read-only tools and the untrusted-input boundary |
| 5D / #253 | 16 | one-request hybrid composition, lineage, hydration, collision, and outcomes |
| 5E / #254 | 72 | operational admission, health, queues, durability, reconciliation, containment, security, recovery, and qualification |
| Increment 4 / #144 | 7 | accepted graph authority, ontology, and actual-service CI foundations |
| Outside Increment 5 activation | 1 | production activation remains unauthorized |

The groups are disjoint and total 114.

## Exact 5D request boundary

The complete 5D inventory is:

- `GRAG-031`, `GRAG-032`, and `GRAG-040`–`GRAG-045`;
- `GRPROD-021` and `GRPROD-024`; and
- `TRI-020` and `TRI-023`–`TRI-027`.

No `DOPS-*` row is assigned to 5D. `DOPS-026` belongs to 5C because it is the
untrusted-input boundary. `DOPS-076` is delivered in 5A because it states that
admission is not activation. Every other accepted `DOPS-*` row belongs to 5E.

`TRI-028` also belongs to 5E. A 5D request may record that urgent work proceeded
without advisory semantic retrieval, but the requirement is not delivered until
the mandatory later reconciliation is durably arranged and completed or retained
as explicitly blocked.

## Delivered in 5A

`DEVAL-010`, `DEVAL-011`, `DEVAL-012`, `DEVAL-051`, `DEVAL-072`,
`DOPS-076`, `GRAG-052`, `GRAG-053`, `GRAG-058`, `GRPROD-002`,
`GRPROD-023`, and `GRPROD-032`.

`DEVAL-011` points directly to the machine plan’s `#/epoch_protocol`. That
protocol requires a pre-Run canonical Epoch digest over exact contract, Plan,
component, source, provider, adapter, parser, query, threshold, policy, dataset,
label/adjudication, code-tree, and generation identities. Any frozen identity
difference—including a material component, source, query, threshold, or policy
change—starts a new Epoch. Cross-Epoch pooling is prohibited and mismatch is
`NOT_EVALUATED`.

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
- `DOPS-043` and `DOPS-044` → 5E/#254: queue backpressure and current-authority revalidation precede commit.
- `DOPS-046`–`DOPS-048` → 5E/#254: durable transition delivery, authoritative-store/audit failure policy, and cross-system failure classification are operational recovery controls.
- `DOPS-050` → 5E/#254: full reconciliation includes orphaned ownership, ambiguous calls, duplicate delivery, stale work, and pending Handoffs.
- `DOPS-067` → 5E/#254: 5C proves tool-local authorization only; least-privilege credentials, source-access scopes, and approved destinations require operational security evidence.
- `DOPS-073` → 5E/#254: a request outcome is not a system-level ability to pause the narrowest safe scope and broaden containment.
- `GRAG-051` → 5E/#254: a challenger requires a measured blocker or owner-approved bounded comparison purpose.
- `DEVAL-046` → 5E/#254: all six error classes are reported separately with counts, opportunity denominators, and rates.

## Decision state

Repository governance decides accepted source through owner control,
substantive review, required exact-head checks, resolved threads, and merge to
`main`. Non-inherited rows are `BOUND_BY_5A`; prior rows are
`INHERITED_ACCEPTED_AUTHORITY`. Digests identify content and do not form a
competing runtime admission system.

## Verification invariants

Tests reject missing or duplicate IDs; overlapping or incomplete delivery
groups; generic or competing anchors; nonexistent prior evidence; changed
counts; deferred rows without the exact issue; any `DOPS-*` row in 5D;
operational `DOPS-*` rows assigned before 5E; `TRI-028` assigned before durable
later reconciliation; material source/query/config changes reusing one Epoch;
cross-Epoch pooling; independent branches reported as a hybrid; incomplete
lineage reported as prior delivery; challenger work without its precondition;
incomplete six-class `DEVAL-046` measurement; production activation inside
Increment 5; and runtime GitHub approval or admission targets.
