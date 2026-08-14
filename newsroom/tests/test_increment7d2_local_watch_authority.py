from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.local_watch_migrations import (
    LOCAL_WATCH_MIGRATION_NAME,
    LOCAL_WATCH_SCHEMA_VERSION,
    LocalWatchBackupError,
    local_watch_backup_paths,
    prepare_local_watch_backup,
)
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)
from newsroom.increment7.local_watch import (
    LocalWatchClosureOutcome,
    LocalWatchVersionStatus,
)
from newsroom.increment7.local_watch_authority import (
    LOCAL_WATCH_AUTHORITY,
    LOCAL_WATCH_COMMAND,
    LOCAL_WATCH_REENTRY,
    LOCAL_WATCH_REENTRY_AUTHORITY,
    LocalWatchAction,
    LocalWatchAuthorityError,
    LocalWatchCommand,
    LocalWatchReadPort,
    LocalWatchReentry,
    LocalWatchReentryKind,
    open_local_watch_authority,
)
from newsroom.tests.authority_migration_compatibility import build_exact_prefix
from newsroom.tests.test_increment6f2_feedback import _supplemental_reentry
from newsroom.tests.test_increment7d1_local_watch_contracts import (
    D,
    _closure,
    _version,
    _watch,
)
from newsroom.tests.test_increment7e2_locality_no_activation import (
    _chain as _locality_chain,
)

_APPLIED = "2042-01-01T00:00:00.000000Z"
_ACTOR = D("b")


def _id(value: int) -> str:
    return str(uuid.UUID(int=value, version=4))


def _create_command(value: int = 100) -> LocalWatchCommand:
    watch = _watch()
    version = _version(watch)
    return LocalWatchCommand(
        command_id=_id(value),
        action=LocalWatchAction.CREATE,
        watch=watch,
        version=version,
        closure=None,
        reentry=None,
        expected_head_version_digest=None,
        request_id=_id(value + 1),
        actor_identity_digest=_ACTOR,
        idempotency_key=f"local-watch:create:{value}",
    )


def _append_command(
    create: LocalWatchCommand | None = None,
    value: int = 200,
) -> LocalWatchCommand:
    create = create or _create_command()
    first = create.version
    version = replace(
        first,
        watch_version_id=_id(value + 2),
        version_ordinal=2,
        previous_version_digest=first.canonical_digest,
        status=LocalWatchVersionStatus.EXTENDED,
        review_at="2042-01-03T00:00:00.000000Z",
        expires_at="2042-01-04T00:00:00.000000Z",
        change_reason="Owner-approved bounded extension.",
        recorded_at="2042-01-01T00:02:00.000000Z",
    )
    return LocalWatchCommand(
        command_id=_id(value),
        action=LocalWatchAction.APPEND_VERSION,
        watch=create.watch,
        version=version,
        closure=None,
        reentry=None,
        expected_head_version_digest=first.canonical_digest,
        request_id=_id(value + 1),
        actor_identity_digest=_ACTOR,
        idempotency_key=f"local-watch:append:{value}",
    )


def _close_command(
    append: LocalWatchCommand | None = None,
    *,
    value: int = 300,
    with_reentry: bool = True,
    conversion: bool = False,
) -> LocalWatchCommand:
    append = append or _append_command()
    closure = _closure(
        append.version,
        closure_id=_id(value + 2),
        outcome=(
            LocalWatchClosureOutcome.CONVERSION_PROPOSED
            if conversion
            else LocalWatchClosureOutcome.EXPIRED
        ),
        effective_at=(
            "2042-01-03T12:00:00.000000Z" if conversion else append.version.expires_at
        ),
        locality_coverage_proposal_digest=(
            _locality_chain()[2].digest if conversion else None
        ),
        recorded_at="2042-01-04T00:01:00.000000Z",
    )
    reentry = None
    if with_reentry:
        supplemental = _supplemental_reentry()
        reentry = LocalWatchReentry(
            reentry_id=_id(value + 3),
            watch_id=append.watch.watch_id,
            watch_version_id=append.version.watch_version_id,
            watch_version_digest=append.version.canonical_digest,
            closure_digest=closure.canonical_digest,
            reentry_kind=LocalWatchReentryKind.EXPIRY,
            supplemental_reentry=supplemental,
            supplemental_reentry_digest=digest_bytes(
                canonical_json_bytes(supplemental.canonical_value())
            ),
            actor_identity_digest=_ACTOR,
            recorded_at="2042-01-04T00:02:00.000000Z",
        )
    return LocalWatchCommand(
        command_id=_id(value),
        action=LocalWatchAction.CLOSE,
        watch=append.watch,
        version=append.version,
        closure=closure,
        reentry=reentry,
        expected_head_version_digest=append.version.canonical_digest,
        request_id=_id(value + 1),
        actor_identity_digest=_ACTOR,
        idempotency_key=f"local-watch:close:{value}",
    )


