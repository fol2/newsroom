# Increment 9A2 isolated shadow deployment

## Status and authority boundary

This is the implementation contract for issue `#490`. It consumes the inert
9A1 scope and manifest only through `newsroom.increment9.deployment`, and may
exercise bounded readiness probes against the isolated shadow authority. It
does not authorise a source campaign, decision-bearing evaluation evidence,
provider or model calls, Evidence Intake, publication, canary, production
mutation or production activation.

The only credentials admitted here are readiness-scoped shadow credentials.
The Neo4j probe endpoint must resolve from an explicit `bolt://` or `neo4j://`
loopback URI, and credentials must be supplied separately. No credential value
is written to a plan, ledger, receipt or evidence artefact.

## Exact deployment identities

The canonical deployment plan binds:

- owner plan digest
  `sha256:92510c8b3989bb25cfce187b3477a71d8909a691ad8f3b88ae4917e456e9216d`;
- the exact 9A1 scope, manifest, effective-manifest, production snapshot and
  principal digests;
- SQLite authority `increment9-schema-v32-isolated-shadow-authority`;
- Neo4j database `increment9`, namespace `increment9_shadow`, disposable
  Increment-9-only volume and shadow writer principal;
- Graphiti proposal workspace
  `increment9-graphiti-proposal-workspace-v1`;
- `neo4j:5.26.2`, multi-architecture index digest and Apple arm64 manifest
  digest from OD-003;
- Neo4j Python driver `6.2.0` and Graphiti `0.29.3` wheel identities;
- 1024-dimension cosine vector generation, generation-scoped full text,
  governed ontology/mapping and admitted-generation-only projector;
- the five Effective Manifest code/config digests;
- exact credential classes, the prohibited publication adapter, protected
  artefact classes and default-deny egress policy;
- zero production reads after the frozen snapshot and absence of public,
  Evidence Intake and production adapters.

Every parser accepts exact canonical JSON only, rejects duplicate or unknown
fields, and reconstructs all closed enums and nested contracts. Readiness
observations bind cryptographically to the deployment plan, effective manifest,
probe identity and service class.

## Isolation and protected evidence

Readiness execution uses only `LOCAL_FILESYSTEM` and `LOCAL_NEO4J`. The future
campaign destinations remain configured but inactive. DNS pinning, TLS 1.3,
zero redirects, bounded response bodies, timeouts and request limits are frozen
for the later controller rather than exercised here.

The probe CLI writes canonical JSON atomically with mode `0600` into a caller
selected private directory; group/public-accessible evidence directories are
rejected and file plus directory updates are fsynced. The caller must provide
the encrypted-at-rest storage and lineage envelope required by the 9A1
protected artefact rules.
Secrets must stay in the Hermes broker or an equivalent local secret store;
only class, scope and digest metadata may enter evidence.

Materialisation creates one mode-`0700` root named exactly for the deployment,
with separate authority, backup, evidence, Graphiti proposal and object-store
directories. It takes one already-frozen SQLite export; it never connects to a
production path. The export is copied once, must match the manifest snapshot
digest, schema v32 fingerprint and complete 32-entry migration-history digest,
and is then read-only shadow input. A distinct v1 SQLite database stores the
append-only Increment 9 Epoch records and cannot alias the production schema.
Both databases receive verified backups. All files are mode `0600`.

The immutable materialisation receipt binds every relative path and file
digest without recording the absolute root. Unexpected files, links, modes,
schema drift or byte changes fail verification. Storage encryption and access
audit remain an explicit required probe; successful file creation does not
infer them.

## Readiness evidence inventory

A complete bundle contains the following exact ordered inventory:

1. `ARTIFACT_ENCRYPTION_ACCESS_AUDIT`
2. `BACKUP_RESTORE_RECONCILIATION`
3. `CAPACITY_MACM4`
4. `CREDENTIAL_VALUES_ABSENT`
5. `DNS_TLS_REDIRECT_BODY_TIMEOUT_RATE_BOUNDS`
6. `EGRESS_ALLOWLIST_BOUNDED`
7. `EGRESS_DEFAULT_DENY`
8. `EVIDENCE_INTAKE_PATH_DENIED`
9. `EXACT_COMPONENT_IDENTITIES`
10. `FILESYSTEM_SEPARATION`
11. `FULLTEXT_GENERATION_SCOPED`
12. `GRAPHITI_PROPOSAL_ONLY`
13. `KILL_SWITCH_AND_CONTAINMENT`
14. `NEO4J_AUTHENTICATED`
15. `NEO4J_DATABASE_NAMESPACE`
16. `PRODUCTION_CREDENTIAL_DENIED`
17. `PRODUCTION_NEO4J_DENIED`
18. `PRODUCTION_NONMUTATION`
19. `PRODUCTION_SQLITE_WRITE_DENIED`
20. `PUBLICATION_PATH_DENIED`
21. `PURGE_NO_RESURRECTION`
22. `RESTART_RECONCILIATION`
23. `SQLITE_ISOLATED_SCHEMA`
24. `TEARDOWN_ZERO_ORPHANS`
25. `VECTOR_GENERATION_1024_COSINE`

The six Neo4j/index/restart/teardown probes must be actual isolated-service
observations. Eighteen storage, backup, capacity, credential, egress,
filesystem, Graphiti, containment, production-denial, publication-denial,
purge and SQLite probes must be actual isolated-host observations. Only the
fixed DNS/TLS/redirect/body/timeout/rate contract is deterministic-only. Both
actual-service and actual-host probe inventories are explicit in the receipt.
A ready receipt additionally requires exact scope and manifest binding, the frozen
production snapshot as the before digest, byte-identical before/after
production digests, in-window chronology, every outcome `PASS`, and zero
secret, production mutation, public effect and orphan counts.

