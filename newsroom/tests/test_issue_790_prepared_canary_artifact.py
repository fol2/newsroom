"""Cross-process binding for the issue #790 PreparedCanary artefact."""

from __future__ import annotations

import inspect
import json
import shlex
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.issue_790_prepared_canary import (
    PREPARED_CANARY_RECORD_INVALID,
    PreparedCanaryError,
    consume_prepared_canary,
    prepare_issue_790_canary,
    prepared_canary_from_record,
    prepared_canary_record,
)
from newsroom.control_plane.issue_790_disposition import Issue790DispositionError
from newsroom.control_plane import issue_790_disposition as disposition
from newsroom.tests.test_issue_790_rehearsal_fixtures import (
    EVENT_13689,
    EXACT_HEAD,
    LEDGER_13689,
    OBSERVED_AT,
    build_rehearsal_stores,
)


def _prepare(stores, *, observed_at=OBSERVED_AT):
    return prepare_issue_790_canary(
        store=stores.work_unpublished,
        proving_store=stores.proving,
        plan=stores.plan,
        observed_at=observed_at,
        exact_head=EXACT_HEAD,
        role="preflight",
    )


def test_prepared_canary_record_round_trip(tmp_path: Path) -> None:
    prepared = _prepare(build_rehearsal_stores(tmp_path))

    record = prepared_canary_record(prepared)
    restored = prepared_canary_from_record(record)

    assert restored.as_decision_payload() == prepared.as_decision_payload()
    assert restored.record_digest == record["record_digest"]
    assert prepared_canary_record(restored) == record
    assert consume_prepared_canary(restored, expected=prepared) is restored


def test_prepared_canary_record_tamper_fail_closes(tmp_path: Path) -> None:
    prepared = _prepare(build_rehearsal_stores(tmp_path))
    record = prepared_canary_record(prepared)
    decision = dict(record["decision"])
    decision["exact_head"] = "0" * 40
    record["decision"] = decision

    with pytest.raises(PreparedCanaryError) as caught:
        prepared_canary_from_record(record)

    assert caught.value.failure_code == PREPARED_CANARY_RECORD_INVALID


def test_prepared_digest_is_stable_across_recheck_instant(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path)

    first = _prepare(stores)
    later = _prepare(stores, observed_at=OBSERVED_AT + timedelta(seconds=1))

    assert first.qualification_evidence != later.qualification_evidence
    assert first.as_decision_payload() == later.as_decision_payload()
    assert first.decision_digest == later.decision_digest


def test_qualification_identity_drift_is_part_of_decision(tmp_path: Path) -> None:
    prepared = _prepare(build_rehearsal_stores(tmp_path))
    qualification = dict(prepared.qualification_evidence or {})
    resolved = [dict(item) for item in qualification["resolved_units"]]
    resolved[0]["chunk_digest"] = "sha256:" + "ab" * 32
    qualification["resolved_units"] = resolved
    unsigned = {
        key: value
        for key, value in qualification.items()
        if key != "evidence_digest"
    }
    qualification["evidence_digest"] = digest_canonical(unsigned)
    expected = replace(prepared, qualification_evidence=qualification)
    expected = replace(
        expected,
        decision_digest=digest_canonical(expected.as_decision_payload()),
    )

    with pytest.raises(PreparedCanaryError) as caught:
        consume_prepared_canary(prepared, expected=expected)

    assert caught.value.failure_code == "PREPARED_CANARY_DIGEST_DRIFT"