def test_command_and_reentry_are_strict_exact_governed_contracts() -> None:
    command = _close_command()
    assert LocalWatchCommand.from_canonical_bytes(command.canonical_bytes) == command
    assert (
        LocalWatchReentry.from_canonical_bytes(
            command.reentry.canonical_bytes  # type: ignore[union-attr]
        )
        == command.reentry
    )
    pretty = json.dumps(json.loads(command.canonical_bytes), indent=2).encode()
    with pytest.raises(LocalWatchAuthorityError, match="exact canonical JSON"):
        LocalWatchCommand.from_canonical_bytes(pretty)
    duplicate = command.canonical_bytes.replace(
        b'"command_id":',
        b'"command_id":"' + _id(999).encode() + b'","command_id":',
        1,
    )
    with pytest.raises(LocalWatchAuthorityError, match="duplicate object name"):
        LocalWatchCommand.from_canonical_bytes(duplicate)
    unknown = json.loads(command.canonical_bytes)
    unknown["activate_locality"] = False
    with pytest.raises(LocalWatchAuthorityError, match="fields or schema"):
        LocalWatchCommand.from_canonical_bytes(canonical_json_bytes(unknown))
    with pytest.raises(LocalWatchAuthorityError, match="digest differs"):
        replace(
            command.reentry,
            supplemental_reentry_digest=D("0"),
        )


def test_current_fresh_create_retains_v29_history_and_allocated_tables() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    apply_pending_migrations(connection, applied_at=_APPLIED)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert SCHEMA_VERSION >= LOCAL_WATCH_SCHEMA_VERSION == 29
    assert (
        EXPECTED_MIGRATION_HISTORY[LOCAL_WATCH_SCHEMA_VERSION - 1][1]
        == LOCAL_WATCH_MIGRATION_NAME
    )
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert schema_fingerprint(connection) == EXPECTED_SCHEMA_FINGERPRINT
    assert {
        "event_scoped_local_watches",
        "event_scoped_local_watch_versions",
        "event_scoped_local_watch_heads",
        "event_scoped_local_watch_closures",
    } <= tables
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def _create_v28(path) -> sqlite3.Connection:
    build_exact_prefix(path, 28)
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def test_v28_upgrade_requires_backup_rolls_back_and_preserves_restore_point(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "authority.sqlite3"
    connection = _create_v28(database)
    with pytest.raises(LocalWatchBackupError, match="requires prepared backup"):
        apply_pending_migrations(connection, applied_at=_APPLIED)
    backup, digest_path = local_watch_backup_paths(database)
    receipt = prepare_local_watch_backup(connection, backup)
    assert receipt.backup_path == backup
    assert digest_path.is_file()
    from newsroom.authority import migrations

    statements = migrations.LOCAL_WATCH_MIGRATION_STATEMENTS
    monkeypatch.setattr(
        migrations,
        "LOCAL_WATCH_MIGRATION_STATEMENTS",
        (statements[0], "CREATE TABLE deliberate_failure("),
    )
    with pytest.raises(sqlite3.OperationalError):
        apply_pending_migrations(connection, applied_at=_APPLIED)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 28
    assert schema_fingerprint(connection) == (
        "sha256:a613b28a765b36fa9110bcdc2b9bc565c6e2bc0ed8b8381d77f5fcd734c39c48"
    )
    monkeypatch.setattr(migrations, "LOCAL_WATCH_MIGRATION_STATEMENTS", statements)
    apply_pending_migrations(connection, applied_at=_APPLIED)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    restored = sqlite3.connect(backup, isolation_level=None)
    try:
        assert restored.execute("PRAGMA user_version").fetchone()[0] == 28
        assert restored.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        restored.close()


def test_checked_lifecycle_replays_restarts_expires_and_governed_reenters(
    tmp_path,
) -> None:
    path = tmp_path / "watch.sqlite3"
    create = _create_command()
    append = _append_command(create)
    close = _close_command(append)
    authority = open_local_watch_authority(path, applied_at=_APPLIED)
    first = authority.record(create.canonical_bytes)
    assert first.current_version == create.version
    assert first.closed is False
    assert authority.record(create.canonical_bytes) == first
    second = authority.record(append.canonical_bytes)
    assert second.versions == (create.version, append.version)
    assert second.closed is False
    final = authority.record(close.canonical_bytes)
    assert final.closure == close.closure
    assert final.reentry == close.reentry
    assert final.closed is True
    assert authority.record(close.canonical_bytes) == final
    port = authority.read_port()
    assert type(port) is LocalWatchReadPort
    assert port.command(create.command_id) == create
    assert port.command(append.command_id) == append
    assert port.command(close.command_id) == close
    authority.close()
    reopened = open_local_watch_authority(path, applied_at=_APPLIED)
    assert reopened.load(create.watch.watch_id) == final
    reopened.close()


def test_expiry_has_no_clock_effect_and_cas_terminal_boundaries_fail_closed(
    tmp_path,
) -> None:
    path = tmp_path / "watch.sqlite3"
    create = _create_command()
    append = _append_command(create)
    authority = open_local_watch_authority(path, applied_at=_APPLIED)
    assert authority.record(create.canonical_bytes).closed is False
    # The declared 2042 expiry is data; opening/loading does not close or re-enter.
    assert authority.load(create.watch.watch_id).closed is False
    authority.record(append.canonical_bytes)
    stale = replace(
        append,
        command_id=_id(500),
        request_id=_id(501),
        idempotency_key="local-watch:stale",
        version=replace(append.version, watch_version_id=_id(502)),
    )
    with pytest.raises(LocalWatchAuthorityError, match="command failed"):
        authority.record(stale.canonical_bytes)
    close = _close_command(append)
    authority.record(close.canonical_bytes)
    third_version = replace(
        append.version,
        watch_version_id=_id(503),
        version_ordinal=3,
        previous_version_digest=append.version.canonical_digest,
        recorded_at="2042-01-01T00:03:00.000000Z",
    )
    third = replace(
        append,
        command_id=_id(504),
        request_id=_id(505),
        idempotency_key="local-watch:after-close",
        version=third_version,
        expected_head_version_digest=append.version.canonical_digest,
    )
    with pytest.raises(LocalWatchAuthorityError, match="terminal"):
        authority.record(third.canonical_bytes)
    authority.close()


def test_conversion_closure_requires_exact_separate_proposal_and_no_reentry(
    tmp_path,
) -> None:
    path = tmp_path / "watch.sqlite3"
    create = _create_command()
    append = _append_command(create)
    conversion = _close_command(
        append,
        value=600,
        with_reentry=False,
        conversion=True,
    )
    proposal = _locality_chain()[2]
    authority = open_local_watch_authority(path, applied_at=_APPLIED)
    authority.record(create.canonical_bytes)
    authority.record(append.canonical_bytes)
    with pytest.raises(LocalWatchAuthorityError, match="exact separate"):
        authority.record(conversion.canonical_bytes)
    final = authority.record(
        conversion.canonical_bytes,
        conversion_proposal=proposal,
    )
    assert final.closure == conversion.closure
    assert final.reentry is None
    with pytest.raises(LocalWatchAuthorityError, match="supplemental re-entry"):
        replace(
            conversion,
            reentry=replace(
                _close_command(append).reentry,
                closure_digest=conversion.closure.canonical_digest,
            ),
        )
    authority.close()


def test_restart_detects_retained_tamper_with_restored_trigger(tmp_path) -> None:
    path = tmp_path / "watch.sqlite3"
    command = _create_command()
    authority = open_local_watch_authority(path, applied_at=_APPLIED)
    authority.record(command.canonical_bytes)
    authority.close()
    attacker = sqlite3.connect(path, isolation_level=None)
    trigger = attacker.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE name='immutable_event_scoped_local_watch_versions'"
    ).fetchone()[0]
    attacker.execute("DROP TRIGGER immutable_event_scoped_local_watch_versions")
    attacker.execute(
        "UPDATE event_scoped_local_watch_versions SET status='PAUSED' WHERE watch_id=?",
        (command.watch.watch_id,),
    )
    attacker.execute(trigger)
    attacker.close()
    reopened = open_local_watch_authority(path, applied_at=_APPLIED)
    with pytest.raises(LocalWatchAuthorityError, match="retained representation"):
        reopened.load(command.watch.watch_id)
    reopened.close()


