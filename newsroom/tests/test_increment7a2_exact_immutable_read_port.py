from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.authority import migrations
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.migrations import (
    EXPECTED_MIGRATION_HISTORY,
    EXPECTED_SCHEMA_FINGERPRINT,
    SCHEMA_VERSION,
    apply_pending_migrations,
    schema_fingerprint,
)
from newsroom.authority.planned_agenda_migrations import (
    PLANNED_AGENDA_MIGRATION_CHECKSUM,
    PLANNED_AGENDA_MIGRATION_NAME,
    PLANNED_AGENDA_PREDECESSOR_FINGERPRINT,
    PLANNED_AGENDA_SCHEMA_VERSION,
    planned_agenda_backup_paths,
    prepare_planned_agenda_backup,
)
from newsroom.increment7.agenda import (
    AgendaKind,
    AgendaPathKind,
    AgendaPathReference,
    AgendaResolutionKind,
    AgendaScheduleStatus,
    AgendaTimePrecision,
    AgendaUrgency,
    CoverageBasis,
    PlannedAgendaItem,
    PlannedAgendaVersion,
)
from newsroom.increment7.agenda_authority import (
    AgendaAuthorityError,
    AgendaCommandOperation,
    AgendaResolution,
    PlannedAgendaCommand,
    open_planned_agenda_authority,
)

_AT = "2026-08-14T00:00:00.000000Z"
_ACTOR = "sha256:" + "a" * 64


def _id(value: int) -> str:
    return str(uuid.UUID(int=value, version=4))


def _path(kind: AgendaPathKind, value: int) -> AgendaPathReference:
    return AgendaPathReference(kind, _id(value), "agenda-path-v1", "rights-v1")


def _item(value: int = 1) -> PlannedAgendaItem:
    return PlannedAgendaItem(
        _id(value),
        AgendaKind.RELEASE,
        f"uk.mpc.decision.{value}",
        _id(value + 1),
        _AT,
    )


def _version(
    item: PlannedAgendaItem, value: int = 10, **changes: object
) -> PlannedAgendaVersion:
    values: dict[str, object] = {
        "agenda_version_id": _id(value),
        "agenda_item_id": item.agenda_item_id,
        "version_ordinal": 1,
        "predecessor_version_digest": None,
        "source_revision_id": item.created_from_source_revision_id,
        "coverage_basis": CoverageBasis.PLANNED_AGENDA,
        "expected_subject": "Monetary Policy Committee decision",
        "time_precision": AgendaTimePrecision.EXACT_WINDOW,
        "asserted_start": "2026-09-01T11:00:00.000000Z",
        "asserted_end": "2026-09-01T12:00:00.000000Z",
        "time_zone": "Europe/London",
        "schedule_status": AgendaScheduleStatus.CONFIRMED,
        "expectation_path": _path(AgendaPathKind.EXPECTATION, value + 1),
        "occurrence_confirmation_paths": (
            _path(AgendaPathKind.OCCURRENCE_CONFIRMATION, value + 2),
        ),
        "geography": "United Kingdom",
        "urgency": AgendaUrgency.TIME_SENSITIVE,
        "relationship_references": (),
        "uncertainties": (),
        "recorded_at": _AT,
    }
    values.update(changes)
    return PlannedAgendaVersion(**values)  # type: ignore[arg-type]


def _resolution(
    version: PlannedAgendaVersion,
    value: int,
    kind: AgendaResolutionKind,
    *,
    ordinal: int = 1,
    previous: str | None = None,
    successor: str | None = None,
) -> AgendaResolution:
    return AgendaResolution(
        resolution_id=_id(value),
        agenda_item_id=version.agenda_item_id,
        agenda_version_id=version.agenda_version_id,
        agenda_version_digest=version.digest,
        resolution_ordinal=ordinal,
        previous_resolution_digest=previous,
        kind=kind,
        evidence_digest=(
            "sha256:" + f"{value % 16:x}" * 64
            if kind is not AgendaResolutionKind.MISSED_NOT_OBSERVED
            else None
        ),
        confirmation_path_digest=(
            digest_bytes(
                canonical_json_bytes(version.occurrence_confirmation_paths[0].to_dict())
            )
            if kind is not AgendaResolutionKind.MISSED_NOT_OBSERVED
            else None
        ),
        baseline_evidence_digest=(
            "sha256:" + "b" * 64
            if kind is AgendaResolutionKind.MISSED_NOT_OBSERVED
            else None
        ),
        successor_version_digest=successor,
        observed_at="2026-09-01T12:01:00.000000Z",
    )


