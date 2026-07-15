---
status: proposed
date: 2026-07-15
---

# Local SQLite ledger in the integrated target architecture

The long-lived editorial ledger in the new integrated Newsroom will use a local SQLite database with one logical command writer, foreign-key enforcement, WAL mode, an explicit durability policy, bounded contention, versioned migrations, integrity checks, off-machine backups and restore drills. Small canonical manifests and packages may remain as bounded transactional BLOBs. Governed source snapshots, surface payloads, assets and larger artefacts will use content-addressed local object storage installed and hash-verified before the ledger commits a reference.

SQLite is selected for a single-host, limited-writer Newsroom because it has no service or licence cost and keeps backup and recovery authority local. This decision does not apply to the short-lived `news_pool.sqlite3` discovery pool, does not make the Mac mini a public server, and does not change ADR 0001's engine-independent authority boundary.

SQLite is not a temporary Stage 1 database. Its first production schema must include the stable identity and ordered-event spine required by the publication outbox, online serving projection and governed graph projection. Neo4j/Graphiti evaluation and graph-projector implementation belong to the same delivery programme. Replacing a derived graph engine rebuilds a projection from the ledger; it does not migrate editorial authority or require a second canonical data model.

## Migration triggers

Reconsider PostgreSQL or another transactional ledger only when the running system requires multi-host writers, distributes operators and workers across hosts, persistently exceeds the agreed write-contention target, or cannot meet its approved recovery point, recovery time or restore window on SQLite. This is a future capacity trigger, not a planned second stage of the present programme. Any later migration must preserve stable identities, immutable bytes, audit sequence, outbox state and target acknowledgements.
