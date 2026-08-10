# Authority migration compatibility harness

## Purpose

`newsroom/tests/authority_migration_compatibility.py` is the canonical test-only
builder and inspector for retained empty SQLite authority schemas from v13
through the production `SCHEMA_VERSION` (v22 at this release).
It gives a future checked migration one stable way to prove that its exact
predecessors still upgrade. It does not add a production migration, change a
schema statement, recalculate a production checksum, or replace the existing
Graphiti downgrade helpers.

The harness builds old schemas forwards from the production SQL statement
tuples. It never creates a predecessor by deleting objects from the current
schema. Migration selection is by each record's declared `version` and `name`,
never by a relative list-tail offset.

## Authority and fail-closed gates

At import, the harness binds every record in
`newsroom.authority.migrations.MIGRATIONS` to its named authoritative
`*_MIGRATION_STATEMENTS` tuple. Both the registry and
`EXPECTED_MIGRATION_HISTORY` must equal the independent literal
`PINNED_MIGRATION_HISTORY` for every version from v1 through current. The
harness also recomputes each authoritative statement-tuple digest and requires
the corresponding literal checksum. The registry must be unique, consecutive
and complete. Missing, extra or drifted records and statement bindings fail
closed. A new checked migration must append its literal full-history record.

`build_exact_prefix(path, version)` requires a new file path and supports the
range from explicit `RETAINED_MIN_VERSION = 13` through the current production
schema version. It applies only migrations v1 through the requested
named version, inserts their checked history, sets `PRAGMA user_version`, and
commits everything in one exclusive transaction. A statement failure rolls the
entire empty build back.

`inspect_exact_prefix(path)` opens the database read-only and compares all of:

- the exact `PRAGMA user_version`;
- ordered migration versions, names and checksums, with no missing or extra row;
- the canonical full-history fingerprint rendered in the release matrix;
- the production normalised schema fingerprint as an additional compatibility
  signal;
- the complete ordered `sqlite_master` inventory with exact storage types:
  `type`, `name` and `tbl_name` must be built-in strings while `sql` must be a
  built-in string or `NULL`, including SQLite automatic indexes, and its
  canonical fingerprint (`NULL` remains JSON `null`);
- `PRAGMA foreign_key_check`, which must return no row; and
- `PRAGMA quick_check`, which must return exactly `ok`.

Changing migration history or leaking a table, view, trigger or index therefore
fails even when `user_version` was left unchanged. Versions outside the retained
range, including a newer schema, are rejected before an exact-cell comparison.
Raw SQL identity is intentionally not whitespace-normalised: normalising inside
a quoted SQLite error literal can hide a contract change. Likewise, an automatic
index whose catalog `sql` is changed from `NULL` to empty text is different even
when SQLite `quick_check` remains `ok`.

## API for the next migration

The intended v23 test flow is:

```python
database = tmp_path / "exact-v22.sqlite3"
before = build_exact_prefix(database, 22)

connection = sqlite3.connect(database)
connection.execute("PRAGMA foreign_keys=ON")
prepare_default_connection_backup(connection)
apply_pending_migrations(connection, applied_at=APPLIED_AT)
connection.close()

# The v23 change should inspect against its own new current-schema contract.
assert before.version == 22
```

Available typed helpers are:

- `migration_for_version(version)` and `history_through(version)` for explicit
  named lookup;
- `build_exact_prefix(path, version)` for a fresh file-backed empty prefix;
- `inspect_exact_prefix(path, expected_version=...)` for exact retained-schema
  validation;
- `prepare_default_connection_backup(connection)` for the durable v16-v21
  backup gate on a normal `sqlite3.connect(...)` connection;
- `canonical_cell(version)` for deterministic history, schema and inventory
  identity; and
- `render_compatibility_matrix()` for stable review pins.

The exported `CURRENT_VERSION`, `PREDECESSOR_VERSION`, `NEWER_VERSION`,
`UPGRADE_PREDECESSOR_VERSIONS` and `BACKUP_PREDECESSOR_VERSIONS` derive
behavioural boundaries from production `SCHEMA_VERSION` and the retained
minimum. `statement_symbol_for_version(CURRENT_VERSION)` identifies the current
authoritative SQL tuple for generic injected-failure proof. Only literal release
history, name/checksum and matrix pins require a manual append for a new version.

`statement_executor` on `build_exact_prefix` is an injection seam for atomic
failure tests only. Production execution should use the default.

## Backup and transaction invariant

Exact v16-v21 upgrades require the existing production backup gate. Open the
database with normal `sqlite3.connect(path)` transaction behaviour, enable
foreign keys, and ensure that no transaction is active before calling
`prepare_default_connection_backup`. The helper delegates to the production
backup implementation and verifies that backup preparation did not open a
transaction. `BEGIN EXCLUSIVE` must remain immediately available before the
upgrade.

For a multihop older upgrade, production retains one exact predecessor and one
SHA-256 sidecar at each destructive boundary:

```text
DATABASE.pre-v17.sqlite3          # exact v16
DATABASE.pre-v18.sqlite3          # exact v17
DATABASE.pre-v19.sqlite3          # exact v18
DATABASE.pre-v20.sqlite3          # exact v19
DATABASE.pre-v21.sqlite3          # exact v20
DATABASE.pre-v22.sqlite3          # exact v21
```

Each `.sha256` receipt contains the production `sha256:`-prefixed digest. The
focused proof reopens every backup through the same exact inspector.

The canonical restore rehearsal closes every connection after a successful
v21-to-v22 upgrade, proves the retained backup and digest, replaces the primary
file from that backup, and inspects it as exact v21. It then prepares the
retained gate again, re-upgrades, and inspects exact v22. This proves the empty
canonical schema rollback/restore path rather than only backup creation.

## Verification

Run the focused contract first:

```bash
uv run pytest -q newsroom/tests/test_authority_migration_compatibility.py
```

It pins deterministic cells from v13 through current, direct-v22/current
equivalence, every v13-v21 upgrade, multihop receipts, default-connection backup
behaviour, rollback after an injected migration failure, successful restore and
re-upgrade, inspector and production-migrator newer-version rejection without
byte changes, history tampering, leaked schema objects, quoted-literal
whitespace drift, catalog `NULL`/empty-text drift and the rendered matrix. A
future schema version must append its explicit full-history record, release
name/checksum and matrix row to the focused pins; the helper range itself
follows `SCHEMA_VERSION` without a hard-coded maximum.

Then run the retained v17-v22 migration selections required by the change under
review. Do not treat the harness as production readiness on its own: it covers
empty canonical schemas. Data-bearing migration and restore rehearsal,
concurrency, crash recovery and application reopen proof remain separate gates.
