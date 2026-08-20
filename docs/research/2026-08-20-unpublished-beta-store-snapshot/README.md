# Unpublished beta store snapshot (host freeze)

**Status:** Research evidence

**Canonical language:** English

**Issue:** [#722](https://github.com/fol2/newsroom/issues/722)

**Captured at:** 2026-08-20T10:54:41Z

**Git HEAD at capture:** `46d7d67` (#721)

**Implementation authority:** None

This package is a **small, rights-safe freeze** of the private unpublished beta so that `main` can show store status without the live SQLite or Neo4j files.

## Files

| File | Contents |
|---|---|
| `status.json` | Counts, Control Plane schedule, OD-011 cost policy, omissions |
| `status.sqlite3` | Same facts as queryable tables (`git add -f`; `*.sqlite3` is gitignored) |
| `graphiti_attempts.jsonl` | Unique Graphiti attempt rows (COMPLETE only at freeze) |
| `payloads_index.jsonl` | Surface Payload index: title, lineage, digests, body **length** only |
| `neo4j_eval_workspace.json` | Frozen names/facts from disposable group `newsroom-eval-proposal` |

## Omitted on purpose

- Article **bodies** (unpublished original copy)
- Live Neo4j Community database files and any **admitted** governed graph
- Keychain secrets and OpenRouter invoices
- Full proving-store observation bodies

The Neo4j file is a **point-in-time read** of the disposable Graphiti workspace. It is not GraphRAG admission and cannot be replayed as a database restore.