def test_live_cli_loads_and_passes_prepared_canary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import issue_790_conservative_disposition as cli

    paths = {
        name: tmp_path / name
        for name in ("store", "proving", "plan", "prepared", "backup", "receipt")
    }
    paths["store"].write_bytes(b"store")
    paths["proving"].write_bytes(b"proving")
    paths["plan"].write_text("{}", encoding="utf-8")
    paths["prepared"].write_text(json.dumps({"record": "fixture"}), encoding="utf-8")
    sentinel = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(cli, "assert_issue_790_paths_disjoint", lambda *_: None)
    monkeypatch.setattr(cli, "load_issue_790_plan", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(cli, "prepared_canary_from_record", lambda value: sentinel)
    monkeypatch.setattr(cli, "write_issue_790_receipt", lambda *_args: None)

    def run(**kwargs):
        captured.update(kwargs)
        return {"canary_evidence_passed": True}

    monkeypatch.setattr(cli, "run_issue_790_canary", run)
    rc = cli.main(
        [
            "canary",
            "--store",
            str(paths["store"]),
            "--proving-store",
            str(paths["proving"]),
            "--plan",
            str(paths["plan"]),
            "--prepared-canary",
            str(paths["prepared"]),
            "--observed-at",
            OBSERVED_AT.isoformat(),
            "--receipt",
            str(paths["receipt"]),
            "--backup",
            str(paths["backup"]),
            "--repository-root",
            str(tmp_path),
            "--canary-event-id",
            "sha256:" + "ab" * 32,
            "--canary-ledger-seq",
            "13690",
            "--disposition-digest",
            "sha256:" + "cd" * 32,
        ]
    )

    assert rc == 0
    assert captured["prepared"] is sentinel


def test_canary_store_lock_rejects_concurrent_hardlink_executor(
    tmp_path: Path,
) -> None:
    stores = build_rehearsal_stores(tmp_path)
    alias = tmp_path / "unpublished-hardlink.sqlite3"
    alias.hardlink_to(stores.work_unpublished)
    lock_path = disposition._issue_790_canary_lock_path(alias)
    assert lock_path == disposition._issue_790_canary_lock_path(
        stores.work_unpublished
    )
    lock_path.parent.mkdir(mode=0o700, parents=False, exist_ok=True)
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import fcntl,os,sys;"
                "fd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600);"
                "fcntl.flock(fd,fcntl.LOCK_EX);"
                "print('LOCKED',flush=True);"
                "sys.stdin.readline();"
                "fcntl.flock(fd,fcntl.LOCK_UN);"
                "os.close(fd)"
            ),
            str(lock_path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "LOCKED"
        with pytest.raises(
            Issue790DispositionError,
            match="canary executor is already active",
        ):
            with disposition._exclusive_issue_790_canary_executor(
                stores.work_unpublished
            ):
                raise AssertionError("second executor acquired the lock")
    finally:
        if child.stdin is not None and child.poll() is None:
            child.stdin.write("release\n")
            child.stdin.flush()
        child.wait(timeout=5)
    assert child.returncode == 0


def test_canary_lock_follows_authority_and_canonical_store_gates() -> None:
    source = inspect.getsource(disposition.run_issue_790_canary)

    assert source.index("_require_approved_plan") < source.index(
        "_canonical_existing_file"
    ) < source.index("_exclusive_issue_790_canary_executor")
    assert "_require_approved_plan" not in inspect.getsource(
        disposition._run_issue_790_canary_locked
    )


def test_legacy_process_fence_matches_only_same_event_and_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stores = build_rehearsal_stores(tmp_path)
    other = tmp_path / "other.sqlite3"
    sqlite3.connect(other).close()
    marker = "python -m scripts.issue_790_conservative_disposition canary"
    event = EVENT_13689
    output = "\n".join(
        (
            f"101 {marker} --store {shlex.quote(str(stores.work_unpublished))} "
            f"--canary-event-id {event}",
            f"102 {marker} --store {shlex.quote(str(other))} "
            f"--canary-event-id {event}",
            f"103 {marker} --store={shlex.quote(str(stores.work_unpublished))} "
            f"--canary-event-id=sha256:{'ff' * 32}",
            "104 python unrelated.py",
        )
    )
    monkeypatch.setattr(
        disposition.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=output,
            stderr="",
        ),
    )

    assert disposition._other_issue_790_legacy_canary_process_ids(
        event_id=event,
        store=stores.work_unpublished,
    ) == (101,)


def _event_manifest_digest(path: Path, *, ledger_seq: int) -> str:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "SELECT manifest_digest FROM unpublished_graphiti_revision_events "
            "WHERE ledger_seq=?",
            (ledger_seq,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return str(row[0])


def test_recovery_rejects_a_valid_but_unpinned_old_backup(tmp_path: Path) -> None:
    stores = build_rehearsal_stores(tmp_path, unused_13689=True)
    pinned = tmp_path / "pinned.sqlite3"
    old = tmp_path / "old.sqlite3"
    pinned_digest = disposition._sqlite_backup(stores.work_unpublished, pinned)
    disposition._sqlite_backup(stores.work_unpublished, old)
    connection = sqlite3.connect(old)
    try:
        connection.execute("PRAGMA user_version=1")
        connection.commit()
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
    finally:
        connection.close()

    with pytest.raises(Issue790DispositionError, match="canary backup digest differs"):
        disposition._verified_pre_operation_canary_backup(
            old,
            event_id=EVENT_13689,
            ledger_seq=LEDGER_13689,
            manifest_digest=_event_manifest_digest(
                stores.work_unpublished, ledger_seq=LEDGER_13689
            ),
            expected_digest=pinned_digest,
        )


def test_backup_path_replacement_during_fd_verification_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stores = build_rehearsal_stores(tmp_path, unused_13689=True)
    backup = tmp_path / "backup.sqlite3"
    replacement = tmp_path / "replacement.sqlite3"
    expected_digest = disposition._sqlite_backup(stores.work_unpublished, backup)
    disposition._sqlite_backup(stores.work_unpublished, replacement)
    validate = disposition._require_pre_operation_canary_backup

    def replace_path(connection, **kwargs):
        replacement.replace(backup)
        return validate(connection, **kwargs)

    monkeypatch.setattr(
        disposition,
        "_require_pre_operation_canary_backup",
        replace_path,
    )
    with pytest.raises(
        Issue790DispositionError,
        match="canary backup changed during verification",
    ):
        disposition._verified_pre_operation_canary_backup(
            backup,
            event_id=EVENT_13689,
            ledger_seq=LEDGER_13689,
            manifest_digest=_event_manifest_digest(
                stores.work_unpublished, ledger_seq=LEDGER_13689
            ),
            expected_digest=expected_digest,
        )
