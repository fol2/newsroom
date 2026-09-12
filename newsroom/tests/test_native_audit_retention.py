from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from newsroom.authority import HydrationRequest, ObjectAdmissionRequest
from newsroom.authority import audit_retention as retention
from newsroom.authority.persistence import AuthorityWriterBusy
from newsroom.control_plane.native_runtime import open_native_runtime
from newsroom.tests.test_native_runtime import _args
from scripts.prune_native_diagnostic_audit import main


_EXPECTED_PURPOSES = {
    "RETRIEVAL_PROJECTION": (
        "retrieval.native-document", "NATIVE_RETRIEVAL_DOCUMENT",
    ),
    "RETRIEVAL_VECTOR": (
        "retrieval.native-vector", "NATIVE_RETRIEVAL_EMBEDDING_VECTOR",
    ),
    "RETRIEVAL_ACCOUNTING": (
        "retrieval.native-embedding-receipt",
        "NATIVE_RETRIEVAL_EMBEDDING_RECEIPT",
    ),
    "TRIAGE_RETRIEVAL": (
        "retrieval.native-context", "NATIVE_RETRIEVAL_CONTEXT",
    ),
}


@pytest.fixture
def audit_fixture(tmp_path, monkeypatch):
    root = tmp_path / "newsroom"
    (root / "native").mkdir(parents=True, mode=0o700)
    (root / "increment4").mkdir(mode=0o700)
    args = _args(root / "native", monkeypatch)
    args.update(
        authority_path=root / "increment4/authority.sqlite3",
        object_root=root / "increment4/object_cas",
        intake_path=root / "native/evidence-intake.sqlite3",
        target_path=root / "native/private-serving.sqlite3",
        principal_id=retention._PRINCIPAL, authority_domain=retention._DOMAIN,
    )
    with sqlite3.connect(root / "unpublished_store.sqlite3") as conn:
        conn.execute("CREATE TABLE retained_receipts(payload BLOB)")
    accesses = {}
    with open_native_runtime(**args) as runtime:
        for purpose, (admission_type, _) in _EXPECTED_PURPOSES.items():
            admission = runtime.authority.objects.admit(
                ObjectAdmissionRequest(admission_type, purpose), b"retained bytes",
                proof=runtime.proof,
            ).admission
            accesses[purpose] = [runtime.authority.objects.hydrate(
                HydrationRequest(admission.admission_id, purpose), proof=runtime.proof,
            ).decision for _ in range(4)]
        source = runtime.authority.objects.admit(
            ObjectAdmissionRequest("evidence.source", "unrelated-source"), b"source",
            proof=runtime.proof,
        ).admission
        for _ in range(3):
            runtime.authority.objects.hydrate(HydrationRequest(source.admission_id, "evidence.source"), proof=runtime.proof)
    return root, args, accesses


def _connect(root):
    conn = sqlite3.connect(root / "increment4/authority.sqlite3")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ids(root, table="object_access_decisions"):
    with _connect(root) as conn:
        return {r[0] for r in conn.execute(f'SELECT "{retention._AUDIT_KEYS[table]}" FROM "{table}"')}


def test_prunes_real_native_diagnostics_preserves_latest_and_reopens(audit_fixture):
    root, args, accesses = audit_fixture
    with _connect(root) as conn:
        before_schema = retention._schema(conn)
        before_business = retention._scan_business(conn, exclude_audit=True)
        # Each read's scope digest is random-context-bound: it is not a reuse key.
        assert conn.execute("SELECT count(DISTINCT effective_scope_digest) FROM authorization_decisions").fetchone()[0] > 16
    report = retention.prune_native_diagnostic_audit(root, apply=True)
    assert report["committed"] and report["compacted"] and report["inode_preserved"]
    assert report["counts"]["eligible_access"] == 16
    assert report["counts"]["newest_access_retained"] == 4
    assert report["deleted"] == {name: 12 for name in retention._AUDIT_KEYS}
    remaining = _ids(root)
    assert len(remaining) == 7  # Four latest native reads and all source reads.
    for decisions in accesses.values():
        assert str(decisions[-1].access_decision_id) in remaining
        assert all(str(d.access_decision_id) not in remaining for d in decisions[:-1])
    with _connect(root) as conn:
        assert retention._schema(conn) == before_schema
        assert retention._scan_business(conn, exclude_audit=True) == before_business
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        for table in retention._AUDIT_KEYS:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute(f'DELETE FROM "{table}"')
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                key = retention._AUDIT_KEYS[table]
                conn.execute(f'UPDATE "{table}" SET "{key}"="{key}"')
    with open_native_runtime(**args) as runtime:
        for purpose, decisions in accesses.items():
            assert runtime.authority.objects.rehydrate(
                HydrationRequest(decisions[-1].admission_id, purpose),
                proof=runtime.proof,
            ).data == b"retained bytes"
    second = retention.prune_native_diagnostic_audit(root, apply=True)
    assert second["deleted"] == {name: 0 for name in retention._AUDIT_KEYS}


