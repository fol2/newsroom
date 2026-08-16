# Increment 10A2 isolated transport authority

Schema v33 is reserved for an empty, isolated SQLite authority and is not registered as a production migration. It retains canonical Submission, Attempt and audit bytes, semantic idempotency, exact attempt coordinates, due-time selection and visible reconciliation obligations.

Submission and attempt writes use one `BEGIN IMMEDIATE` transaction. Immutable attempt/audit rows and retained-table delete triggers preserve replay. `TransportStore.status()` is the ordinary typed facade; the raw connection is private. No adapter, endpoint, credential or public writer route is exposed.