def _command(
    operation: AgendaCommandOperation,
    value: int,
    *,
    item: PlannedAgendaItem | None = None,
    version: PlannedAgendaVersion | None = None,
    resolution: AgendaResolution | None = None,
    current_version: PlannedAgendaVersion | None = None,
    previous_resolution: AgendaResolution | None = None,
    key: str | None = None,
) -> PlannedAgendaCommand:
    return PlannedAgendaCommand(
        command_id=_id(value),
        operation=operation,
        item=item,
        version=version,
        resolution=resolution,
        expected_current_version_digest=(
            None if current_version is None else current_version.digest
        ),
        expected_current_version_ordinal=(
            0 if current_version is None else current_version.version_ordinal
        ),
        expected_current_resolution_digest=(
            None if previous_resolution is None else previous_resolution.digest
        ),
        expected_current_resolution_ordinal=(
            0 if previous_resolution is None else previous_resolution.resolution_ordinal
        ),
        request_id=_id(value + 1_000),
        actor_identity_digest=_ACTOR,
        idempotency_key=key or f"agenda-command-{value}",
    )


def _create(authority, value: int = 1):
    item = _item(value)
    version = _version(item, value + 10)
    command = _command(
        AgendaCommandOperation.CREATE,
        value + 100,
        item=item,
        version=version,
    )
    return item, version, command, authority.apply(command.canonical_bytes)


def _downgrade_empty_v26_to_v25(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=OFF")
    immutable = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name='immutable_authority_migrations_delete'"
    ).fetchone()[0]
    connection.execute("DROP TRIGGER immutable_authority_migrations_delete")
    triggers = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' "
        "AND (name LIKE '%planned_agenda%' OR name LIKE '%Agenda%')"
    ).fetchall()
    for (name,) in triggers:
        connection.execute(f'DROP TRIGGER "{name}"')
    for table in (
        "planned_agenda_resolutions",
        "planned_agenda_heads",
        "planned_agenda_versions",
        "planned_agenda_items",
    ):
        connection.execute(f"DROP TABLE {table}")
    connection.execute("DELETE FROM authority_migrations WHERE version=26")
    connection.execute(immutable)
    connection.execute("PRAGMA user_version=25")
    connection.execute("PRAGMA foreign_keys=ON")


def test_v26_fresh_create_history_fingerprint_and_integrity() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    apply_pending_migrations(connection, applied_at=_AT)
    assert SCHEMA_VERSION == PLANNED_AGENDA_SCHEMA_VERSION == 26
    assert EXPECTED_MIGRATION_HISTORY[-1] == (
        26,
        PLANNED_AGENDA_MIGRATION_NAME,
        PLANNED_AGENDA_MIGRATION_CHECKSUM,
    )
    assert connection.execute("PRAGMA user_version").fetchone() == (26,)
    assert schema_fingerprint(connection) == EXPECTED_SCHEMA_FINGERPRINT
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)


