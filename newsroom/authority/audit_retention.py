"""Offline reclamation of superseded native retrieval-read diagnostics.

This is not retention of commands, admissions, accounting or source history.
The existing writer lock is held throughout, ordinary append-only triggers are
restored transactionally, and no authority database copy is made.
"""
from __future__ import annotations

from contextlib import ExitStack
import fcntl
import hashlib
import logging
import os
from pathlib import Path
import re
import resource
import shutil
import sqlite3
import struct
import sys
import time

from .canonical import canonical_json_bytes
from .migrations import (
    EXPECTED_MIGRATION_HISTORY, EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION, schema_fingerprint,
)
from .object_policy import HydrationPolicyContract
from .persistence import AuthorityWriterBusy

_AUDIT_KEYS = {
    "object_access_decisions": "access_decision_id",
    "authorization_decisions": "authorization_decision_id",
    "authorization_requests": "request_digest",
    "authentication_contexts": "authentication_context_id",
}
_PURPOSES = {
    "RETRIEVAL_PROJECTION": ("retrieval.native-document", "NATIVE_RETRIEVAL_DOCUMENT"),
    "RETRIEVAL_VECTOR": ("retrieval.native-vector", "NATIVE_RETRIEVAL_EMBEDDING_VECTOR"),
    "RETRIEVAL_ACCOUNTING": (
        "retrieval.native-embedding-receipt", "NATIVE_RETRIEVAL_EMBEDDING_RECEIPT",
    ),
}
_VERSION = "hermes-private-native-v1"
_PRINCIPAL = "newsroom.control-plane"
_DOMAIN = "newsroom.evaluation"
_EXTERNAL_DATABASES = (
    "unpublished_store.sqlite3", "native/retrieval.sqlite3",
    "native/evidence-intake.sqlite3", "native/private-serving.sqlite3",
)
# Opaque IDs can occur in nested/escaped JSON and receipts, not only FK columns.
_LOG = logging.getLogger(__name__)
_ASCII_ESCAPE = re.compile(rb"\\u00([0-7][0-9a-fA-F])")
_TOKEN = re.compile(rb"(?<![0-9a-f])(?:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|sha256:[0-9a-f]{64})(?![0-9a-f])")


class AuditRetentionError(RuntimeError):
    """No authorised maintenance change was committed unless explicitly stated."""


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _exact_path(path: Path, *, directory: bool = False) -> Path:
    path = path.absolute()
    if path.resolve(strict=True) != path or path.is_symlink():
        raise AuditRetentionError(f"maintenance path must be exact, not a symlink: {path}")
    if not (path.is_dir() if directory else path.is_file()):
        raise AuditRetentionError(f"maintenance path has the wrong type: {path}")
    return path


