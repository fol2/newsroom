# Private native engine maintenance

Issue #981 owns the optimisation and its observed results. Normal source polling,
accounting, rights and private publication continue autonomously; this runbook
adds no per-story or per-version owner approval. Public exposure remains in
newsroom-hub.

## Obsolete read diagnostics

With the native service drained and its authority writer lock released:

```sh
python -m scripts.prune_native_diagnostic_audit --data-root "$NEWSROOM_DATA"
# Apply only the owner-authorised obsolete-audit retention scope:
python -m scripts.prune_native_diagnostic_audit --data-root "$NEWSROOM_DATA" --apply
```

Inspection is optional, not a mandatory duplicate full scan before application.
The command protects retained receipts, foreign keys, business content and the
latest exact reusable reads. Only superseded successful native retrieval
read diagnostics and their otherwise-unreferenced security chains are eligible.
Ordinary `hydrate` still records new deliveries; `rehydrate` authenticates and
checks current rights and bytes again, but can return its unchanged receipt.

Application uses SQLite's transaction rollback and in-place VACUUM, not a full
store backup. Ensure space for SQLite's temporary sort/journal/compaction files.
The report distinguishes committed pruning from unsuccessful compaction. A
compaction failure is not permission to rerun a live service or claim reclamation.
Check retained OPEN, source/canonical coverage, accounting, ACK/readback and
actual cold/continuous resource measurements after deployment.

## Supporting Neo4j footprint

For this small local private inventory, bound rather than auto-size memory from
the host's entire RAM. The initial measured configuration candidate is:

```properties
server.memory.heap.initial_size=128m
server.memory.heap.max_size=256m
server.memory.pagecache.size=64m
db.tx_log.rotation.size=16m
db.tx_log.rotation.retention_policy=2 files
```

Validate with `neo4j-admin server validate-config`. Neo4j owns pruning after a
successful checkpoint (`CALL db.checkpoint()`); never unlink transaction logs.
Report JVM/Neo4j separately from the Python daemon: these settings are not a
128MB combined-runtime or Cloudflare Workers compatibility claim. Increase a
bound only after an observed workload failure, not automatically.

References: [Neo4j transaction logging](https://neo4j.com/docs/operations-manual/current/database-internals/transaction-logs/)
and [memory configuration](https://neo4j.com/docs/operations-manual/current/performance/memory-configuration/).

## Background lifecycle

The native engine and its existing Neo4j service need the user's Background
launchd domain, not a GUI login session. Their user-owned LaunchAgent plists use
`LimitLoadToSessionType=Background`; bootstrap into `user/$(id -u)` and retain the
existing labels, paths, stop/drain behaviour and singleton lock. Do not resurrect
legacy Control Plane/Graphiti-worker/OpenClaw jobs or create a second daemon.

Observe the target domain, clean exact deployment and actual process before
claiming operation. Configuration is not proof of a future host reboot; retain
separate process restart and continued scheduled-work evidence.
