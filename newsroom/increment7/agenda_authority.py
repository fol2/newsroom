"""Checked SQLite lifecycle authority for Planned Agenda records.

The authority persists caller-supplied, already observed assertions.  It has no
clock, source, provider, publication, Signal, Lead, Candidate or evidence-
acquisition capability.  In particular, elapsed time is never an occurrence.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Self

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.authority.migrations import (
    SCHEMA_VERSION,
    apply_pending_migrations,
    prepare_pending_migration_backup,
)
from newsroom.increment7.agenda import (
    AgendaResolutionKind,
    AgendaScheduleStatus,
    PlannedAgendaItem,
    PlannedAgendaVersion,
    validate_agenda_successor,
)

PLANNED_AGENDA_COMMAND = "newsroom.increment7.planned-agenda-command.v1"
PLANNED_AGENDA_RESOLUTION = "newsroom.increment7.planned-agenda-resolution.v1"
PLANNED_AGENDA_AUTHORITY = "CHECKED_SQLITE_CAS_V26"
AGENDA_OCCURRENCE_AUTHORITY = "EXPLICIT_SOURCE_EVIDENCE_ONLY"
AGENDA_RESCHEDULE_CANCEL_AUTHORITY = "IMMUTABLE_SUCCESSOR_AND_RESOLUTION"
AGENDA_LATE_RESOLUTION_AUTHORITY = "EXPLICIT_BASELINE_THEN_SOURCE_EVIDENCE"
MAX_AGENDA_COMMAND_BYTES = 4_194_304

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_UTC = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)


class AgendaAuthorityError(ValueError):
    """A command, persisted row or lifecycle transition failed closed."""


class AgendaCommandOperation(StrEnum):
    CREATE = "CREATE"
    REVISE = "REVISE"
    RESOLVE = "RESOLVE"


class _NoEffect:
    authorises_external_effect = False
    authorises_publication = False
    authorises_provider = False
    authorises_schedule = False
    authorises_evidence_acquisition = False
    authorises_budget = False
    authorises_personal_data = False
    creates_signal = False
    creates_lead = False
    creates_candidate = False
    clock_driven = False
    production_activation_authorised = False


def _total(label: str):
    def decorate(function):
        def wrapped(*args: object, **kwargs: object):
            try:
                return function(*args, **kwargs)
            except AgendaAuthorityError:
                raise
            except Exception as exc:
                raise AgendaAuthorityError(label) from exc

        return wrapped

    return decorate


def _text(value: object, field: str, maximum: int = 2_048) -> str:
    try:
        size = len(value.encode()) if type(value) is str else 0
    except UnicodeError as exc:
        raise AgendaAuthorityError(f"{field} must be canonical text") from exc
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or size > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise AgendaAuthorityError(f"{field} must be canonical text")
    return value


def _token(value: object, field: str) -> str:
    value = _text(value, field, 256)
    if _TOKEN.fullmatch(value) is None:
        raise AgendaAuthorityError(f"{field} must be a canonical token")
    return value


def _uuid(value: object, field: str) -> str:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        raise AgendaAuthorityError(f"{field} must be a canonical UUID")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError as exc:
        raise AgendaAuthorityError(f"{field} must be a canonical UUID") from exc
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise AgendaAuthorityError(f"{field} must be a SHA-256 digest") from exc


def _timestamp(value: object, field: str) -> str:
    value = _text(value, field, 27)
    if _UTC.fullmatch(value) is None:
        raise AgendaAuthorityError(f"{field} must be an exact UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise AgendaAuthorityError(f"{field} must be an exact UTC timestamp") from exc
    return value


def _enum[T: StrEnum](kind: type[T], value: object, field: str) -> T:
    if type(value) is not str and type(value) is not kind:
        raise AgendaAuthorityError(f"{field} differs")
    try:
        return kind(value)
    except ValueError as exc:
        raise AgendaAuthorityError(f"{field} differs") from exc


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise AgendaAuthorityError(f"duplicate object name: {key}")
        value[key] = item
    return value


def _document(raw: bytes, schema: str, fields: tuple[str, ...]) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_AGENDA_COMMAND_BYTES:
        raise AgendaAuthorityError("document bytes are not bounded")
    try:
        value = json.loads(raw.decode(), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except AgendaAuthorityError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
        RecursionError,
        ValueError,
    ) as exc:
        raise AgendaAuthorityError("document is not canonical JSON") from exc
    if raw != canonical or type(value) is not dict:
        raise AgendaAuthorityError("document is not exact canonical JSON")
    if tuple(value) != tuple(sorted(fields)):
        raise AgendaAuthorityError("document fields differ")
    if value["schema_version"] != schema:
        raise AgendaAuthorityError("document schema differs")
    return value


_EVIDENCE_REQUIRED = frozenset(
    {
        AgendaResolutionKind.OCCURRENCE_CONFIRMED,
        AgendaResolutionKind.LATE_OCCURRENCE,
        AgendaResolutionKind.RESCHEDULED,
        AgendaResolutionKind.CANCELLED_WITH_SOURCE_EVIDENCE,
        AgendaResolutionKind.POSTPONED_WITH_SOURCE_EVIDENCE,
        AgendaResolutionKind.WITHDRAWN_WITH_SOURCE_EVIDENCE,
        AgendaResolutionKind.CHECK_FAILED,
        AgendaResolutionKind.CHECK_PARTIAL,
        AgendaResolutionKind.CHECK_UNAVAILABLE,
        AgendaResolutionKind.AMBIGUOUS,
    }
)
_REVISION_KINDS = frozenset(
    {
        AgendaResolutionKind.RESCHEDULED,
        AgendaResolutionKind.CANCELLED_WITH_SOURCE_EVIDENCE,
        AgendaResolutionKind.POSTPONED_WITH_SOURCE_EVIDENCE,
        AgendaResolutionKind.WITHDRAWN_WITH_SOURCE_EVIDENCE,
    }
)
_TERMINAL_KINDS = frozenset(
    {
        AgendaResolutionKind.OCCURRENCE_CONFIRMED,
        AgendaResolutionKind.LATE_OCCURRENCE,
        AgendaResolutionKind.CANCELLED_WITH_SOURCE_EVIDENCE,
        AgendaResolutionKind.WITHDRAWN_WITH_SOURCE_EVIDENCE,
    }
)


_RESOLUTION_FIELDS = (
    "schema_version",
    "resolution_id",
    "agenda_item_id",
    "agenda_version_id",
    "agenda_version_digest",
    "resolution_ordinal",
    "previous_resolution_digest",
    "kind",
    "evidence_digest",
    "confirmation_path_digest",
    "baseline_evidence_digest",
    "successor_version_digest",
    "observed_at",
)


@dataclass(frozen=True, slots=True)
class AgendaResolution(_NoEffect):
    resolution_id: str
    agenda_item_id: str
    agenda_version_id: str
    agenda_version_digest: str
    resolution_ordinal: int
    previous_resolution_digest: str | None
    kind: AgendaResolutionKind
    evidence_digest: str | None
    confirmation_path_digest: str | None
    baseline_evidence_digest: str | None
    successor_version_digest: str | None
    observed_at: str
    schema_version: str = PLANNED_AGENDA_RESOLUTION

    def __post_init__(self) -> None:
        if self.schema_version != PLANNED_AGENDA_RESOLUTION:
            raise AgendaAuthorityError("resolution schema differs")
        for field in ("resolution_id", "agenda_item_id", "agenda_version_id"):
            _uuid(getattr(self, field), field)
        _digest(self.agenda_version_digest, "agenda_version_digest")
        if (
            type(self.resolution_ordinal) is not int
            or not 1 <= self.resolution_ordinal <= 1_000_000
        ):
            raise AgendaAuthorityError("resolution_ordinal differs")
        if self.resolution_ordinal == 1:
            if self.previous_resolution_digest is not None:
                raise AgendaAuthorityError("first resolution has a predecessor")
        elif self.previous_resolution_digest is None:
            raise AgendaAuthorityError("successor resolution lacks a predecessor")
        else:
            _digest(self.previous_resolution_digest, "previous_resolution_digest")
        object.__setattr__(self, "kind", _enum(AgendaResolutionKind, self.kind, "kind"))
        for field in (
            "evidence_digest",
            "confirmation_path_digest",
            "baseline_evidence_digest",
            "successor_version_digest",
        ):
            value = getattr(self, field)
            if value is not None:
                _digest(value, field)
        if (self.kind in _EVIDENCE_REQUIRED) != (self.evidence_digest is not None):
            raise AgendaAuthorityError("resolution evidence boundary differs")
        if (self.evidence_digest is not None) != (
            self.confirmation_path_digest is not None
        ):
            raise AgendaAuthorityError("resolution confirmation path differs")
        missed = self.kind is AgendaResolutionKind.MISSED_NOT_OBSERVED
        if missed != (self.baseline_evidence_digest is not None):
            raise AgendaAuthorityError("miss requires explicit baseline evidence")
        revised = self.kind in _REVISION_KINDS
        if revised != (self.successor_version_digest is not None):
            raise AgendaAuthorityError("revision resolution successor differs")
        _timestamp(self.observed_at, "observed_at")

    @property
    def canonical_bytes(self) -> bytes:
        value: dict[str, object] = {}
        for field in _RESOLUTION_FIELDS:
            item = getattr(self, field)
            value[field] = item.value if isinstance(item, StrEnum) else item
        return canonical_json_bytes(value)

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    @_total("Agenda Resolution replay failed")
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, PLANNED_AGENDA_RESOLUTION, _RESOLUTION_FIELDS)
        value["kind"] = _enum(AgendaResolutionKind, value["kind"], "kind")
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise AgendaAuthorityError("Agenda Resolution replay differs")
        return result


_COMMAND_FIELDS = (
    "schema_version",
    "command_id",
    "operation",
    "item",
    "version",
    "resolution",
    "expected_current_version_digest",
    "expected_current_version_ordinal",
    "expected_current_resolution_digest",
    "expected_current_resolution_ordinal",
    "request_id",
    "actor_identity_digest",
    "idempotency_key",
)


@dataclass(frozen=True, slots=True)
class PlannedAgendaCommand(_NoEffect):
    command_id: str
    operation: AgendaCommandOperation
    item: PlannedAgendaItem | None
    version: PlannedAgendaVersion | None
    resolution: AgendaResolution | None
    expected_current_version_digest: str | None
    expected_current_version_ordinal: int
    expected_current_resolution_digest: str | None
    expected_current_resolution_ordinal: int
    request_id: str
    actor_identity_digest: str
    idempotency_key: str
    schema_version: str = PLANNED_AGENDA_COMMAND

    def __post_init__(self) -> None:
        if self.schema_version != PLANNED_AGENDA_COMMAND:
            raise AgendaAuthorityError("command schema differs")
        _uuid(self.command_id, "command_id")
        _uuid(self.request_id, "request_id")
        _digest(self.actor_identity_digest, "actor_identity_digest")
        _token(self.idempotency_key, "idempotency_key")
        object.__setattr__(
            self,
            "operation",
            _enum(AgendaCommandOperation, self.operation, "operation"),
        )
        for field, kind in (
            ("item", PlannedAgendaItem),
            ("version", PlannedAgendaVersion),
            ("resolution", AgendaResolution),
        ):
            value = getattr(self, field)
            if value is not None and type(value) is not kind:
                raise AgendaAuthorityError(f"command {field} differs")
        for field in (
            "expected_current_version_ordinal",
            "expected_current_resolution_ordinal",
        ):
            value = getattr(self, field)
            if type(value) is not int or not 0 <= value <= 1_000_000:
                raise AgendaAuthorityError(f"{field} differs")
        version_current = self.expected_current_version_digest is not None
        if version_current:
            _digest(
                self.expected_current_version_digest,
                "expected_current_version_digest",
            )
        if version_current != (self.expected_current_version_ordinal > 0):
            raise AgendaAuthorityError("command Version CAS is partial")
        resolution_current = self.expected_current_resolution_digest is not None
        if resolution_current:
            _digest(
                self.expected_current_resolution_digest,
                "expected_current_resolution_digest",
            )
        if resolution_current != (self.expected_current_resolution_ordinal > 0):
            raise AgendaAuthorityError("command Resolution CAS is partial")
        present = (
            self.item is not None,
            self.version is not None,
            self.resolution is not None,
        )
        if self.operation is AgendaCommandOperation.CREATE:
            if present != (True, True, False) or version_current or resolution_current:
                raise AgendaAuthorityError("CREATE command shape differs")
        elif self.operation is AgendaCommandOperation.REVISE:
            if present != (False, True, True) or not version_current:
                raise AgendaAuthorityError("REVISE command shape differs")
        elif present != (False, False, True) or not version_current:
            raise AgendaAuthorityError("RESOLVE command shape differs")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "actor_identity_digest": self.actor_identity_digest,
                "command_id": self.command_id,
                "expected_current_resolution_digest": self.expected_current_resolution_digest,
                "expected_current_resolution_ordinal": self.expected_current_resolution_ordinal,
                "expected_current_version_digest": self.expected_current_version_digest,
                "expected_current_version_ordinal": self.expected_current_version_ordinal,
                "idempotency_key": self.idempotency_key,
                "item": None
                if self.item is None
                else json.loads(self.item.canonical_bytes),
                "operation": self.operation.value,
                "request_id": self.request_id,
                "resolution": None
                if self.resolution is None
                else json.loads(self.resolution.canonical_bytes),
                "schema_version": self.schema_version,
                "version": None
                if self.version is None
                else json.loads(self.version.canonical_bytes),
            }
        )

    @classmethod
    @_total("Planned Agenda command replay failed")
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, PLANNED_AGENDA_COMMAND, _COMMAND_FIELDS)
        parsers = {
            "item": PlannedAgendaItem.from_canonical_bytes,
            "version": PlannedAgendaVersion.from_canonical_bytes,
            "resolution": AgendaResolution.from_canonical_bytes,
        }
        for field, parser in parsers.items():
            if value[field] is not None:
                value[field] = parser(canonical_json_bytes(value[field]))
        value["operation"] = _enum(
            AgendaCommandOperation, value["operation"], "operation"
        )
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise AgendaAuthorityError("Planned Agenda command replay differs")
        return result


@dataclass(frozen=True, slots=True)
class PlannedAgendaSnapshot(_NoEffect):
    item: PlannedAgendaItem
    current_version: PlannedAgendaVersion
    resolutions: tuple[AgendaResolution, ...]

    def __post_init__(self) -> None:
        if (
            type(self.item) is not PlannedAgendaItem
            or type(self.current_version) is not PlannedAgendaVersion
            or type(self.resolutions) is not tuple
            or any(type(value) is not AgendaResolution for value in self.resolutions)
            or self.current_version.agenda_item_id != self.item.agenda_item_id
        ):
            raise AgendaAuthorityError("Agenda snapshot binding differs")


_AUTHORITY_TOKEN = object()


class PlannedAgendaReadPort(_NoEffect):
    """Read-only exact replay port over retained Agenda rows."""

    __slots__ = ("_connection",)

    def __init__(self, token: object, connection: sqlite3.Connection) -> None:
        if token is not _AUTHORITY_TOKEN:
            raise AgendaAuthorityError("Planned Agenda port construction is private")
        object.__setattr__(self, "_connection", connection)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("PlannedAgendaReadPort is immutable")

    @_total("Planned Agenda Version history failed")
    def versions(self, agenda_item_id: str) -> tuple[PlannedAgendaVersion, ...]:
        _uuid(agenda_item_id, "agenda_item_id")
        rows = self._connection.execute(
            "SELECT version_bytes,version_digest FROM planned_agenda_versions "
            "WHERE agenda_item_id=? ORDER BY version_ordinal",
            (agenda_item_id,),
        ).fetchall()
        versions = tuple(
            PlannedAgendaVersion.from_canonical_bytes(bytes(row[0])) for row in rows
        )
        for ordinal, (version, stored) in enumerate(zip(versions, rows), 1):
            if version.version_ordinal != ordinal or version.digest != stored[1]:
                raise AgendaAuthorityError("Planned Agenda Version replay differs")
            if ordinal > 1:
                validate_agenda_successor(versions[ordinal - 2], version)
        return versions

    @_total("Agenda Resolution history failed")
    def resolutions(self, agenda_item_id: str) -> tuple[AgendaResolution, ...]:
        _uuid(agenda_item_id, "agenda_item_id")
        rows = self._connection.execute(
            "SELECT r.resolution_bytes,r.resolution_digest,v.recorded_at "
            "FROM planned_agenda_resolutions r JOIN planned_agenda_versions v "
            "ON v.agenda_version_id=r.agenda_version_id "
            "AND v.agenda_item_id=r.agenda_item_id "
            "AND v.version_digest=r.agenda_version_digest "
            "WHERE r.agenda_item_id=? ORDER BY r.resolution_ordinal",
            (agenda_item_id,),
        ).fetchall()
        resolutions = tuple(
            AgendaResolution.from_canonical_bytes(bytes(row[0])) for row in rows
        )
        previous: AgendaResolution | None = None
        for ordinal, (resolution, stored) in enumerate(zip(resolutions, rows), 1):
            if (
                resolution.agenda_item_id != agenda_item_id
                or resolution.resolution_ordinal != ordinal
                or resolution.digest != stored[1]
                or resolution.observed_at < stored[2]
                or resolution.previous_resolution_digest
                != (None if previous is None else previous.digest)
                or (
                    previous is not None
                    and resolution.observed_at < previous.observed_at
                )
            ):
                raise AgendaAuthorityError("Agenda Resolution replay differs")
            previous = resolution
        return resolutions

    @_total("Planned Agenda load failed")
    def load(self, agenda_item_id: str) -> PlannedAgendaSnapshot:
        _uuid(agenda_item_id, "agenda_item_id")
        row = self._connection.execute(
            "SELECT i.item_bytes,i.item_digest,h.current_version_id,"
            "h.current_version_digest,"
            "h.current_version_ordinal,h.current_resolution_digest,"
            "h.current_resolution_ordinal FROM planned_agenda_items i "
            "JOIN planned_agenda_heads h USING(agenda_item_id) WHERE i.agenda_item_id=?",
            (agenda_item_id,),
        ).fetchone()
        if row is None:
            raise AgendaAuthorityError("Planned Agenda Item is absent")
        item = PlannedAgendaItem.from_canonical_bytes(bytes(row[0]))
        if item.digest != row[1]:
            raise AgendaAuthorityError("Planned Agenda Item replay differs")
        versions = self.versions(agenda_item_id)
        if not versions:
            raise AgendaAuthorityError("Planned Agenda Version history is empty")
        current = versions[-1]
        if (
            current.agenda_version_id,
            current.digest,
            current.version_ordinal,
        ) != tuple(row[2:5]):
            raise AgendaAuthorityError("Planned Agenda head differs")
        resolutions = self.resolutions(agenda_item_id)
        previous = resolutions[-1] if resolutions else None
        expected_resolution = (
            None if previous is None else previous.digest,
            len(resolutions),
        )
        if tuple(row[5:7]) != expected_resolution:
            raise AgendaAuthorityError("Agenda Resolution head differs")
        return PlannedAgendaSnapshot(item, current, resolutions)


class PlannedAgendaAuthority(PlannedAgendaReadPort):
    """Transactional v26 writer with exact idempotency and two independent CAS heads."""

    __slots__ = ("_closed",)

    def __init__(self, token: object, connection: sqlite3.Connection) -> None:
        super().__init__(token, connection)
        object.__setattr__(self, "_closed", False)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("PlannedAgendaAuthority is immutable")

    @_total("Planned Agenda command failed")
    def apply(self, raw: bytes) -> PlannedAgendaSnapshot:
        command = PlannedAgendaCommand.from_canonical_bytes(raw)
        if self._closed:
            raise AgendaAuthorityError("Planned Agenda authority is closed")
        if command.operation is AgendaCommandOperation.CREATE:
            return self._create(command)
        if command.operation is AgendaCommandOperation.REVISE:
            return self._revise(command)
        return self._resolve(command)

    def _begin(self) -> None:
        self._connection.execute("BEGIN IMMEDIATE")

    def _finish(self, error: BaseException | None = None) -> None:
        if self._connection.in_transaction:
            self._connection.execute("ROLLBACK" if error else "COMMIT")

    def _matching_replay(
        self,
        command: PlannedAgendaCommand,
        expected: dict[str, bytes],
    ) -> str | None:
        bindings: dict[str, tuple[object, ...]] = {}
        byte_columns = {
            "planned_agenda_items": "item_bytes",
            "planned_agenda_versions": "version_bytes",
            "planned_agenda_resolutions": "resolution_bytes",
        }
        for table, byte_column in byte_columns.items():
            row = self._connection.execute(
                f"SELECT agenda_item_id,request_id,actor_identity_digest,"
                f"idempotency_key,command_digest,{byte_column} FROM {table} WHERE request_id=? "
                "OR (actor_identity_digest=? AND idempotency_key=?)",
                (
                    command.request_id,
                    command.actor_identity_digest,
                    command.idempotency_key,
                ),
            ).fetchone()
            if row is not None:
                bindings[table] = tuple(row)
        if not bindings:
            return None
        if set(bindings) != set(expected):
            raise AgendaAuthorityError("Agenda idempotency operation conflicts")
        item_ids = {str(row[0]) for row in bindings.values()}
        if len(item_ids) != 1:
            raise AgendaAuthorityError("Agenda idempotency item binding conflicts")
        for table, row in bindings.items():
            if (
                tuple(row[1:4])
                != (
                    command.request_id,
                    command.actor_identity_digest,
                    command.idempotency_key,
                )
                or row[4] != digest_bytes(command.canonical_bytes)
                or bytes(row[5]) != expected[table]
            ):
                raise AgendaAuthorityError("Agenda idempotency binding conflicts")
        return item_ids.pop()

    def _create(self, command: PlannedAgendaCommand) -> PlannedAgendaSnapshot:
        assert command.item is not None and command.version is not None
        item = PlannedAgendaItem.from_canonical_bytes(command.item.canonical_bytes)
        version = PlannedAgendaVersion.from_canonical_bytes(
            command.version.canonical_bytes
        )
        if (
            version.agenda_item_id != item.agenda_item_id
            or version.version_ordinal != 1
        ):
            raise AgendaAuthorityError("initial Agenda Version binding differs")
        self._begin()
        try:
            replay_id = self._matching_replay(
                command,
                {
                    "planned_agenda_items": item.canonical_bytes,
                    "planned_agenda_versions": version.canonical_bytes,
                },
            )
            if replay_id is not None:
                snapshot = self.load(replay_id)
                if snapshot.item != item:
                    raise AgendaAuthorityError("Agenda CREATE replay conflicts")
                self._finish()
                return snapshot
            self._connection.execute(
                "INSERT INTO planned_agenda_items VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item.agenda_item_id,
                    item.canonical_bytes,
                    item.digest,
                    item.agenda_kind.value,
                    item.stable_subject_key,
                    version.agenda_version_id,
                    command.request_id,
                    digest_bytes(command.canonical_bytes),
                    command.actor_identity_digest,
                    command.idempotency_key,
                    item.created_at,
                ),
            )
            self._insert_version(version, command)
            self._connection.execute(
                "INSERT INTO planned_agenda_heads VALUES(?,?,?,?,?,?,?)",
                (
                    item.agenda_item_id,
                    version.agenda_version_id,
                    version.digest,
                    1,
                    None,
                    0,
                    version.recorded_at,
                ),
            )
            self._finish()
        except BaseException as exc:
            self._finish(exc)
            raise
        return self.load(item.agenda_item_id)

    def _insert_version(
        self, version: PlannedAgendaVersion, command: PlannedAgendaCommand
    ) -> None:
        self._connection.execute(
            "INSERT INTO planned_agenda_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                version.agenda_version_id,
                version.agenda_item_id,
                version.version_ordinal,
                version.predecessor_version_digest,
                version.canonical_bytes,
                version.digest,
                version.source_revision_id,
                version.schedule_status.value,
                command.request_id,
                digest_bytes(command.canonical_bytes),
                command.actor_identity_digest,
                command.idempotency_key,
                version.recorded_at,
            ),
        )

    def _assert_cas(
        self, command: PlannedAgendaCommand, snapshot: PlannedAgendaSnapshot
    ) -> None:
        current_resolution = snapshot.resolutions[-1] if snapshot.resolutions else None
        if (
            command.expected_current_version_digest != snapshot.current_version.digest
            or command.expected_current_version_ordinal
            != snapshot.current_version.version_ordinal
            or command.expected_current_resolution_digest
            != (None if current_resolution is None else current_resolution.digest)
            or command.expected_current_resolution_ordinal != len(snapshot.resolutions)
        ):
            raise AgendaAuthorityError("Planned Agenda CAS differs")

    def _insert_resolution(
        self, resolution: AgendaResolution, command: PlannedAgendaCommand
    ) -> None:
        self._connection.execute(
            "INSERT INTO planned_agenda_resolutions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                resolution.resolution_id,
                resolution.agenda_item_id,
                resolution.agenda_version_id,
                resolution.agenda_version_digest,
                resolution.resolution_ordinal,
                resolution.previous_resolution_digest,
                resolution.kind.value,
                resolution.canonical_bytes,
                resolution.digest,
                resolution.evidence_digest,
                resolution.confirmation_path_digest,
                resolution.baseline_evidence_digest,
                resolution.successor_version_digest,
                command.request_id,
                digest_bytes(command.canonical_bytes),
                command.actor_identity_digest,
                command.idempotency_key,
                resolution.observed_at,
            ),
        )

    def _validate_resolution(
        self,
        resolution: AgendaResolution,
        snapshot: PlannedAgendaSnapshot,
        *,
        revision: bool,
    ) -> None:
        current = snapshot.current_version
        previous = snapshot.resolutions[-1] if snapshot.resolutions else None
        if (
            resolution.agenda_item_id != snapshot.item.agenda_item_id
            or resolution.agenda_version_id != current.agenda_version_id
            or resolution.agenda_version_digest != current.digest
            or resolution.resolution_ordinal != len(snapshot.resolutions) + 1
            or resolution.previous_resolution_digest
            != (None if previous is None else previous.digest)
            or (resolution.kind in _REVISION_KINDS) is not revision
        ):
            raise AgendaAuthorityError("Agenda Resolution current binding differs")
        if previous is not None and previous.kind in _TERMINAL_KINDS:
            raise AgendaAuthorityError("Agenda lifecycle is terminal")
        if resolution.observed_at < current.recorded_at or (
            previous is not None and resolution.observed_at < previous.observed_at
        ):
            raise AgendaAuthorityError("Agenda Resolution chronology differs")
        admitted_paths = {
            digest_bytes(canonical_json_bytes(path.to_dict()))
            for path in current.occurrence_confirmation_paths
        }
        if resolution.confirmation_path_digest is not None and (
            resolution.confirmation_path_digest not in admitted_paths
        ):
            raise AgendaAuthorityError("Agenda confirmation path is not admitted")
        if resolution.kind is AgendaResolutionKind.LATE_OCCURRENCE and (
            previous is None
            or previous.kind is not AgendaResolutionKind.MISSED_NOT_OBSERVED
            or previous.agenda_version_id != resolution.agenda_version_id
        ):
            raise AgendaAuthorityError("late occurrence requires a recorded miss")

    def _revise(self, command: PlannedAgendaCommand) -> PlannedAgendaSnapshot:
        assert command.version is not None and command.resolution is not None
        successor = PlannedAgendaVersion.from_canonical_bytes(
            command.version.canonical_bytes
        )
        resolution = AgendaResolution.from_canonical_bytes(
            command.resolution.canonical_bytes
        )
        self._begin()
        try:
            replay_id = self._matching_replay(
                command,
                {
                    "planned_agenda_versions": successor.canonical_bytes,
                    "planned_agenda_resolutions": resolution.canonical_bytes,
                },
            )
            if replay_id is not None:
                snapshot = self.load(replay_id)
                self._finish()
                return snapshot
            snapshot = self.load(successor.agenda_item_id)
            self._assert_cas(command, snapshot)
            validate_agenda_successor(snapshot.current_version, successor)
            self._validate_resolution(resolution, snapshot, revision=True)
            if resolution.successor_version_digest != successor.digest:
                raise AgendaAuthorityError("revision successor digest differs")
            status_matrix = {
                AgendaResolutionKind.RESCHEDULED: {
                    AgendaScheduleStatus.PROVISIONAL,
                    AgendaScheduleStatus.CONFIRMED,
                },
                AgendaResolutionKind.CANCELLED_WITH_SOURCE_EVIDENCE: {
                    AgendaScheduleStatus.CANCELLED
                },
                AgendaResolutionKind.POSTPONED_WITH_SOURCE_EVIDENCE: {
                    AgendaScheduleStatus.POSTPONED_WITHOUT_DATE
                },
                AgendaResolutionKind.WITHDRAWN_WITH_SOURCE_EVIDENCE: {
                    AgendaScheduleStatus.WITHDRAWN
                },
            }
            if successor.schedule_status not in status_matrix[resolution.kind]:
                raise AgendaAuthorityError("revision status and resolution differ")
            if resolution.kind is AgendaResolutionKind.RESCHEDULED and (
                successor.time_precision,
                successor.asserted_start,
                successor.asserted_end,
                successor.time_zone,
            ) == (
                snapshot.current_version.time_precision,
                snapshot.current_version.asserted_start,
                snapshot.current_version.asserted_end,
                snapshot.current_version.time_zone,
            ):
                raise AgendaAuthorityError("reschedule leaves schedule unchanged")
            self._insert_version(successor, command)
            self._insert_resolution(resolution, command)
            self._connection.execute(
                "UPDATE planned_agenda_heads SET current_version_id=?,"
                "current_version_digest=?,current_version_ordinal=?,"
                "current_resolution_digest=?,current_resolution_ordinal=?,updated_at=? "
                "WHERE agenda_item_id=?",
                (
                    successor.agenda_version_id,
                    successor.digest,
                    successor.version_ordinal,
                    resolution.digest,
                    resolution.resolution_ordinal,
                    resolution.observed_at,
                    successor.agenda_item_id,
                ),
            )
            self._finish()
        except BaseException as exc:
            self._finish(exc)
            raise
        return self.load(successor.agenda_item_id)

    def _resolve(self, command: PlannedAgendaCommand) -> PlannedAgendaSnapshot:
        assert command.resolution is not None
        resolution = AgendaResolution.from_canonical_bytes(
            command.resolution.canonical_bytes
        )
        self._begin()
        try:
            replay_id = self._matching_replay(
                command,
                {"planned_agenda_resolutions": resolution.canonical_bytes},
            )
            if replay_id is not None:
                snapshot = self.load(replay_id)
                self._finish()
                return snapshot
            snapshot = self.load(resolution.agenda_item_id)
            self._assert_cas(command, snapshot)
            self._validate_resolution(resolution, snapshot, revision=False)
            self._insert_resolution(resolution, command)
            self._connection.execute(
                "UPDATE planned_agenda_heads SET current_resolution_digest=?,"
                "current_resolution_ordinal=?,updated_at=? WHERE agenda_item_id=?",
                (
                    resolution.digest,
                    resolution.resolution_ordinal,
                    resolution.observed_at,
                    resolution.agenda_item_id,
                ),
            )
            self._finish()
        except BaseException as exc:
            self._finish(exc)
            raise
        return self.load(resolution.agenda_item_id)

    def read_port(self) -> PlannedAgendaReadPort:
        return PlannedAgendaReadPort(_AUTHORITY_TOKEN, self._connection)

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            object.__setattr__(self, "_closed", True)


@_total("Planned Agenda authority open failed")
def open_planned_agenda_authority(
    database: str | Path,
    *,
    applied_at: str,
) -> PlannedAgendaAuthority:
    """Open the local checked v26 authority, retaining an exact v25 backup."""
    _timestamp(applied_at, "applied_at")
    if database != ":memory:" and not isinstance(database, (str, Path)):
        raise AgendaAuthorityError("database path differs")
    connection = sqlite3.connect(str(database), isolation_level=None, timeout=30)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version < SCHEMA_VERSION:
            prepare_pending_migration_backup(connection)
        apply_pending_migrations(connection, applied_at=applied_at)
        if (
            connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
            or connection.execute("PRAGMA foreign_key_check").fetchall()
            or connection.execute("PRAGMA quick_check").fetchone()[0] != "ok"
        ):
            raise AgendaAuthorityError("checked v26 schema differs")
        return PlannedAgendaAuthority(_AUTHORITY_TOKEN, connection)
    except BaseException:
        connection.close()
        raise


__all__ = [
    "AGENDA_LATE_RESOLUTION_AUTHORITY",
    "AGENDA_OCCURRENCE_AUTHORITY",
    "AGENDA_RESCHEDULE_CANCEL_AUTHORITY",
    "PLANNED_AGENDA_AUTHORITY",
    "PLANNED_AGENDA_COMMAND",
    "PLANNED_AGENDA_RESOLUTION",
    "AgendaAuthorityError",
    "AgendaCommandOperation",
    "AgendaResolution",
    "PlannedAgendaAuthority",
    "PlannedAgendaCommand",
    "PlannedAgendaReadPort",
    "PlannedAgendaSnapshot",
    "open_planned_agenda_authority",
]
