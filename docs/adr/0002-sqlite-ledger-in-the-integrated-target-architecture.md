---
status: proposed
date: 2026-07-15
---

# Local SQLite ledger in the integrated target architecture

The long-lived editorial ledger in the new integrated Newsroom will use SQLite on one supported local filesystem and host. A dedicated non-agent command service identity will own the database and authoritative object roots and will be the only direct writer. Hermes, generative workers, projectors, publication-controller workers, target adapters and Web Admin clients may use authorised reads or submit authenticated commands, but may not independently mutate the ledger. Each command must carry its caller principal, allow-listed command type, idempotency identity and expected aggregate version or equivalent fence.

The SQLite file must never be directly opened from NFS, SMB, a cloud-synchronised directory or multiple hosts. The operating profile will enforce foreign keys on every connection and define WAL and synchronous settings, busy timeout, bounded transactions, serial migration ordering, lock admission, checkpoint policy, integrity checks, backup API and restore drills. Small canonical manifests may remain as bounded transactional BLOBs within an approved size envelope. Governed source snapshots, surface payloads, assets and larger artefacts will use content-addressed local object storage atomically installed, durably flushed and hash-verified before the ledger commits a reference.

SQLite is selected for a single-host, serial-command Newsroom because it has no service or licence cost and keeps authority local. This decision does not apply to the short-lived `news_pool.sqlite3` discovery pool, does not make the Mac mini a public server, and does not change ADR 0001's engine-independent authority boundary. Remote workers that submit commands through the authenticated interface do not by themselves make the ledger multi-host.

SQLite is not a temporary Stage 1 database. Canonical production schema v1 must include the stable identity and ordered-event spine required by target operations, online-serving projection and governed graph projection. Normal versioned migrations may evolve that schema without changing its authority boundary. Neo4j/Graphiti evaluation and graph-projector implementation belong to the same delivery programme. Replacing a derived graph engine rebuilds a projection from the ledger; it does not migrate editorial authority or require a second canonical data model.

Off-machine recovery authority is one coordinated, encrypted database-and-object recovery point, not an SQLite file alone. The command writer establishes a ledger cutoff and consistent database snapshot, pins and copies every object reachable from that snapshot, publishes a content-addressed manifest only after verification and preserves those objects for the recovery point's lifetime. Restore remains quarantined until later deletion and tombstone decisions are applied and database, object and audit integrity pass. Backup keys remain separate from backup storage and agent configuration, and publication credentials are excluded.

Before production activation, the owner must approve numeric limits and alerts for transaction latency, lock wait, transaction duration, write contention, operation and projection backlog, database and BLOB size, disk headroom, backup freshness, recovery point objective, recovery time objective, restore window and drill frequency.

## Migration triggers

Reconsider PostgreSQL or another transactional ledger when the running system requires direct multi-host or active-active writers, automatic database failover, security isolation unavailable within the single-host boundary, or availability, durability, throughput, lock-contention, recovery point, recovery time or restore-window requirements that SQLite persistently cannot meet inside the approved operating envelope. Distributing operators or workers behind the one authenticated command interface is not alone a trigger. This is a capacity and safety review, not a planned second stage. Any later migration must preserve stable identities, immutable bytes, audit and ledger sequence, target operations, attempts, responses, observations, reconciliation history and verified recovery authority.
