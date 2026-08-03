# Increment 5 production-retrieval operating contract

This runbook covers implementation and non-production qualification authorized
by 5A. Production activation is outside Increment 5.

## Profiles and validation

`FIXTURE_REPLAY` is hermetic, zero-call, and never qualification evidence.
`PRODUCTION_SHAPED_QUALIFICATION` may use actual Neo4j and a signed,
rights-cleared, repository-safe dataset, but it still has zero provider spend,
no model load, no protected content, no write authority, no public effect, and
no production activation.

Every 5E evidence manifest is canonical JSON validated inside the fresh
exact-head signed process with:

```text
python -I scripts/sdlc/increment5_profile_validator.py
```

The receipt binds the manifest digest and profile kind while stating
`authority_effect=NONE`, `qualification_authority_granted=false`, and
`production_activation_authorized=false`. It is necessary profile evidence,
never sufficient qualification evidence.

## Implementation ownership

- **5B / #251:** four independent retriever branches and exact receipts.
- **5C / #252:** six typed bounded read-only tools and tool-local authorization.
- **5D / #253:** deterministic fusion, authoritative dependency-root deduplication, complete six-stage discovery lineage, hydration, freshness, collision checks, and request-level outcomes.
- **5E / #254:** hybrid qualification, six-class error protocol, Operational Profiles, security, rights purge, full reconciliation recovery, scoped containment, rollback, rebuild, and actual-service evidence.

## Decision-bearing system

`HYBRID` is the sole qualification target. Exact-only, full-text-only,
vector-only, and admitted-graph-only are mandatory comparative ablations whose
quality cannot rescue `HYBRID`. A safety or rights violation in any executed
system blocks the affected scope.

## Hard limits and outcomes

Limits are 5,000 ms end-to-end, 8 results per branch, 12 retained candidates,
262,144 response bytes, zero external calls, zero provider cost, graph depth 2,
fan-out 32, and date window 31 days. Limits are never silently widened.

Outcomes are `COMPLETE`, `DEGRADED`, `INCOMPLETE`, `POLICY_BLOCKED`, `STALE`, or
`UNAVAILABLE`. An empty result is no-match only with `COMPLETE`.

## Security and DOPS-067

Only six named tools expose retrieval. Inputs and outputs are typed and bounded.
Raw/generated Cypher, caller Lucene syntax, arbitrary indexes or predicates,
writes, unrestricted source text, model/provider credentials, and projection
text as factual authority are prohibited.

5C proves tool-local caller, purpose, and scope authorization. 5E separately
proves least-privilege credential identity, exact source-access scope, secret
storage/redaction, approved destinations, and rejection of broader, substituted,
or unadmitted credentials, access, or destinations. A successful tool call is
not `DOPS-067` evidence.

## Reconciliation and DOPS-050

5D can reconcile one retrieval request through fusion, deduplication, hydration,
freshness, collision, and explicit outcomes. That is not the complete
operational reconciliation required by `DOPS-050`.

5E must detect and retain evidence for orphaned ownership, ambiguous calls,
duplicate delivery, stale work, and pending Handoffs. It must prove repair or an
explicit blocked/unresolved state without silently relabelling missing work as a
successful empty result.

## Scoped containment and DOPS-073

A per-request `DEGRADED`, `INCOMPLETE`, or `UNAVAILABLE` result is not a
system-level containment mechanism. 5E must prove the ability to pause the
narrowest safe affected scope and broaden containment when shared authority,
rights, security, or integrity is uncertain. Containment actions are
role-bounded, authenticated, audited, reversible where safe, and retained with
their trigger and exit criteria.

## Rights, purge, and recovery

Rights are checked at read time. Personal data, secrets, rights-restricted text,
and public governed source text cannot enter the v1 vector lane.

Withdrawal stops derivative creation. Purge removes passages, full-text entries,
fixed-point vectors, graph derivatives, and cached contexts; records derivative
identities and a purge receipt; rebuilds an isolated generation; and proves
non-resurrection before selection. Any residual blocks qualification.

Rollback selects a prior generation only when exact component identities match,
rights remain current, freshness and completeness pass, and no purged material
returns. Otherwise return `UNAVAILABLE`, `STALE`, or `POLICY_BLOCKED` until a
safe isolated generation qualifies.

## DEVAL-046 evidence

Retain separate counts, opportunity denominators, and ppm rates for false merge,
fragmentation, snowball absorption, false or missed development, duplicate
Candidate creation, and unnecessary Candidate creation. Every class requires at
least ten relevant preregistered cases. Cross-class pooling is prohibited; a
missing class is `NOT_EVALUATED`.

Candidate-related checks use read-only expected dispositions and create no
Candidate.

## Version, challenger, and operational admission

Before 5E qualifies a scope, Operational Admission enumerates exact source,
adapter, parser, Profile, worker, retrieval, and provider versions and proves
that every new version starts without inherited authority.

A second graph engine may be tested only after a retained measured blocker
against Neo4j Community plus Graphiti or an owner-approved bounded comparison
purpose. Without that record, evidence must prove one implementation only.

## Evidence and stopping conditions

Retain route/profile/generation identity, branch receipts, fusion/dedup/hydration
outcomes, rights and collision state, exposure counts, family metrics, six error
class reports, comparative results, temporal and rebuild counts, exact
components, purge/rebuild linkage, credential/source/destination evidence,
reconciliation and containment evidence, and final owner outcome.

Stop and preserve evidence on any successful write, generated query execution,
external call or spend, model load, protected-content vector, authority bypass,
false no-match, purge residual, identity drift, unadmitted version, unapproved
challenger, credential/access/destination violation, unresolved reconciliation,
failed containment, or silent branch loss. CI success alone never activates
production.
