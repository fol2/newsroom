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

The native engine uses the existing login Keychain. Its user-owned LaunchAgent
therefore runs in the logged-in user's `gui/$(id -u)` (Aqua) domain, with
`LimitLoadToSessionType=Aqua`. It remains a background engine; background work
does not require launchd's distinct Background security session. On the observed
macOS 26.6.2 host, all three credential classes read successfully from Aqua while
the same reads in Background returned interaction-not-allowed. Do not move the
native service to Background or add a credential bridge merely to avoid login.

The existing Neo4j server can remain in `user/$(id -u)` Background: it does not
read the engine's login-Keychain credentials. Retain the existing labels, paths,
stop/drain behaviour and singleton lock. Do not bootstrap the native engine
until offline authority maintenance has released its writer lock.

Disable the retired `com.jamesto.newsroom-control-plane` and
`com.jamesto.newsroom-graphiti-worker` LaunchAgents before a desktop login can
autoload them; boot out either if it is already loaded. Do not stop the separate
newsroom-hub UI or create a second native daemon.

Observe exact deployment, credential availability in the actual service domain,
process restart and continued scheduled work before claiming operation. A
successful `security unlock-keychain` command or desktop login alone is not a
credential-read test. This arrangement requires a user login after host reboot;
unattended pre-login operation is not proved and would require a separately
justified credential/lifecycle design, not silently weakened access controls.
