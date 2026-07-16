---
status: accepted
date: 2026-07-15
last_updated: 2026-07-16
accepted_by_owner: 2026-07-16
---

# Local SQLite ledger in the integrated target architecture

## Decision

The long-lived editorial ledger in the integrated Newsroom will use SQLite on one supported local filesystem and host.

A dedicated non-agent command-service identity owns the database and authoritative object roots and is the only direct writer. Hermes, generative workers, projectors, publication-controller workers, target adapters and Admin clients may use authorised reads or submit authenticated commands, but may not independently mutate the ledger.

Each command carries its caller principal, allow-listed command type, idempotency identity and expected aggregate version or equivalent fence.

## Filesystem and transaction boundary

The SQLite file must never be opened directly from NFS, SMB, a cloud-synchronised directory or multiple hosts.

The operating profile defines and tests:

- foreign-key enforcement on every connection;
- WAL and synchronous settings;
- busy timeout and lock admission;
- bounded transaction duration;
- serial migration ordering;
- checkpoint policy;
- integrity checks;
- backup API and restore drills; and
- numerical limits and alerts for contention, disk, database size and recovery.

Small canonical manifests may remain as bounded transactional BLOBs within an approved size envelope. Governed source snapshots, passages, surface payloads, assets and larger artefacts use content-addressed local object storage. Objects are atomically installed, durably flushed and hash-verified before the ledger commits a reference.

## Why SQLite

SQLite is selected for the initial single-host, serial-command Newsroom because it keeps authority local, has no database-service or licence fee and fits the intended operational shape.

This decision:

- does not apply to the short-lived legacy `news_pool.sqlite3` discovery pool;
- does not make the Mac mini a public database server;
- does not weaken ADR 0001's engine-independent authority boundary; and
- does not prevent remote workers from submitting authenticated commands through the single command interface.

## Integrated GraphRAG boundary

SQLite is not a temporary Stage 1 database.

Canonical production schema v1 includes the stable identities, temporal and trust fields, proposal and admission records, ordered-event spine and projection metadata required by discovery, future evidence and publication, online serving and the governed graph, vector and full-text projections.

Neo4j or another graph engine remains a rebuildable projection. Neo4j/Graphiti qualification, graph-projector implementation and hybrid retrieval belong to the same initial delivery programme as the SQLite authority plane. Replacing a derived graph engine rebuilds a projection from the ledger and governed objects; it does not migrate editorial authority or require a second canonical domain model.

Shadow, replay and test environments may use separate physical SQLite files, but they must use the same canonical schema and event contract for the implemented scope rather than a disposable discovery-only semantic model.

## Recovery authority

Off-machine recovery authority is one coordinated, encrypted database-and-object recovery point, not an SQLite file alone.

The command writer establishes a ledger cutoff and consistent database snapshot, pins and copies every object reachable from that snapshot, publishes a content-addressed manifest only after verification and preserves those objects for the recovery point's lifetime.

Restore remains quarantined until:

- later deletion and tombstone decisions are applied;
- database, object and audit integrity pass;
- projection and queue state is reconciled; and
- automatic operation is separately authorised to resume.

Backup keys remain separate from backup storage and agent configuration. Publication credentials are excluded from the backup.

## Numerical admission gates

Before production activation, the owner must approve evidence-based limits and alerts for:

- transaction latency and duration;
- lock wait and write contention;
- command and projection backlog;
- database and bounded-BLOB size;
- disk headroom;
- backup freshness;
- recovery-point objective;
- recovery-time objective;
- restore window; and
- drill frequency.

These values are not inferred from acceptance of this ADR.

## Migration triggers

PostgreSQL or another transactional ledger must be reconsidered when the running system requires:

- direct multi-host or active-active writers;
- automatic database failover;
- security isolation unavailable within the single-host command boundary; or
- availability, durability, throughput, contention, recovery-point, recovery-time or restore-window requirements that SQLite persistently cannot meet inside the approved envelope.

Distributing operators or workers behind the one authenticated command interface is not itself a trigger.

Any later migration must preserve stable identities, immutable bytes, audit and ledger sequence, proposals and admissions, target operations, attempts, responses, observations, projection history, reconciliation history and verified recovery authority. It is a capacity and safety review, not a planned second stage.

## Completion record

The product owner accepted this ADR on 2026-07-16 together with ADR 0001 and the governed GraphRAG specification. Acceptance selects SQLite for the canonical single-host ledger while requiring GraphRAG work in the same initial programme. It authorises no code change, graph installation, source access, model call, spending, shadow run, canary or production activation.