def test_dry_run_and_cli_default_do_not_change_database(audit_fixture, capsys):
    root, _, _ = audit_fixture
    path = root / "increment4/authority.sqlite3"
    before = path.read_bytes()
    assert main(["--data-root", str(root)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "dry-run" and not report["committed"]
    assert report["counts"]["superseded_access_candidates"] == 12
    assert path.read_bytes() == before


@pytest.mark.parametrize("purpose", ("RETRIEVAL_PROJECTION", "TRIAGE_RETRIEVAL"))
@pytest.mark.parametrize("table", tuple(retention._AUDIT_KEYS))
def test_external_receipt_preserves_each_security_reference(
    audit_fixture, table, purpose,
):
    root, _, accesses = audit_fixture
    access = accesses[purpose][0]
    with _connect(root) as conn:
        row = conn.execute("SELECT access_decision_id,authorization_decision_id,authorization_request_digest,authentication_context_id FROM object_access_decisions WHERE access_decision_id=?", (str(access.access_decision_id),)).fetchone()
    token = dict(zip(retention._AUDIT_KEYS, row))[table]
    with sqlite3.connect(root / "unpublished_store.sqlite3") as conn:
        # Exact BLOB references and JSON-embedded references are both roots.
        conn.execute("INSERT INTO retained_receipts VALUES (?)", (token.encode(),))
        conn.execute("INSERT INTO retained_receipts VALUES (?)", (json.dumps({"nested": [token]}).encode(),))
    retention.prune_native_diagnostic_audit(root, apply=True)
    assert token in _ids(root, table)


def test_cas_reference_and_foreign_key_root_preserve_older_reads(audit_fixture, monkeypatch):
    root, _, accesses = audit_fixture
    decisions = accesses["RETRIEVAL_PROJECTION"]
    cas_token, fk_token = (str(d.access_decision_id) for d in decisions[:2])
    escaped = "".join(f"\\u{ord(char):04x}" for char in cas_token)
    (root / "increment4/object_cas/retained-reference.json").write_text('{"access_decision_id":"' + escaped + '"}')
    with _connect(root) as conn:
        conn.execute("CREATE TABLE retained_access_reference(id TEXT PRIMARY KEY,access_id TEXT REFERENCES object_access_decisions(access_decision_id))")
        conn.execute("INSERT INTO retained_access_reference VALUES ('reference',?)", (fk_token,))
        children = retention._children(conn, "object_access_decisions")
        assert ("extraction_run_passages", "access_decision_id") in children
        assert ("graphiti_input_manifest_passages", "access_decision_id") in children
        assert ("hybrid_retrieval_context_hydrations", "access_decision_id") in children
        assert ("integrated_retrieval_contexts", "hydration_access_decision_id") in children
        before = retention._schema(conn)
    # A deliberately added FK root exercises discovery; production requires the
    # exact current native schema and does not permit arbitrary added tables.
    monkeypatch.setattr(retention, "_require_schema", lambda conn: None)
    report = retention.prune_native_diagnostic_audit(root, apply=True)
    assert report["deleted"]["object_access_decisions"] == 10
    assert {cas_token, fk_token} <= _ids(root)
    with _connect(root) as conn:
        assert retention._schema(conn) == before


def test_failure_rolls_back_deletes_and_trigger_changes(audit_fixture, monkeypatch):
    root, _, _ = audit_fixture
    before = {table: _ids(root, table) for table in retention._AUDIT_KEYS}
    with _connect(root) as conn:
        schema = retention._schema(conn)
    original = retention._index_children
    def fail_after_access_delete(conn, parent, indexes):
        if parent == "authorization_decisions":
            raise RuntimeError("injected post-delete failure")
        return original(conn, parent, indexes)
    monkeypatch.setattr(retention, "_index_children", fail_after_access_delete)
    with pytest.raises(RuntimeError, match="injected"):
        retention.prune_native_diagnostic_audit(root, apply=True)
    assert {table: _ids(root, table) for table in retention._AUDIT_KEYS} == before
    with _connect(root) as conn:
        assert retention._schema(conn) == schema
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_writer_busy_and_missing_external_root_fail_before_pruning(audit_fixture):
    root, args, _ = audit_fixture
    with open_native_runtime(**args):
        with pytest.raises(AuthorityWriterBusy):
            retention.prune_native_diagnostic_audit(root, apply=True)
    before = _ids(root)
    (root / "native/evidence-intake.sqlite3").unlink()
    with pytest.raises(FileNotFoundError):
        retention.prune_native_diagnostic_audit(root, apply=True)
    assert _ids(root) == before


def test_maintenance_fk_indexes_are_leading_and_removed(audit_fixture):
    root, _, _ = audit_fixture
    with _connect(root) as conn:
        schema = retention._schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        indexes = []
        for parent in retention._AUDIT_KEYS:
            children = retention._index_children(conn, parent, indexes)
            for table, column in children:
                plan = conn.execute(f'EXPLAIN QUERY PLAN SELECT 1 FROM "{table}" WHERE "{column}"=?', ("missing",)).fetchall()
                assert all("SCAN " not in str(row) for row in plan), (table, column, plan)
        assert indexes
        conn.rollback()
        assert retention._schema(conn) == schema


@pytest.mark.parametrize("table", tuple(retention._AUDIT_KEYS))
def test_external_canonical_digest_protects_exact_record(audit_fixture, table):
    root, _, accesses = audit_fixture
    access = accesses["RETRIEVAL_PROJECTION"][0]
    with _connect(root) as conn:
        row = conn.execute("SELECT access_decision_id,authorization_decision_id,authorization_request_digest,authentication_context_id FROM object_access_decisions WHERE access_decision_id=?", (str(access.access_decision_id),)).fetchone()
        identifier = dict(zip(retention._AUDIT_KEYS, row))[table]
        column = "canonical_record_digest" if table == "authorization_requests" else "canonical_digest"
        digest = conn.execute(f'SELECT "{column}" FROM "{table}" WHERE "{retention._AUDIT_KEYS[table]}"=?', (identifier,)).fetchone()[0]
    with sqlite3.connect(root / "unpublished_store.sqlite3") as conn:
        conn.execute("INSERT INTO retained_receipts VALUES (?)", (json.dumps({"canonical_reference": digest}).encode(),))
    retention.prune_native_diagnostic_audit(root, apply=True)
    assert identifier in _ids(root, table)


def test_cas_drift_aborts_and_schema_drift_is_rejected(audit_fixture, monkeypatch):
    root, _, _ = audit_fixture
    before = _ids(root)
    original = retention._delete_candidates
    def cas_drift(conn):
        result = original(conn)
        (root / "increment4/object_cas/unexpected.json").write_text("{}")
        return result
    monkeypatch.setattr(retention, "_delete_candidates", cas_drift)
    with pytest.raises(retention.AuditRetentionError, match="CAS changed"):
        retention.prune_native_diagnostic_audit(root, apply=True)
    assert _ids(root) == before
    with _connect(root) as conn:
        conn.execute("DROP TRIGGER immutable_authorization_requests_delete")
    with pytest.raises(retention.AuditRetentionError, match="schema"):
        retention.prune_native_diagnostic_audit(root, apply=True)
    assert _ids(root) == before


def test_distinct_byte_range_retains_its_own_latest_receipt(audit_fixture):
    root, args, accesses = audit_fixture
    admission_id = accesses["RETRIEVAL_PROJECTION"][0].admission_id
    with open_native_runtime(**args) as runtime:
        ranges = [runtime.authority.objects.hydrate(
            HydrationRequest(admission_id, "RETRIEVAL_PROJECTION", offset=1, length=4),
            proof=runtime.proof,
        ).decision for _ in range(2)]
    report = retention.prune_native_diagnostic_audit(root, apply=True)
    assert report["counts"]["newest_access_retained"] == 5
    assert str(ranges[-1].access_decision_id) in _ids(root)
    assert str(ranges[0].access_decision_id) not in _ids(root)


def test_compaction_failure_reports_committed_prune(audit_fixture, monkeypatch):
    root, _, _ = audit_fixture
    original = retention._schema
    calls = 0
    def fail_after_commit(conn):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("injected compaction verification failure")
        return original(conn)
    monkeypatch.setattr(retention, "_schema", fail_after_commit)
    report = retention.prune_native_diagnostic_audit(root, apply=True)
    assert report["committed"] and not report["compacted"]
    assert "Pruning committed" in report["compaction_error"]
    assert len(_ids(root)) == 7