def _fingerprint(paths: tuple[Path, ...]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (str(p), s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        for p in paths for s in [p.stat()]
    )


def _tables(conn: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(row[0] for row in conn.execute(
        "SELECT name FROM main.sqlite_schema WHERE type='table' "
        "AND (name NOT LIKE 'sqlite_%' OR name='sqlite_sequence') ORDER BY name"
    ))


def _require_schema(conn: sqlite3.Connection) -> None:
    history = tuple(conn.execute("SELECT version,name,checksum FROM authority_migrations ORDER BY version"))
    if (conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
            or history != EXPECTED_MIGRATION_HISTORY
            or schema_fingerprint(conn) != EXPECTED_SCHEMA_FINGERPRINT):
        raise AuditRetentionError("authority schema or migration history differs")


def _schema(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT type,name,tbl_name,sql FROM main.sqlite_schema ORDER BY type,name"
    ).fetchall()
    return hashlib.sha256(canonical_json_bytes([list(row) for row in rows])).hexdigest()


def _reference_tokens(raw: bytes):
    # JSON may escape otherwise ordinary ASCII ID characters. Decoding only
    # ASCII escapes is conservative for non-JSON bytes and does not parse
    # protected source text or allocate a full nested document graph.
    if b"\\u00" in raw:
        raw = _ASCII_ESCAPE.sub(lambda match: bytes([int(match[1], 16)]), raw)
    return ((match[0].decode("ascii"),) for match in _TOKEN.finditer(raw))


def _encoded(value: object) -> bytes:
    if value is None:
        return b"n"
    if isinstance(value, bytes):
        return b"b" + value
    if isinstance(value, str):
        return b"s" + value.encode("utf-8")
    if isinstance(value, int):
        return b"i" + str(value).encode("ascii")
    if isinstance(value, float):
        return b"f" + struct.pack(">d", value)
    raise AuditRetentionError("unexpected SQLite value type")


def _scan_business(
    source: sqlite3.Connection, *, tokens: sqlite3.Connection | None = None,
    exclude_audit: bool = False,
) -> dict[str, object]:
    """Hash actual rows and collect references together, bounded by one row."""
    digest = hashlib.sha256()
    rows = byte_count = 0
    pending: list[tuple[str]] = []
    for table in _tables(source):
        if exclude_audit and table in _AUDIT_KEYS:
            continue
        digest.update(table.encode() + b"\0")
        columns = source.execute(f"PRAGMA main.table_info({_q(table)})").fetchall()
        primary = [c[1] for c in sorted(columns, key=lambda c: c[5]) if c[5]]
        order = ",".join(map(_q, primary)) if primary else "rowid"
        for row in source.execute(f"SELECT * FROM main.{_q(table)} ORDER BY {order}"):
            rows += 1
            digest.update(b"r")
            for value in row:
                raw = _encoded(value)
                byte_count += len(raw)
                digest.update(len(raw).to_bytes(8, "big"))
                digest.update(raw)
                if tokens is not None and isinstance(value, (str, bytes)):
                    pending.extend(_reference_tokens(value.encode("utf-8") if isinstance(value, str) else value))
                    if len(pending) >= 4096:
                        tokens.executemany("INSERT OR IGNORE INTO _audit_tokens VALUES (?)", pending)
                        pending.clear()
    if pending:
        assert tokens is not None
        tokens.executemany("INSERT OR IGNORE INTO _audit_tokens VALUES (?)", pending)
    return {"sha256": digest.hexdigest(), "rows": rows, "bytes": byte_count}


def _scan_cas(root: Path, conn: sqlite3.Connection) -> dict[str, object]:
    digest = hashlib.sha256()
    total = count = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise AuditRetentionError(f"CAS contains a symlink: {path}")
        if not path.is_file():
            continue
        count += 1
        digest.update(str(path.relative_to(root)).encode() + b"\0")
        # Token overlap covers the longest reference across chunk boundaries.
        tail = b""
        with path.open("rb") as stream:
            while chunk := stream.read(1_048_576):
                total += len(chunk)
                digest.update(chunk)
                conn.executemany(
                    "INSERT OR IGNORE INTO _audit_tokens VALUES (?)",
                    _reference_tokens(tail + chunk),
                )
                tail = (tail + chunk)[-512:]
    return {"sha256": digest.hexdigest(), "files": count, "bytes": total}


def _policies(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TEMP TABLE _audit_policies(purpose TEXT PRIMARY KEY, class TEXT, digest TEXT)")
    for purpose, (admission_type, object_class) in _PURPOSES.items():
        policy = HydrationPolicyContract(
            policy_id=f"{admission_type}-hermes-read", contract_version=_VERSION,
            implementation_version=_VERSION, purpose=purpose,
            required_scope="authority.objects.read",
            allowed_principal_ids=frozenset({_PRINCIPAL}),
            allowed_authority_domains=frozenset({_DOMAIN}),
            allowed_object_classes=frozenset({object_class}),
            allowed_uses=frozenset({purpose}),
            allowed_security_scopes=frozenset({"authority.retrieval"}),
            allowed_retention_scopes=frozenset({"authority.retrieval.retained"}),
            max_bytes=1_048_576,
        )
        row = conn.execute(
            "SELECT canonical_bytes FROM hydration_policy_contracts WHERE contract_digest=?",
            (policy.contract_digest,),
        ).fetchone()
        if row is None or bytes(row[0]) != canonical_json_bytes(policy.canonical_value()):
            raise AuditRetentionError(f"exact native policy is missing or differs: {policy.policy_id}")
        conn.execute("INSERT INTO _audit_policies VALUES (?,?,?)", (purpose, object_class, policy.contract_digest))


def _children(conn: sqlite3.Connection, parent: str) -> list[tuple[str, str]]:
    key = _AUDIT_KEYS[parent]
    return sorted({
        (table, fk[3])
        for table in _tables(conn)
        for fk in conn.execute(f"PRAGMA main.foreign_key_list({_q(table)})")
        if fk[2] == parent and fk[4] == key
    })


def _index_children(
    conn: sqlite3.Connection, parent: str, indexes: list[str],
) -> list[tuple[str, str]]:
    children = _children(conn, parent)
    for table, column in children:
        existing = [row[1] for row in conn.execute(f"PRAGMA main.index_list({_q(table)})") if not row[4]]
        if any(
            (info := conn.execute(f"PRAGMA main.index_info({_q(index)})").fetchone())
            and info[2] == column for index in existing
        ):
            continue
        name = f"_audit_maintenance_{len(indexes)}"
        conn.execute(f"CREATE INDEX {_q(name)} ON {_q(table)}({_q(column)})")
        indexes.append(name)
    return children


def _unreferenced(parent: str, children: list[tuple[str, str]]) -> str:
    key = _AUDIT_KEYS[parent]
    canonical = "canonical_record_digest" if parent == "authorization_requests" else "canonical_digest"
    tests = [
        f"NOT EXISTS(SELECT 1 FROM _audit_tokens p WHERE p.id={_q(parent)}.{_q(column)})"
        for column in (key, canonical)
    ]
    tests.extend(
        f"NOT EXISTS(SELECT 1 FROM {_q(table)} c WHERE c.{_q(column)}={_q(parent)}.{_q(key)})"
        for table, column in children
    )
    return " AND ".join(tests)


def _candidates(conn: sqlite3.Connection) -> dict[str, int]:
    conn.execute("""CREATE TEMP TABLE _audit_candidates AS
        SELECT a.rowid AS access_rowid,a.access_decision_id,a.canonical_digest,
               a.authentication_context_id,a.authorization_request_digest,
               a.authorization_decision_id,
               row_number() OVER (
                 PARTITION BY a.admission_id,a.hydration_policy_contract_digest,
                    a.principal_id,a.authority_domain,a.purpose,a.byte_offset,
                    a.allowed_bytes,a.state_cutoff_digest,
                    d.authorization_policy_version,d.scope_content_digest,
                    h.authentication_method,h.assurance_class,h.credential_binding_digest
                 ORDER BY a.decided_at DESC,a.rowid DESC
               ) AS reuse_rank
        FROM object_access_decisions a
        JOIN _audit_policies p ON p.purpose=a.purpose AND p.class=a.object_class
            AND p.digest=a.hydration_policy_contract_digest
        JOIN authorization_requests r ON r.request_digest=a.authorization_request_digest
            AND r.authentication_context_id=a.authentication_context_id
        JOIN authorization_decisions d ON d.authorization_decision_id=a.authorization_decision_id
            AND d.authorization_request_digest=a.authorization_request_digest
            AND d.authentication_context_id=a.authentication_context_id
        JOIN authentication_contexts h ON h.authentication_context_id=a.authentication_context_id
        WHERE a.principal_id=? AND a.authority_domain=? AND a.allowed_use=a.purpose
          AND a.security_scope='authority.retrieval'
          AND a.retention_scope='authority.retrieval.retained'
          AND r.principal_id=a.principal_id AND r.authority_domain=a.authority_domain
          AND r.operation_type='object:hydrate:' || a.purpose
          AND r.required_scope='authority.objects.read'
          AND h.principal_id=a.principal_id AND h.authority_domain=a.authority_domain
          AND d.allowed=1 AND d.reason_code='AUTHZ_ALLOWED'
          AND d.authorization_policy_version=?
    """, (_PRINCIPAL, _DOMAIN, _VERSION))
    eligible, newest = conn.execute("SELECT count(*),coalesce(sum(reuse_rank=1),0) FROM _audit_candidates").fetchone()
    conn.execute("DELETE FROM _audit_candidates WHERE reuse_rank=1")
    # Direct FKs are additionally checked at delete time. Token roots include
    # their actual TEXT columns as well as nested canonical representations.
    conn.execute("DELETE FROM _audit_candidates WHERE access_decision_id IN (SELECT id FROM _audit_tokens) "
                 "OR canonical_digest IN (SELECT id FROM _audit_tokens)")
    candidates = conn.execute("SELECT count(*) FROM _audit_candidates").fetchone()[0]
    return {"eligible_access": eligible, "newest_access_retained": newest,
            "externally_referenced_superseded": eligible - newest - candidates,
            "superseded_access_candidates": candidates}


def _delete_candidates(conn: sqlite3.Connection) -> dict[str, int]:
    triggers = []
    for table in _AUDIT_KEYS:
        name = f"immutable_{table}_delete"
        row = conn.execute("SELECT sql FROM main.sqlite_schema WHERE type='trigger' AND name=? AND tbl_name=?", (name, table)).fetchone()
        if row is None:
            raise AuditRetentionError(f"required immutable trigger is missing: {name}")
        triggers.append((name, row[0]))
    indexes: list[str] = []
    for name, _ in triggers:
        conn.execute(f"DROP TRIGGER {_q(name)}")
    deleted = {}
    children = _index_children(conn, "object_access_decisions", indexes)
    conn.execute(
        "DELETE FROM object_access_decisions WHERE rowid IN "
        "(SELECT access_rowid FROM _audit_candidates) AND " + _unreferenced("object_access_decisions", children)
    )
    deleted["object_access_decisions"] = conn.execute("SELECT changes()").fetchone()[0]
    # A candidate protected by a retained FK must not seed orphan-chain removal.
    conn.execute("DELETE FROM _audit_candidates WHERE access_rowid IN (SELECT rowid FROM object_access_decisions)")
    for table, candidate_column in (
        ("authorization_decisions", "authorization_decision_id"),
        ("authorization_requests", "authorization_request_digest"),
        ("authentication_contexts", "authentication_context_id"),
    ):
        children = _index_children(conn, table, indexes)
        key = _AUDIT_KEYS[table]
        conn.execute(
            f"DELETE FROM {_q(table)} WHERE {_q(key)} IN "
            f"(SELECT {_q(candidate_column)} FROM _audit_candidates) AND "
            + _unreferenced(table, children)
        )
        deleted[table] = conn.execute("SELECT changes()").fetchone()[0]
    for name in indexes:
        conn.execute(f"DROP INDEX {_q(name)}")
    for _, sql in triggers:
        conn.execute(sql)
    return deleted


def prune_native_diagnostic_audit(data_root: Path, *, apply: bool = False) -> dict[str, object]:
    """Dry-run by default; apply atomically prunes, then compacts in place.

    Required external roots are deliberately not optional CLI flags. The
    authority lifetime writer lock excludes ordinary engine writes throughout.
    No provider, CAS mutation, command/history deletion or backup is performed.
    """
    started = time.monotonic_ns()
    data_root = _exact_path(Path(data_root), directory=True)
    authority = _exact_path(data_root / "increment4/authority.sqlite3")
    cas = _exact_path(data_root / "increment4/object_cas", directory=True)
    external = tuple(_exact_path(data_root / name) for name in _EXTERNAL_DATABASES)
    if len({(p.stat().st_dev, p.stat().st_ino) for p in (authority, *external)}) != len(external) + 1:
        raise AuditRetentionError("authority and external reference stores must be distinct")
    before = authority.stat()
    wal = Path(str(authority) + "-wal")
    wal_before = wal.stat().st_size if wal.exists() else 0
    free_before = shutil.disk_usage(data_root).free
    lock = authority.with_name(authority.name + ".writer.lock")
    if lock.is_symlink():
        raise AuditRetentionError("writer lock path must not be a symlink")
    with ExitStack() as stack:
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        stack.callback(os.close, fd)
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise AuthorityWriterBusy("another authority writer is active") from exc
        conn = sqlite3.connect(authority.as_uri() + ("?mode=rw" if apply else "?mode=ro"), uri=True, isolation_level=None, timeout=0)
        stack.callback(conn.close)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA temp_store=FILE")
        conn.execute("PRAGMA cache_size=-8192")
        if apply:
            conn.execute("PRAGMA synchronous=FULL")
        conn.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        try:
            _require_schema(conn)
            schema = _schema(conn)
            conn.execute("CREATE TEMP TABLE _audit_tokens(id TEXT PRIMARY KEY) WITHOUT ROWID")
            _policies(conn)
            _LOG.info("AUDIT_RETENTION_STAGE retained_authority_references")
            scan_started = time.monotonic_ns()
            business = _scan_business(conn, tokens=conn, exclude_audit=True)
            _LOG.info("AUDIT_RETENTION_STAGE external_references")
            external_reports = {}
            readers = []
            for path in external:
                other = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
                stack.callback(other.close)
                other.execute("PRAGMA query_only=ON")
                other.execute("BEGIN")
                other.execute("SELECT name FROM sqlite_schema LIMIT 1").fetchone()
                readers.append((path, other))
            # Opening a WAL reader can create an empty sidecar itself. Capture
            # fingerprints after establishing every read snapshot, not before.
            observed_paths = tuple(p for base in external for p in (base, Path(str(base) + "-wal")) if p.exists())
            external_before = _fingerprint(observed_paths)
            for path, other in readers:
                external_reports[str(path.relative_to(data_root))] = _scan_business(other, tokens=conn)
            _LOG.info("AUDIT_RETENTION_STAGE cas_references")
            cas_paths = tuple(sorted(cas.rglob("*")))
            cas_before = _fingerprint(cas_paths)
            cas_report = _scan_cas(cas, conn)
            scan_ms = (time.monotonic_ns() - scan_started) // 1_000_000
            _LOG.info("AUDIT_RETENTION_STAGE classify_superseded_reads")
            candidates_started = time.monotonic_ns()
            counts = _candidates(conn)
            report: dict[str, object] = {
                "mode": "apply" if apply else "dry-run", "authority": str(authority),
                "reference_scan_ms": scan_ms,
                "candidate_classification_ms": (time.monotonic_ns() - candidates_started) // 1_000_000,
                "schema_sha256": schema, "business": business,
                "external_roots": external_reports, "cas": cas_report,
                "counts": counts, "database_bytes_before": before.st_size,
                "protected_tokens": conn.execute("SELECT count(*) FROM _audit_tokens").fetchone()[0],
                "committed": False, "compacted": False,
                "wal_bytes_before": wal_before,
                "free_disk_bytes_before": free_before,
                "temporary_database_bytes": conn.execute("PRAGMA temp.page_count").fetchone()[0] * conn.execute("PRAGMA temp.page_size").fetchone()[0],
            }
            if apply:
                _LOG.info("AUDIT_RETENTION_STAGE prune_and_verify")
                prune_started = time.monotonic_ns()
                report["deleted"] = _delete_candidates(conn)
                if _schema(conn) != schema or _scan_business(conn, exclude_audit=True) != business:
                    raise AuditRetentionError("retained business rows or schema changed; rolling back")
                if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise AuditRetentionError("retained foreign-key integrity differs; rolling back")
                if _fingerprint(observed_paths) != external_before or any(
                    Path(str(p) + "-wal").exists() and Path(str(p) + "-wal") not in observed_paths for p in external
                ):
                    raise AuditRetentionError("external reference store changed during maintenance")
                if tuple(sorted(cas.rglob("*"))) != cas_paths or _fingerprint(cas_paths) != cas_before:
                    raise AuditRetentionError("CAS changed during maintenance; rolling back")
                report["wal_bytes_before_commit"] = wal.stat().st_size if wal.exists() else 0
                conn.commit()
                report["committed"] = True
                report["prune_verify_ms"] = (time.monotonic_ns() - prune_started) // 1_000_000
                _LOG.info("AUDIT_RETENTION_STAGE committed_compact_in_place")
                compact_started = time.monotonic_ns()
                try:
                    checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    if checkpoint is not None and checkpoint[0]:
                        raise AuditRetentionError("authority WAL checkpoint is busy")
                    reclaimable = any(report["deleted"].values()) or conn.execute("PRAGMA freelist_count").fetchone()[0] > 0
                    if reclaimable:
                        conn.execute("VACUUM")
                    else:
                        report["compaction_skipped"] = "NO_RECLAIMABLE_PAGES"
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                        raise AuditRetentionError("post-compaction SQLite quick_check differs")
                    if _schema(conn) != schema:
                        raise AuditRetentionError("post-compaction schema differs")
                    report["compacted"] = bool(reclaimable)
                except Exception as exc:
                    report["compaction_error"] = f"Pruning committed; compaction failed: {exc}"
                report["compaction_ms"] = (time.monotonic_ns() - compact_started) // 1_000_000
            else:
                conn.rollback()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
    after = authority.stat()
    report.update({
        "database_bytes_after": after.st_size,
        "wal_bytes_after": wal.stat().st_size if wal.exists() else 0,
        "free_disk_bytes_after": shutil.disk_usage(data_root).free,
        "reclaimed_bytes": before.st_size - after.st_size,
        "inode_preserved": (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino),
        "wall_ms": (time.monotonic_ns() - started) // 1_000_000,
        "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * (1 if sys.platform == "darwin" else 1024),
    })
    if not report["inode_preserved"]:
        report["compaction_error"] = "Pruning committed; authority inode unexpectedly changed" if report["committed"] else "Authority inode unexpectedly changed during inspection"
    return report