Missing, reordered, unavailable, failed, stale, cross-manifest, incorrectly
classified or post-expiry evidence yields `NOT_READY`. Missing evidence never
becomes an optimistic pass.

## Bounded commands

```bash
PYTHONPATH=. .venv/bin/python scripts/increment9_shadow_deployment.py \
  materialise --plan PLAN.json \
  --root PROTECTED_PARENT/increment9-deployment-ID \
  --production-snapshot FROZEN_V32_EXPORT.sqlite3 \
  --receipt-id RECEIPT_ID --created-at TIMESTAMP \
  --output PROTECTED_DIR/materialised-receipt.json

PYTHONPATH=. .venv/bin/python scripts/increment9_shadow_deployment.py \
  verify-materialised --plan PLAN.json \
  --receipt PROTECTED_DIR/materialised-receipt.json \
  --root PROTECTED_PARENT/increment9-deployment-ID \
  --output PROTECTED_DIR/materialised-verification.json

PYTHONPATH=. .venv/bin/python scripts/increment9_shadow_deployment.py \
  sqlite-backup-restore --output PROTECTED_DIR/sqlite.json

PYTHONPATH=. .venv/bin/python scripts/increment9_shadow_deployment.py \
  capacity --output PROTECTED_DIR/capacity.json

NEWSROOM_INCREMENT9_NEO4J_URI=bolt://localhost:7687 \
NEWSROOM_INCREMENT9_NEO4J_USERNAME=neo4j \
NEWSROOM_INCREMENT9_NEO4J_PASSWORD=SECRET_FROM_BROKER \
PYTHONPATH=. .venv/bin/python scripts/increment9_shadow_deployment.py \
  neo4j --output PROTECTED_DIR/neo4j.json

PYTHONPATH=. .venv/bin/python scripts/increment9_shadow_deployment.py \
  teardown --plan PLAN.json \
  --receipt PROTECTED_DIR/materialised-receipt.json \
  --root PROTECTED_PARENT/increment9-deployment-ID \
  --output PROTECTED_DIR/teardown.json
```

The Neo4j probe creates uniquely named, 9A2-labelled full-text and 1024-cosine
vector indexes plus one namespaced fixture node. It waits for the indexes,
observes their identities, removes the node, drops both indexes and verifies
zero remaining fixture nodes. Cleanup is attempted on both success and probe
failure. The command rejects a non-Community or non-`5.26.2` server.

## Backup, restore, teardown and rollback

The SQLite readiness probe installs schema v32 in a standalone database,
verifies the governed fingerprint, performs SQLite backup, and verifies the
restored copy. Neo4j remains a disposable projection; SQLite and governed
objects remain authority. Graph/index loss therefore requires delete-and-
rebuild plus watermark reconciliation, not restoration from Neo4j.

Teardown first re-verifies the complete closed inventory and every protected
digest, then removes only the plan-bound deployment root and checks that the
path did not resurrect. Teardown failure, residual probe state, a production digest change, a secret
value in evidence, a prohibited effect or an ambiguous cross-authority write
blocks the receipt and invokes OD-014 containment. Rollback targets the last
verified authority backup and last healthy Hermes build. A failed readiness
attempt remains retained evidence; an unchanged failed run is not converted to
a pass.

## Gate and handoff

Native blocker #512 / PRs #513 and #515 established and corrected the dedicated
exact-service gate. Bootstrap run `31921339865` proved Neo4j `5.26.2`
Community, the isolated `increment9` database, both online index types and
zero-orphan teardown. The first repository-probe integration run `31921673573`
then failed closed because the generic runner temporary directory was not a
private evidence parent. It uploaded no artefact and is not passing evidence.
PR #515 introduced the dedicated mode-`0700` parent without relaxing the
mode-`0600` file rule. Changed-head dedicated run `31921768763` passed through
upload and purge; standard SDLC run `31921768749` passed 4,008 outcomes with
zero failures, errors or required skips, including 42 authenticated service
cases and source integrity.

Final completeness review classified restart reconciliation as actual-service
rather than inferred evidence. PR #516 added a real restart, re-authentication,
exact identity check and post-restart zero-node/zero-index receipt. Dedicated
run `31922358934` passed the restart, two-receipt upload and purge; standard
SDLC run `31922358840` again passed 4,008 outcomes with zero failures, errors
or required skips, source integrity and 42 authenticated service cases.

Exact-head SDLC run `31922687091` subsequently failed closed because the 9A2
readiness module directly imported the official Neo4j driver outside the
repository's sole private production driver adapter. Its dedicated
actual-service run `31922686872` passed, but neither run is final pass evidence.
The changed head keeps the bounded query and result validation in the 9A2
module while the owned readiness CLI injects the locked driver factory. This
preserves the production import boundary without changing test selection,
timeouts or budgets.

Those GitHub-hosted x86 receipts are explicitly component-scoped; they are not
Mac M4/arm64 host proof. The separate `CAPACITY_MACM4` actual-host observation
remains mandatory.

The 9A2 delivery gate requires exact-head deterministic tests, source
integrity, authenticated isolated Neo4j `5.26.2` evidence, protected output,
production non-mutation, teardown, final substantive review with P1 = 0 and
material P2 = 0, and zero unresolved threads. The service gate is a readiness
probe only. A `READY_FOR_9B2_CONTROLLER_QUALIFICATION` receipt still records
that runtime campaign authority is required and hands only controller
qualification eligibility to #492.
