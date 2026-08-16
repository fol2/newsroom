# Increment 9A1 isolated shadow authority boundary

- **Status:** contract implemented; no deployment or runtime effect
- **Issue:** [#489](https://github.com/fol2/newsroom/issues/489)
- **Planning authority:** [#488](https://github.com/fol2/newsroom/issues/488)
- **Module:** `newsroom.increment9.shadow_contracts`
- **Schemas:** `newsroom.increment9.shadow-scope.v1` and `newsroom.increment9.shadow-manifest.v1`

## Purpose

9A1 makes the separation between production authority and a later isolated
shadow machine-readable. The contracts are immutable values. Loading, parsing,
validating or merging them performs no deployment, credential lookup, network
request, provider/model call, spend, campaign, publication or production
mutation.

The contracts bind the owner-approved Increment 9R plan digest. A scope that
drifts from OD-002, OD-003, OD-004, OD-012, OD-013 or OD-014 fails closed.

## Authority separation

`ProductionAuthorityReference` identifies one schema-v32 SQLite authority
snapshot/export, its schema fingerprint, migration digest, cutoff and watermark.
It grants one snapshot reference, not a production writer.

`ShadowAuthorityIdentity` names a separate SQLite identity, Neo4j database and
namespace, Graphiti proposal workspace and shadow principal. A `ShadowScope`
cannot change those owner-bound identities or alias a production namespace.

Construction is deliberately absent from the public contract. The private
`_admit_for_later_deployment` seam returns only a content-addressed manifest
identity receipt for 9A2. It contains no raw connection, credential or effect
capability and does not itself authorise deployment.

## Effect closure

The complete allowed set is:

- one production snapshot read;
- isolated shadow-authority writes;
- proposal-workspace writes;
- protected-artifact writes; and
- evaluation-record writes.

The closed prohibited set includes publication, Discord/public dispatch,
Evidence Intake, canary, production SQLite/Neo4j writes, production-authority
mutation, production activation and legacy retirement. Unknown effects cannot
enter canonical bytes.

The explicit outcomes are `AVAILABLE`, `STALE`, `PARTIAL`, `UNAVAILABLE`,
`RIGHTS_BLOCKED` and `POLICY_BLOCKED`. Missing or blocked work therefore cannot
collapse into a successful no-match result.

## Principal, purpose, credentials and egress

`ShadowAccessBoundary` binds one purpose, principal digest, the complete
owner-approved credential-class inventory, an egress-policy digest and an
artefact-policy digest. It is descriptive: every no-effect flag remains false.
A later manifest must carry the same principal, purpose and policy identities.
No secret value may appear in the contract.

## Production equivalence

Every OD-013 material and non-material difference is represented by one typed,
unique `ProductionDifference`. Reports must retain the associated inference
limit; the shadow establishes only component-scoped equivalence and does not
establish traffic scale, high availability, production identity or untested
credential behaviour.

## Protected artefacts

All OD-012 protected classes are present exactly once. Every rule requires
lineage and encryption at rest and supplies a positive retention ceiling and
rights-revocation purge deadline. The inventory covers raw HTTP, governed
passages, model and embedding input/output, review research, credential
metadata, rights records, backups and the audit ledger.

9A2 must build storage and purge mechanisms from these rules. 9A1 neither
creates storage nor claims that purge/restore has been exercised.

## Version, expiry, closure and stop

A `ShadowScope` has exact creation and expiry instants. A `ShadowManifest` has a
fixed schema/version, content digest, positive ordinal and exact predecessor.
The manifest cannot predate or outlive its scope. `validate_manifest_chain`
requires a contiguous, chronological, content-addressed chain.

Closure reasons include expiry, owner stop, kill switch, rights withdrawal,
budget exhaustion, manifest supersession, containment failure and completed
teardown. OD-014 P0/P1 kill, revoke, notify and containment deadlines are bound
exactly.

An early stop blocks all later decision-bearing campaign phases. Autonomous
containment, restore and recovery-proof work may continue only as
non-decision-bearing evidence; it cannot reclassify a failed Epoch.

## Canonical and tamper rules

Both public documents:

- use restricted canonical JSON bytes;
- reject duplicate and unknown object names;
- reject non-canonical whitespace or encodings;
- expose SHA-256 content identities;
- use closed enum inventories; and
- revalidate every nested owner-bound value after parsing.

## Completion boundary

9A1 completion establishes contracts only. It does not establish:

- an isolated deployment or actual-service proof;
- credential availability or secret separation;
- default-deny network enforcement;
- backup, restore, purge or teardown execution;
- a live source/provider/model request; or
- decision-bearing shadow evidence.

Those remain gated work for #490 and later atoms.
