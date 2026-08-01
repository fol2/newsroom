# Increment 5 production retrieval traceability

**Status:** Exact 5A decision and delivery map
**Machine-readable source:** `newsroom/increment5/traceability.py`
**Verification:** `newsroom/tests/test_increment5a_traceability.py`
**Bound decision packet:** `sha256:4cc1de54a8d831358bbbe9b65c724d442401e84e3e72918df45807e140bdea56`
**Rows:** 114 unique requirements

## Reading the map

The table separates two independent facts:

- **Decision trace** says whether 5A binds the requirement, inherits an already accepted authority, or remains blocked until owner approval.
- **Delivery trace** says where executable implementation/evidence is actually delivered. A requirement bound in 5A is not falsely reported as a working retriever, tool, hydration path or actual-service qualification.

Every row names the canonical decision JSON pointer, implementation symbol, verification node and exact issue boundary. Tests reject duplicate requirements, unknown issue boundaries, missing families, false graph-free/fake production language, and changes to the expected delivery distribution.

## Coverage

The 114 rows cover:

- governed GraphRAG requirements `GRAG-030`–`GRAG-058` applicable to retrieval, hydration, bounded tools, degraded operation and qualification;
- native production requirements `GRPROD-001`–`GRPROD-032` applicable to the mandatory graph/vector/full-text subsystem;
- triage retrieval requirements `TRI-020`–`TRI-028`;
- evaluation requirements `DEVAL-003`, `DEVAL-010`–`014`, `DEVAL-040`–`047`, `DEVAL-050`–`054`, `DEVAL-064`, and `DEVAL-070`–`074`; and
- operational requirements `DOPS-001`, `002`, `007`, `010`–`016`, `026`, `030`–`037`, `040`, `043`–`048`, `050`, `052`, `054`, `060`, `064`, `067`, `070`, and `072`–`076`.

## Delivery distribution

| Delivery boundary | Count | Requirements |
|---|---:|---|
| Delivered in 5A / #250 | 26 | `DEVAL-010`, `DEVAL-011`, `DEVAL-012`, `DEVAL-051`, `DEVAL-072`, `DEVAL-073`, `DOPS-001`, `DOPS-002`, `DOPS-037`, `DOPS-064`, `DOPS-070`, `DOPS-074`, `DOPS-076`, `GRAG-051`, `GRAG-052`, `GRAG-053`, `GRAG-058`, `GRPROD-002`, `GRPROD-003`, `GRPROD-004`, `GRPROD-013`, `GRPROD-014`, `GRPROD-015`, `GRPROD-020`, `GRPROD-023`, `GRPROD-032` |
| Deferred to 5B / #251 | 2 | `GRAG-031`, `TRI-021` |
| Deferred to 5C / #252 | 7 | `DOPS-026`, `DOPS-060`, `DOPS-067`, `GRAG-033`, `GRAG-034`, `GRAG-035`, `TRI-022` |
| Deferred to 5D / #253 | 35 | `DOPS-010`, `DOPS-011`, `DOPS-012`, `DOPS-013`, `DOPS-014`, `DOPS-015`, `DOPS-016`, `DOPS-030`, `DOPS-031`, `DOPS-032`, `DOPS-033`, `DOPS-034`, `DOPS-040`, `DOPS-043`, `DOPS-044`, `DOPS-046`, `DOPS-047`, `DOPS-048`, `DOPS-050`, `DOPS-073`, `GRAG-032`, `GRAG-040`, `GRAG-041`, `GRAG-043`, `GRAG-044`, `GRAG-045`, `GRPROD-021`, `GRPROD-024`, `TRI-020`, `TRI-023`, `TRI-024`, `TRI-025`, `TRI-026`, `TRI-027`, `TRI-028` |
| Deferred to 5E / #254 | 39 | `DEVAL-003`, `DEVAL-013`, `DEVAL-014`, `DEVAL-040`, `DEVAL-041`, `DEVAL-042`, `DEVAL-043`, `DEVAL-044`, `DEVAL-045`, `DEVAL-046`, `DEVAL-047`, `DEVAL-050`, `DEVAL-052`, `DEVAL-053`, `DEVAL-054`, `DEVAL-064`, `DEVAL-070`, `DEVAL-071`, `DEVAL-074`, `DOPS-035`, `DOPS-036`, `DOPS-045`, `DOPS-052`, `DOPS-054`, `DOPS-072`, `DOPS-075`, `GRAG-046`, `GRAG-050`, `GRAG-054`, `GRAG-055`, `GRAG-056`, `GRAG-057`, `GRPROD-001`, `GRPROD-010`, `GRPROD-011`, `GRPROD-012`, `GRPROD-016`, `GRPROD-030`, `GRPROD-031` |
| Satisfied by Increment 4 / #144 | 4 | `DOPS-007`, `GRAG-030`, `GRAG-042`, `GRPROD-005` |
| Outside Increment 5 activation | 1 | `GRPROD-022` |