def test_competing_identical_creates_converge_to_one_retained_watch(tmp_path) -> None:
    path = tmp_path / "watch.sqlite3"
    command = _create_command()
    authorities = [
        open_local_watch_authority(path, applied_at=_APPLIED) for _ in range(2)
    ]
    barrier = threading.Barrier(2)
    results: list[str] = []

    def writer(authority) -> None:
        barrier.wait()
        results.append(
            authority.record(command.canonical_bytes).current_version.canonical_digest
        )
        authority.close()

    threads = [threading.Thread(target=writer, args=(item,)) for item in authorities]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert results == [command.version.canonical_digest] * 2
    connection = sqlite3.connect(path)
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM event_scoped_local_watches"
        ).fetchone()[0]
        == 1
    )
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    connection.close()


def test_allocated_schemas_authority_and_non_effects_are_exact() -> None:
    assert LOCAL_WATCH_COMMAND == "newsroom.increment7.local-watch-command.v1"
    assert LOCAL_WATCH_REENTRY == "newsroom.increment7.local-watch-reentry.v1"
    assert LOCAL_WATCH_AUTHORITY == "CHECKED_SQLITE_TRANSACTIONAL_V29"
    assert LOCAL_WATCH_REENTRY_AUTHORITY.endswith("GOVERNED_LINEAGE_ONLY")
    command = _close_command()
    for value in (command, command.reentry):
        assert value.authorises_external_effect is False
        assert value.authorises_source_access is False
        assert value.authorises_egress is False
        assert value.authorises_spend is False
        assert value.authorises_evidence is False
        assert value.authorises_publication is False
        assert value.creates_candidate is False
        assert value.production_activation_authorised is False