def test_v25_upgrade_requires_and_retains_exact_backup(tmp_path: Path) -> None:
    database = tmp_path / "agenda.sqlite3"
    connection = sqlite3.connect(database, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    apply_pending_migrations(connection, applied_at=_AT)
    _downgrade_empty_v26_to_v25(connection)
    assert schema_fingerprint(connection) == PLANNED_AGENDA_PREDECESSOR_FINGERPRINT
    connection.close()

    authority = open_planned_agenda_authority(database, applied_at=_AT)
    authority.close()
    backup, digest = planned_agenda_backup_paths(database.resolve())
    assert backup.is_file() and digest.is_file()
    retained = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    assert retained.execute("PRAGMA user_version").fetchone() == (25,)
    assert schema_fingerprint(retained) == PLANNED_AGENDA_PREDECESSOR_FINGERPRINT
    retained.close()


def test_v26_failure_rolls_back_to_exact_v25(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "rollback.sqlite3"
    connection = sqlite3.connect(database, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    apply_pending_migrations(connection, applied_at=_AT)
    _downgrade_empty_v26_to_v25(connection)
    backup, _ = planned_agenda_backup_paths(database.resolve())
    prepare_planned_agenda_backup(connection, backup)
    monkeypatch.setattr(
        migrations,
        "PLANNED_AGENDA_MIGRATION_STATEMENTS",
        (*migrations.PLANNED_AGENDA_MIGRATION_STATEMENTS, "INVALID SQL"),
    )
    with pytest.raises(sqlite3.OperationalError):
        apply_pending_migrations(connection, applied_at=_AT)
    assert connection.execute("PRAGMA user_version").fetchone() == (25,)
    assert schema_fingerprint(connection) == PLANNED_AGENDA_PREDECESSOR_FINGERPRINT
    assert (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='planned_agenda_items'"
        ).fetchone()
        is None
    )


def test_create_replay_read_port_restart_and_no_effects(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    authority = open_planned_agenda_authority(database, applied_at=_AT)
    item, version, command, snapshot = _create(authority)
    assert authority.apply(command.canonical_bytes) == snapshot
    assert authority.read_port().load(item.agenda_item_id) == snapshot
    assert authority.read_port().versions(item.agenda_item_id) == (version,)
    assert authority.read_port().resolutions(item.agenda_item_id) == ()
    conflicting = _resolution(
        version,
        190,
        AgendaResolutionKind.CHECK_FAILED,
    )
    with pytest.raises(AgendaAuthorityError, match="idempotency operation"):
        authority.apply(
            _command(
                AgendaCommandOperation.RESOLVE,
                290,
                resolution=conflicting,
                current_version=version,
                key=command.idempotency_key,
            ).canonical_bytes
        )
    for value in (
        authority,
        snapshot,
        snapshot.item,
        snapshot.current_version,
        command,
    ):
        assert value.creates_signal is False
        assert value.creates_lead is False
        assert value.creates_candidate is False
        assert value.authorises_external_effect is False
    authority.close()

    reopened = open_planned_agenda_authority(database, applied_at=_AT)
    assert reopened.load(item.agenda_item_id).current_version == version
    reopened.close()


def test_explicit_miss_then_late_occurrence_is_retained_and_terminal() -> None:
    authority = open_planned_agenda_authority(":memory:", applied_at=_AT)
    item, version, _, _ = _create(authority)
    missed = _resolution(
        version,
        201,
        AgendaResolutionKind.MISSED_NOT_OBSERVED,
    )
    miss_command = _command(
        AgendaCommandOperation.RESOLVE,
        301,
        resolution=missed,
        current_version=version,
    )
    after_miss = authority.apply(miss_command.canonical_bytes)
    late = _resolution(
        version,
        202,
        AgendaResolutionKind.LATE_OCCURRENCE,
        ordinal=2,
        previous=missed.digest,
    )
    late_command = _command(
        AgendaCommandOperation.RESOLVE,
        302,
        resolution=late,
        current_version=version,
        previous_resolution=missed,
    )
    final = authority.apply(late_command.canonical_bytes)
    assert after_miss.resolutions == (missed,)
    assert final.resolutions == (missed, late)

    further = _resolution(
        version,
        203,
        AgendaResolutionKind.CHECK_FAILED,
        ordinal=3,
        previous=late.digest,
    )
    with pytest.raises(AgendaAuthorityError, match="terminal"):
        authority.apply(
            _command(
                AgendaCommandOperation.RESOLVE,
                303,
                resolution=further,
                current_version=version,
                previous_resolution=late,
            ).canonical_bytes
        )


@pytest.mark.parametrize(
    ("kind", "status"),
    [
        (AgendaResolutionKind.RESCHEDULED, AgendaScheduleStatus.CONFIRMED),
        (
            AgendaResolutionKind.CANCELLED_WITH_SOURCE_EVIDENCE,
            AgendaScheduleStatus.CANCELLED,
        ),
    ],
)
def test_revision_is_atomic_cas_bound_and_status_matched(kind, status) -> None:
    authority = open_planned_agenda_authority(":memory:", applied_at=_AT)
    item, prior, _, _ = _create(authority)
    successor = _version(
        item,
        20,
        version_ordinal=2,
        predecessor_version_digest=prior.digest,
        source_revision_id=_id(30),
        asserted_start="2026-09-02T11:00:00.000000Z",
        asserted_end="2026-09-02T12:00:00.000000Z",
        schedule_status=status,
        uncertainties=(
            ("source-revision-asserted-cancellation",)
            if status is AgendaScheduleStatus.CANCELLED
            else ()
        ),
        recorded_at="2026-08-15T00:00:00.000000Z",
    )
    resolution = _resolution(prior, 210, kind, successor=successor.digest)
    command = _command(
        AgendaCommandOperation.REVISE,
        310,
        version=successor,
        resolution=resolution,
        current_version=prior,
    )
    result = authority.apply(command.canonical_bytes)
    assert result.current_version == successor
    assert result.resolutions == (resolution,)
    assert authority.apply(command.canonical_bytes) == result


def test_two_writers_enforce_current_head_cas(tmp_path: Path) -> None:
    database = tmp_path / "concurrent.sqlite3"
    first = open_planned_agenda_authority(database, applied_at=_AT)
    item, version, _, _ = _create(first)
    second = open_planned_agenda_authority(database, applied_at=_AT)
    stale = second.load(item.agenda_item_id)
    occurrence = _resolution(
        version,
        220,
        AgendaResolutionKind.OCCURRENCE_CONFIRMED,
    )
    forged_path = replace(
        occurrence,
        confirmation_path_digest="sha256:" + "0" * 64,
    )
    with pytest.raises(AgendaAuthorityError, match="path is not admitted"):
        first.apply(
            _command(
                AgendaCommandOperation.RESOLVE,
                319,
                resolution=forged_path,
                current_version=version,
            ).canonical_bytes
        )
    first.apply(
        _command(
            AgendaCommandOperation.RESOLVE,
            320,
            resolution=occurrence,
            current_version=version,
        ).canonical_bytes
    )
    competing = _resolution(
        version,
        221,
        AgendaResolutionKind.CHECK_FAILED,
    )
    assert stale.resolutions == ()
    with pytest.raises(AgendaAuthorityError, match="CAS"):
        second.apply(
            _command(
                AgendaCommandOperation.RESOLVE,
                321,
                resolution=competing,
                current_version=version,
            ).canonical_bytes
        )
    first.close()
    second.close()


def test_command_and_resolution_replay_reject_unknown_duplicate_and_clock_only() -> (
    None
):
    item = _item()
    version = _version(item)
    command = _command(
        AgendaCommandOperation.CREATE,
        400,
        item=item,
        version=version,
    )
    assert PlannedAgendaCommand.from_canonical_bytes(command.canonical_bytes) == command
    unknown = json.loads(command.canonical_bytes)
    unknown["clock_elapsed"] = True
    with pytest.raises(AgendaAuthorityError, match="fields differ"):
        PlannedAgendaCommand.from_canonical_bytes(canonical_json_bytes(unknown))
    duplicate = command.canonical_bytes.replace(
        b'"command_id":', b'"command_id":"' + _id(999).encode() + b'","command_id":', 1
    )
    with pytest.raises(AgendaAuthorityError, match="duplicate object"):
        PlannedAgendaCommand.from_canonical_bytes(duplicate)
    with pytest.raises(AgendaAuthorityError, match="baseline evidence"):
        AgendaResolution(
            _id(500),
            item.agenda_item_id,
            version.agenda_version_id,
            version.digest,
            1,
            None,
            AgendaResolutionKind.MISSED_NOT_OBSERVED,
            None,
            None,
            None,
            None,
            "2026-09-01T12:01:00.000000Z",
        )


def test_retained_rows_reject_direct_mutation_and_delete(tmp_path: Path) -> None:
    database = tmp_path / "retained.sqlite3"
    authority = open_planned_agenda_authority(database, applied_at=_AT)
    item, _, _, _ = _create(authority)
    with pytest.raises(sqlite3.DatabaseError):
        authority._connection.execute(  # noqa: SLF001 - adversarial fixture proof
            "UPDATE planned_agenda_items SET stable_subject_key='tampered' "
            "WHERE agenda_item_id=?",
            (item.agenda_item_id,),
        )
    with pytest.raises(sqlite3.DatabaseError):
        authority._connection.execute(  # noqa: SLF001 - adversarial fixture proof
            "DELETE FROM planned_agenda_versions WHERE agenda_item_id=?",
            (item.agenda_item_id,),
        )