## Decision status

| Decision status | Count | Requirements |
|---|---:|---|
| Bound by 5A | 100 | `DEVAL-003`, `DEVAL-011`, `DEVAL-012`, `DEVAL-013`, `DEVAL-014`, `DEVAL-040`, `DEVAL-041`, `DEVAL-042`, `DEVAL-043`, `DEVAL-044`, `DEVAL-045`, `DEVAL-046`, `DEVAL-047`, `DEVAL-050`, `DEVAL-052`, `DEVAL-053`, `DEVAL-054`, `DEVAL-064`, `DEVAL-070`, `DEVAL-071`, `DEVAL-072`, `DEVAL-074`, `DOPS-010`, `DOPS-011`, `DOPS-012`, `DOPS-013`, `DOPS-014`, `DOPS-015`, `DOPS-016`, `DOPS-026`, `DOPS-030`, `DOPS-031`, `DOPS-032`, `DOPS-033`, `DOPS-034`, `DOPS-035`, `DOPS-036`, `DOPS-037`, `DOPS-040`, `DOPS-043`, `DOPS-044`, `DOPS-045`, `DOPS-046`, `DOPS-047`, `DOPS-048`, `DOPS-050`, `DOPS-052`, `DOPS-054`, `DOPS-060`, `DOPS-064`, `DOPS-067`, `DOPS-070`, `DOPS-072`, `DOPS-073`, `DOPS-074`, `DOPS-075`, `GRAG-031`, `GRAG-032`, `GRAG-033`, `GRAG-034`, `GRAG-035`, `GRAG-040`, `GRAG-041`, `GRAG-043`, `GRAG-044`, `GRAG-045`, `GRAG-046`, `GRAG-050`, `GRAG-051`, `GRAG-052`, `GRAG-053`, `GRAG-054`, `GRAG-055`, `GRAG-056`, `GRAG-057`, `GRPROD-001`, `GRPROD-002`, `GRPROD-003`, `GRPROD-004`, `GRPROD-010`, `GRPROD-011`, `GRPROD-012`, `GRPROD-013`, `GRPROD-014`, `GRPROD-015`, `GRPROD-020`, `GRPROD-021`, `GRPROD-023`, `GRPROD-024`, `GRPROD-030`, `GRPROD-031`, `TRI-020`, `TRI-021`, `TRI-022`, `TRI-023`, `TRI-024`, `TRI-025`, `TRI-026`, `TRI-027`, `TRI-028` |
| Inherited accepted authority | 5 | `DOPS-007`, `GRAG-030`, `GRAG-042`, `GRPROD-005`, `GRPROD-016` |
| Blocked pending owner approval | 9 | `DEVAL-010`, `DEVAL-051`, `DEVAL-073`, `DOPS-001`, `DOPS-002`, `DOPS-076`, `GRAG-058`, `GRPROD-022`, `GRPROD-032` |

The pending set is intentionally exact: `DEVAL-010`, `DEVAL-051`, `DEVAL-073`, `DOPS-001`, `DOPS-002`, `DOPS-076`, `GRAG-058`, `GRPROD-022`, and `GRPROD-032`. It prevents a proposed Evaluation Plan, profile or acceptance record from silently becoming execution, live shadow or activation authority.

## Issue boundaries

- **#250 / 5A:** canonical owner-decision proposal, typed component identities, strict production and fixture schemas, rights matrix, zero-runtime budgets, frozen Evaluation Plan, rollback and exact traceability.
- **#251 / 5B:** independently inspectable exact, full-text, vector and admitted-graph branches under the approved component identities.
- **#252 / 5C:** six closed authenticated named read-only tools and security containment.
- **#253 / 5D:** immutable Retrieval Contexts, authority hydration, freshness, explicit degraded outcomes, no false no-match and reconciliation.
- **#254 / 5E:** pre-registered ablation, bilingual/temporal/security/rights testing, authenticated actual-Neo4j qualification, graph/index-loss recovery and final evidence.

No row authorises raw Cypher, general graph/index access, model/content authority, graph-free production, external embedding calls, protected-content vectors, spending, shadow, canary or production activation.
