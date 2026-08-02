# Increment 5 production-retrieval operating contract

This runbook applies to the implementation and non-production qualification authorized by 5A. Production activation is outside Increment 5.

## Profiles

`FIXTURE_REPLAY` is hermetic and uses repository-safe fixtures plus deterministic fixed-point vectors. It has zero external calls and is not qualification evidence.

`PRODUCTION_SHAPED_QUALIFICATION` uses the real retriever/index/hydration/degradation code, an authenticated Neo4j service and a signed rights-cleared dataset manifest. It remains non-production: no live source, model load, provider credential/spend, protected content, write authority, public effect or activation.

## Schema surfaces

The contract records structural profile-schema digests. The public profile schema files are self-contained reviewed bindings: each is deterministically derived from the exact structural schema and fixes the accepted contract plus every component digest with JSON-Schema `const` values.

Use the reviewed-binding schemas for manifest exchange or standalone validation. The explicitly named `*_structural_v1.schema.json` schemas exist to keep contract identity non-circular and are not sufficient by themselves to establish an accepted manifest identity.

Neither profile is a production deployment profile. Production rejection of fake, disabled or omitted GraphRAG and production configuration build/readiness validation remain 5E controls.

## Hard limits

- 5,000 ms end-to-end;
- 8 results per branch;
- 12 retained candidates;
- 262,144 response bytes;
- zero external calls;
- zero provider cost;
- graph depth 2, fan-out 32 and date window 31 days.

A breach produces explicit degradation or incompleteness. Limits are never silently widened.

## Outcomes

- `COMPLETE`: every mandatory branch, hydration, rights, freshness, collision and reconciliation check completed.
- `DEGRADED`: a named optional contribution failed but the bounded result remains useful.
- `INCOMPLETE`: missing authority bytes, collision result, mandatory branch or reconciliation prevents complete meaning.
- `POLICY_BLOCKED`: rights, scope or security policy forbids the material.
- `STALE`: the selected generation or hydrated authority is outside the admitted freshness boundary.
- `UNAVAILABLE`: no safe bounded response can be produced.

An empty result is no-match only with `COMPLETE`.

## Security boundary

Only the six contract-named tools may expose retrieval. They accept typed bounded inputs and return bounded Retrieval Contexts. Prohibited surfaces include raw/generated Cypher, caller Lucene syntax, arbitrary indexes/predicates/depth/fan-out/windows, write sessions, model/provider credentials, unrestricted source text and projection text as factual payload.

Serving requires the active complete generation, zero open projection gaps and zero dead letters. A stale or incomplete projection cannot be relabelled no-match or replaced by a graph-free contract.

## Rights and purge

Rights are checked at read time. Personal data, secrets, rights-restricted text and public governed source text cannot enter the v1 vector lane.

Withdrawal, tombstone or revocation stops new derivative creation. Purge removes every passage, full-text entry, fixed-point vector, graph derivative and cached context, records derivative identities and a purge receipt, rebuilds an isolated generation and proves non-resurrection before selection. Any residual blocks qualification.

## Rollback and recovery

Rollback selects a prior generation only when exact component identities still match, rights remain current, freshness/completeness pass and no purged material returns. There is no graph-free rollback, history rewrite or same-generation contract edit.

Otherwise return `UNAVAILABLE`, `STALE` or `POLICY_BLOCKED` until a safe isolated generation qualifies.

## Evidence and observability

Retain bounded records for route/profile/generation identity; branch status, duration, count and truncation; fusion/dedup counts; hydration, rights and collision results; unique qualification case IDs; mandatory query-family, required-case-type and required-slice exposure counts; temporal-correctness error count; rebuild-reproducibility mismatch count; top-level outcome; response bytes; zero-call/zero-cost counters; component identities; and purge/rebuild linkage. Both zero-tolerance counts must be zero.

Qualification is not evaluable unless the frozen partition contains 100 unique cases, the three family floors are 30/30/40, every required case type has at least 10 cases and every required slice has at least 20 relevant cases. Cross-family case reuse and calibration counting are prohibited. Any exposure shortfall is retained as `NOT_EVALUATED`; operators cannot choose a denominator after seeing results.

Logs must exclude secrets, credentials, prohibited source expressions and protected payloads.

Stop the affected profile and preserve evidence on any successful write, generated query execution, external call/spend, model load, protected-content vector, authority bypass, false no-match, purge residual, identity mismatch, component drift or silent branch loss. Recovery requires a new isolated generation and fresh applicable qualification evidence. CI success alone never activates production.
