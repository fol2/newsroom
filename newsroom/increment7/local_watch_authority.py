"""Checked Event-Scoped Local Watch lifecycle authority for Increment 7D2.

The v29 authority retains exact caller-supplied fixture/replay records.  It has
no clock, scheduler, source adapter, provider, network, evidence, Candidate,
publication or production activation capability.  Expiry and re-entry are
explicit commands, never autonomous effects.
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
from newsroom.increment6.work_items import SupplementalDiscoveryReentry
from newsroom.increment7.local_watch import (
    EventScopedLocalWatch,
    LocalWatchClosure,
    LocalWatchClosureOutcome,
    LocalWatchVersion,
    validate_local_watch_closure,
    validate_local_watch_version_chain,
)
from newsroom.increment7.locality_qualification import LocalityCoverageProposal

LOCAL_WATCH_COMMAND = "newsroom.increment7.local-watch-command.v1"
LOCAL_WATCH_REENTRY = "newsroom.increment7.local-watch-reentry.v1"
LOCAL_WATCH_AUTHORITY = "CHECKED_SQLITE_TRANSACTIONAL_V29"
LOCAL_WATCH_REENTRY_AUTHORITY = "EXISTING_INCREMENT6_GOVERNED_LINEAGE_ONLY"
MAX_LOCAL_WATCH_COMMAND_BYTES = 8_388_608

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_UTC = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)


class LocalWatchAuthorityError(ValueError):
    """A command, retained row or governed lineage failed closed."""


class LocalWatchAction(StrEnum):
    CREATE = "CREATE"
    APPEND_VERSION = "APPEND_VERSION"
    CLOSE = "CLOSE"


class LocalWatchReentryKind(StrEnum):
    EXPIRY = "EXPIRY"
    OBSERVABLE_TRANSITION = "OBSERVABLE_TRANSITION"
    OWNER_REVIEW = "OWNER_REVIEW"


class _NoEffect:
    authorises_external_effect = False
    authorises_source_access = False
    authorises_search = False
    authorises_provider = False
    authorises_locality = False
    authorises_credentials = False
    authorises_egress = False
    authorises_spend = False
    authorises_schedule = False
    authorises_evidence = False
    authorises_publication = False
    creates_signal = False
    creates_lead = False
    creates_candidate = False
    creates_locality_proposal = False
    production_activation_authorised = False


def _total(label: str):
    def decorate(function):
        def wrapped(*args: object, **kwargs: object):
            try:
                return function(*args, **kwargs)
            except LocalWatchAuthorityError:
                raise
            except Exception as exc:
                raise LocalWatchAuthorityError(label) from exc

        return wrapped

    return decorate


def _text(value: object, field: str, maximum: int = 2_048) -> str:
    try:
        size = len(value.encode()) if type(value) is str else 0
    except UnicodeError as exc:
        raise LocalWatchAuthorityError(f"{field} must be canonical text") from exc
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or size > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise LocalWatchAuthorityError(f"{field} must be canonical text")
    return value


def _token(value: object, field: str) -> str:
    value = _text(value, field, 256)
    if _TOKEN.fullmatch(value) is None:
        raise LocalWatchAuthorityError(f"{field} must be a canonical token")
    return value


def _uuid(value: object, field: str) -> str:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        raise LocalWatchAuthorityError(f"{field} must be a canonical UUID")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError as exc:
        raise LocalWatchAuthorityError(f"{field} must be a canonical UUID") from exc
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise LocalWatchAuthorityError(f"{field} must be a SHA-256 digest") from exc


def _timestamp(value: object, field: str) -> str:
    value = _text(value, field, 27)
    if _UTC.fullmatch(value) is None:
        raise LocalWatchAuthorityError(f"{field} must be an exact UTC timestamp")
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise LocalWatchAuthorityError(
            f"{field} must be an exact UTC timestamp"
        ) from exc
    return value


def _enum[T: StrEnum](kind: type[T], value: object, field: str) -> T:
    if type(value) is not str and type(value) is not kind:
        raise LocalWatchAuthorityError(f"{field} differs")
    try:
        return kind(value)
    except ValueError as exc:
        raise LocalWatchAuthorityError(f"{field} differs") from exc


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LocalWatchAuthorityError(f"duplicate object name: {key}")
        result[key] = value
    return result


def _document(raw: bytes, schema: str, fields: tuple[str, ...]) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_LOCAL_WATCH_COMMAND_BYTES:
        raise LocalWatchAuthorityError("Local Watch authority bytes are not bounded")
    try:
        value = json.loads(raw.decode(), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except LocalWatchAuthorityError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
        RecursionError,
        ValueError,
    ) as exc:
        raise LocalWatchAuthorityError(
            "Local Watch authority document is not canonical JSON"
        ) from exc
    if type(value) is not dict or raw != canonical:
        raise LocalWatchAuthorityError(
            "Local Watch authority document is not exact canonical JSON"
        )
    if tuple(value) != tuple(sorted(fields)) or value.get("schema_version") != schema:
        raise LocalWatchAuthorityError("Local Watch authority fields or schema differ")
    return value


def _embedded(record: object) -> dict[str, object]:
    return json.loads(record.canonical_bytes)


def _supplemental_bytes(reentry: SupplementalDiscoveryReentry) -> bytes:
    if type(reentry) is not SupplementalDiscoveryReentry:
        raise LocalWatchAuthorityError("supplemental discovery re-entry differs")
    return canonical_json_bytes(reentry.canonical_value())


_REENTRY_FIELDS = (
    "schema_version",
    "reentry_id",
    "watch_id",
    "watch_version_id",
    "watch_version_digest",
    "closure_digest",
    "reentry_kind",
    "supplemental_reentry",
    "supplemental_reentry_digest",
    "actor_identity_digest",
    "recorded_at",
)


@dataclass(frozen=True, slots=True)
class LocalWatchReentry(_NoEffect):
    reentry_id: str
    watch_id: str
    watch_version_id: str
    watch_version_digest: str
    closure_digest: str
    reentry_kind: LocalWatchReentryKind
    supplemental_reentry: SupplementalDiscoveryReentry
    supplemental_reentry_digest: str
    actor_identity_digest: str
    recorded_at: str

    @property
    def schema_version(self) -> str:
        return LOCAL_WATCH_REENTRY

    def __post_init__(self) -> None:
        for field in ("reentry_id", "watch_id", "watch_version_id"):
            _uuid(getattr(self, field), field)
        for field in (
            "watch_version_digest",
            "closure_digest",
            "supplemental_reentry_digest",
            "actor_identity_digest",
        ):
            _digest(getattr(self, field), field)
        object.__setattr__(
            self,
            "reentry_kind",
            _enum(LocalWatchReentryKind, self.reentry_kind, "reentry_kind"),
        )
        expected = digest_bytes(_supplemental_bytes(self.supplemental_reentry))
        if self.supplemental_reentry_digest != expected:
            raise LocalWatchAuthorityError(
                "supplemental discovery re-entry digest differs"
            )
        _timestamp(self.recorded_at, "recorded_at")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "actor_identity_digest": self.actor_identity_digest,
                "closure_digest": self.closure_digest,
                "recorded_at": self.recorded_at,
                "reentry_id": self.reentry_id,
                "reentry_kind": self.reentry_kind.value,
                "schema_version": self.schema_version,
                "supplemental_reentry": self.supplemental_reentry.canonical_value(),
                "supplemental_reentry_digest": self.supplemental_reentry_digest,
                "watch_id": self.watch_id,
                "watch_version_digest": self.watch_version_digest,
                "watch_version_id": self.watch_version_id,
            }
        )

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, LOCAL_WATCH_REENTRY, _REENTRY_FIELDS)
        if type(value["supplemental_reentry"]) is not dict:
            raise LocalWatchAuthorityError("supplemental discovery re-entry differs")
        try:
            value["supplemental_reentry"] = SupplementalDiscoveryReentry.from_value(
                value["supplemental_reentry"]
            )
        except Exception as exc:
            raise LocalWatchAuthorityError(
                "supplemental discovery re-entry differs"
            ) from exc
        value.pop("schema_version")
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise LocalWatchAuthorityError("Local Watch Re-entry replay differs")
        return result


_COMMAND_FIELDS = (
    "schema_version",
    "command_id",
    "action",
    "watch",
    "version",
    "closure",
    "reentry",
    "expected_head_version_digest",
    "request_id",
    "actor_identity_digest",
    "idempotency_key",
)


@dataclass(frozen=True, slots=True)
class LocalWatchCommand(_NoEffect):
    command_id: str
    action: LocalWatchAction
    watch: EventScopedLocalWatch
    version: LocalWatchVersion
    closure: LocalWatchClosure | None
    reentry: LocalWatchReentry | None
    expected_head_version_digest: str | None
    request_id: str
    actor_identity_digest: str
    idempotency_key: str

    @property
    def schema_version(self) -> str:
        return LOCAL_WATCH_COMMAND

    def __post_init__(self) -> None:
        _uuid(self.command_id, "command_id")
        _uuid(self.request_id, "request_id")
        object.__setattr__(
            self, "action", _enum(LocalWatchAction, self.action, "action")
        )
        if (
            type(self.watch) is not EventScopedLocalWatch
            or type(self.version) is not LocalWatchVersion
        ):
            raise LocalWatchAuthorityError("Local Watch command records differ")
        _digest(self.actor_identity_digest, "actor_identity_digest")
        _token(self.idempotency_key, "idempotency_key")
        if self.expected_head_version_digest is not None:
            _digest(
                self.expected_head_version_digest,
                "expected_head_version_digest",
            )
        if (
            self.version.watch_id != self.watch.watch_id
            or self.version.watch_digest != self.watch.canonical_digest
            or self.version.actor_identity_digest != self.actor_identity_digest
        ):
            raise LocalWatchAuthorityError("Local Watch command binding differs")
        if self.action is LocalWatchAction.CREATE:
            if (
                self.version.version_ordinal != 1
                or self.version.previous_version_digest is not None
                or self.expected_head_version_digest is not None
                or self.closure is not None
                or self.reentry is not None
            ):
                raise LocalWatchAuthorityError("Local Watch CREATE shape differs")
            validate_local_watch_version_chain(self.watch, (self.version,))
        elif self.action is LocalWatchAction.APPEND_VERSION:
            if (
                self.version.version_ordinal <= 1
                or self.version.previous_version_digest
                != self.expected_head_version_digest
                or self.closure is not None
                or self.reentry is not None
            ):
                raise LocalWatchAuthorityError(
                    "Local Watch APPEND_VERSION shape differs"
                )
        else:
            if (
                self.expected_head_version_digest != self.version.canonical_digest
                or type(self.closure) is not LocalWatchClosure
                or (
                    self.reentry is not None
                    and type(self.reentry) is not LocalWatchReentry
                )
            ):
                raise LocalWatchAuthorityError("Local Watch CLOSE shape differs")
            validate_local_watch_closure(self.watch, self.version, self.closure)
            if (
                self.closure.actor_identity_digest != self.actor_identity_digest
                or self.closure.recorded_at < self.version.recorded_at
            ):
                raise LocalWatchAuthorityError(
                    "Local Watch closure actor or chronology differs"
                )
            if self.reentry is not None and (
                self.reentry.watch_id != self.watch.watch_id
                or self.reentry.watch_version_id != self.version.watch_version_id
                or self.reentry.watch_version_digest != self.version.canonical_digest
                or self.reentry.closure_digest != self.closure.canonical_digest
                or self.reentry.actor_identity_digest != self.actor_identity_digest
                or self.reentry.recorded_at < self.closure.recorded_at
            ):
                raise LocalWatchAuthorityError("Local Watch Re-entry binding differs")
            if (
                self.closure.outcome is LocalWatchClosureOutcome.CONVERSION_PROPOSED
                and self.reentry is not None
            ):
                raise LocalWatchAuthorityError(
                    "conversion proposal cannot be a supplemental re-entry"
                )

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "action": self.action.value,
                "actor_identity_digest": self.actor_identity_digest,
                "closure": None if self.closure is None else _embedded(self.closure),
                "command_id": self.command_id,
                "expected_head_version_digest": self.expected_head_version_digest,
                "idempotency_key": self.idempotency_key,
                "reentry": None if self.reentry is None else _embedded(self.reentry),
                "request_id": self.request_id,
                "schema_version": self.schema_version,
                "version": _embedded(self.version),
                "watch": _embedded(self.watch),
            }
        )

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, LOCAL_WATCH_COMMAND, _COMMAND_FIELDS)
        for field, kind in (
            ("watch", EventScopedLocalWatch),
            ("version", LocalWatchVersion),
        ):
            if type(value[field]) is not dict:
                raise LocalWatchAuthorityError(f"{field} differs")
            value[field] = kind.from_bytes(canonical_json_bytes(value[field]))
        for field, kind in (
            ("closure", LocalWatchClosure),
            ("reentry", LocalWatchReentry),
        ):
            if value[field] is not None:
                if type(value[field]) is not dict:
                    raise LocalWatchAuthorityError(f"{field} differs")
                parser = (
                    kind.from_bytes
                    if kind is LocalWatchClosure
                    else kind.from_canonical_bytes
                )
                value[field] = parser(canonical_json_bytes(value[field]))
        value.pop("schema_version")
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise LocalWatchAuthorityError("Local Watch Command replay differs")
        return result


@dataclass(frozen=True, slots=True)
class LocalWatchSnapshot(_NoEffect):
    watch: EventScopedLocalWatch
    versions: tuple[LocalWatchVersion, ...]
    closure: LocalWatchClosure | None
    reentry: LocalWatchReentry | None

    @property
    def current_version(self) -> LocalWatchVersion:
        return self.versions[-1]

    @property
    def closed(self) -> bool:
        return self.closure is not None


def validate_local_watch_command(
    command: LocalWatchCommand,
    *,
    existing_versions: tuple[LocalWatchVersion, ...] = (),
    conversion_proposal: LocalityCoverageProposal | None = None,
) -> None:
    if type(command) is not LocalWatchCommand or type(existing_versions) is not tuple:
        raise LocalWatchAuthorityError("Local Watch validation input differs")
    if command.action is LocalWatchAction.CREATE:
        if existing_versions:
            raise LocalWatchAuthorityError("Local Watch CREATE already exists")
        validate_local_watch_version_chain(command.watch, (command.version,))
    elif command.action is LocalWatchAction.APPEND_VERSION:
        validate_local_watch_version_chain(
            command.watch, (*existing_versions, command.version)
        )
        if (
            not existing_versions
            or command.expected_head_version_digest
            != existing_versions[-1].canonical_digest
        ):
            raise LocalWatchAuthorityError("Local Watch version CAS differs")
    else:
        if (
            not existing_versions
            or command.version != existing_versions[-1]
            or command.expected_head_version_digest
            != existing_versions[-1].canonical_digest
        ):
            raise LocalWatchAuthorityError("Local Watch closure CAS differs")
        validate_local_watch_closure(
            command.watch,
            command.version,
            command.closure,  # type: ignore[arg-type]
        )
    closure = command.closure
    if (
        closure is not None
        and closure.outcome is LocalWatchClosureOutcome.CONVERSION_PROPOSED
    ):
        if (
            type(conversion_proposal) is not LocalityCoverageProposal
            or conversion_proposal.digest != closure.locality_coverage_proposal_digest
        ):
            raise LocalWatchAuthorityError(
                "conversion requires the exact separate Locality Coverage Proposal"
            )
    elif conversion_proposal is not None:
        raise LocalWatchAuthorityError("unexpected Locality Coverage Proposal")


_TOKEN_PORT = object()


class LocalWatchReadPort(_NoEffect):
    __slots__ = ("_connection",)

    def __init__(self, token: object, connection: sqlite3.Connection) -> None:
        if token is not _TOKEN_PORT:
            raise LocalWatchAuthorityError(
                "Local Watch read port construction is private"
            )
        object.__setattr__(self, "_connection", connection)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("LocalWatchReadPort is immutable")

    def _snapshot(self, function, *args):
        owns = not self._connection.in_transaction
        if owns:
            self._connection.execute("BEGIN")
        try:
            result = function(*args)
        except BaseException:
            if owns and self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
        if owns:
            self._connection.execute("COMMIT")
        return result

    def _load(self, watch_id: str) -> LocalWatchSnapshot:
        row = self._connection.execute(
            "SELECT watch_bytes,watch_digest,subject_kind,subject_id,subject_version_digest,"
            "owner_identity_digest,created_at FROM event_scoped_local_watches WHERE watch_id=?",
            (watch_id,),
        ).fetchone()
        if row is None:
            raise LocalWatchAuthorityError("Event-Scoped Local Watch is absent")
        watch = EventScopedLocalWatch.from_bytes(bytes(row[0]))
        version_rows = self._connection.execute(
            "SELECT watch_version_id,version_ordinal,previous_version_digest,version_bytes,"
            "version_digest,status,starts_at,review_at,expires_at,command_bytes,command_digest,"
            "command_id,request_id,actor_identity_digest,idempotency_key,recorded_at "
            "FROM event_scoped_local_watch_versions WHERE watch_id=? ORDER BY version_ordinal",
            (watch_id,),
        ).fetchall()
        versions: list[LocalWatchVersion] = []
        for item in version_rows:
            version = LocalWatchVersion.from_bytes(bytes(item[3]))
            command = LocalWatchCommand.from_canonical_bytes(bytes(item[9]))
            if (
                version.watch_version_id != item[0]
                or version.version_ordinal != item[1]
                or version.previous_version_digest != item[2]
                or version.canonical_digest != item[4]
                or version.status.value != item[5]
                or version.starts_at != item[6]
                or version.review_at != item[7]
                or version.expires_at != item[8]
                or command.digest != item[10]
                or command.command_id != item[11]
                or command.request_id != item[12]
                or command.actor_identity_digest != item[13]
                or command.idempotency_key != item[14]
                or version.recorded_at != item[15]
                or command.watch != watch
                or command.version != version
            ):
                raise LocalWatchAuthorityError(
                    "Local Watch Version retained representation differs"
                )
            versions.append(version)
        chain = validate_local_watch_version_chain(watch, tuple(versions))
        head = self._connection.execute(
            "SELECT current_version_id,current_version_digest,current_version_ordinal,"
            "closed,closure_digest,updated_at FROM event_scoped_local_watch_heads WHERE watch_id=?",
            (watch_id,),
        ).fetchone()
        if head is None or (
            watch.canonical_digest != row[1]
            or watch.subject_kind.value != row[2]
            or watch.subject_id != row[3]
            or watch.subject_version_digest != row[4]
            or watch.owner_identity_digest != row[5]
            or watch.created_at != row[6]
            or head[0] != chain[-1].watch_version_id
            or head[1] != chain[-1].canonical_digest
            or head[2] != chain[-1].version_ordinal
        ):
            raise LocalWatchAuthorityError(
                "Local Watch retained representation differs"
            )
        closure_row = self._connection.execute(
            "SELECT closure_bytes,closure_digest,watch_version_id,watch_version_digest,"
            "outcome,effective_at,locality_coverage_proposal_digest,reentry_bytes,"
            "reentry_digest,reentry_id,command_bytes,command_digest,command_id,request_id,"
            "actor_identity_digest,idempotency_key,recorded_at "
            "FROM event_scoped_local_watch_closures WHERE watch_id=?",
            (watch_id,),
        ).fetchone()
        closure = None
        reentry = None
        if closure_row is not None:
            closure = LocalWatchClosure.from_bytes(bytes(closure_row[0]))
            command = LocalWatchCommand.from_canonical_bytes(bytes(closure_row[10]))
            reentry = (
                None
                if closure_row[7] is None
                else LocalWatchReentry.from_canonical_bytes(bytes(closure_row[7]))
            )
            validate_local_watch_closure(watch, chain[-1], closure)
            if (
                closure.canonical_digest != closure_row[1]
                or closure.watch_version_id != closure_row[2]
                or closure.watch_version_digest != closure_row[3]
                or closure.outcome.value != closure_row[4]
                or closure.effective_at != closure_row[5]
                or closure.locality_coverage_proposal_digest != closure_row[6]
                or (None if reentry is None else reentry.digest) != closure_row[8]
                or (None if reentry is None else reentry.reentry_id) != closure_row[9]
                or command.digest != closure_row[11]
                or command.command_id != closure_row[12]
                or command.request_id != closure_row[13]
                or command.actor_identity_digest != closure_row[14]
                or command.idempotency_key != closure_row[15]
                or closure.recorded_at != closure_row[16]
                or command.watch != watch
                or command.version != chain[-1]
                or command.closure != closure
                or command.reentry != reentry
            ):
                raise LocalWatchAuthorityError(
                    "Local Watch Closure retained representation differs"
                )
        if (
            bool(head[3]) is not (closure is not None)
            or head[4] != (None if closure is None else closure.canonical_digest)
            or head[5]
            != (chain[-1].recorded_at if closure is None else closure.recorded_at)
        ):
            raise LocalWatchAuthorityError("Local Watch head differs")
        return LocalWatchSnapshot(watch, chain, closure, reentry)

    @_total("Local Watch replay failed")
    def load(self, watch_id: str) -> LocalWatchSnapshot:
        _uuid(watch_id, "watch_id")
        return self._snapshot(self._load, watch_id)

    @_total("Local Watch command replay failed")
    def command(self, command_id: str) -> LocalWatchCommand:
        _uuid(command_id, "command_id")

        def read() -> LocalWatchCommand:
            rows = self._connection.execute(
                "SELECT command_bytes FROM event_scoped_local_watch_versions WHERE command_id=? "
                "UNION ALL SELECT command_bytes FROM event_scoped_local_watch_closures WHERE command_id=?",
                (command_id, command_id),
            ).fetchall()
            if len(rows) != 1:
                raise LocalWatchAuthorityError(
                    "Local Watch Command is absent or ambiguous"
                )
            command = LocalWatchCommand.from_canonical_bytes(bytes(rows[0][0]))
            self._load(command.watch.watch_id)
            return command

        return self._snapshot(read)


class LocalWatchAuthority(LocalWatchReadPort):
    """Transactional v29 writer with exact replay, CAS and terminal closure."""

    __slots__ = ()

    def _matching_replay(self, command: LocalWatchCommand) -> bytes | None:
        rows = self._connection.execute(
            "SELECT command_bytes FROM event_scoped_local_watch_versions "
            "WHERE command_id=? OR request_id=? OR idempotency_key=? "
            "UNION ALL SELECT command_bytes FROM event_scoped_local_watch_closures "
            "WHERE command_id=? OR request_id=? OR idempotency_key=?",
            (
                command.command_id,
                command.request_id,
                command.idempotency_key,
                command.command_id,
                command.request_id,
                command.idempotency_key,
            ),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1 or bytes(rows[0][0]) != command.canonical_bytes:
            raise LocalWatchAuthorityError("Local Watch Command identity collision")
        return bytes(rows[0][0])

    def _insert_version(self, command: LocalWatchCommand) -> None:
        version = command.version
        self._connection.execute(
            "INSERT INTO event_scoped_local_watch_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                version.watch_version_id,
                version.watch_id,
                version.version_ordinal,
                version.previous_version_digest,
                version.canonical_bytes,
                version.canonical_digest,
                version.status.value,
                version.starts_at,
                version.review_at,
                version.expires_at,
                command.canonical_bytes,
                command.digest,
                command.command_id,
                command.request_id,
                command.actor_identity_digest,
                command.idempotency_key,
                version.recorded_at,
            ),
        )

    @_total("Local Watch command failed")
    def record(
        self,
        raw: bytes,
        *,
        conversion_proposal: LocalityCoverageProposal | None = None,
    ) -> LocalWatchSnapshot:
        command = LocalWatchCommand.from_canonical_bytes(raw)
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            replay = self._matching_replay(command)
            if replay is not None:
                snapshot = self._load(command.watch.watch_id)
                existing = (
                    ()
                    if command.action is LocalWatchAction.CREATE
                    else snapshot.versions[:-1]
                    if command.action is LocalWatchAction.APPEND_VERSION
                    else snapshot.versions
                )
                validate_local_watch_command(
                    command,
                    existing_versions=existing,
                    conversion_proposal=conversion_proposal,
                )
                self._connection.execute("COMMIT")
                return snapshot
            if command.action is LocalWatchAction.CREATE:
                validate_local_watch_command(
                    command, conversion_proposal=conversion_proposal
                )
                self._connection.execute(
                    "INSERT INTO event_scoped_local_watches VALUES(?,?,?,?,?,?,?,?)",
                    (
                        command.watch.watch_id,
                        command.watch.canonical_bytes,
                        command.watch.canonical_digest,
                        command.watch.subject_kind.value,
                        command.watch.subject_id,
                        command.watch.subject_version_digest,
                        command.watch.owner_identity_digest,
                        command.watch.created_at,
                    ),
                )
                self._insert_version(command)
                self._connection.execute(
                    "INSERT INTO event_scoped_local_watch_heads VALUES(?,?,?,?,?,?,?)",
                    (
                        command.watch.watch_id,
                        command.version.watch_version_id,
                        command.version.canonical_digest,
                        1,
                        0,
                        None,
                        command.version.recorded_at,
                    ),
                )
            else:
                snapshot = self._load(command.watch.watch_id)
                if snapshot.closed:
                    raise LocalWatchAuthorityError("Local Watch lifecycle is terminal")
                if command.watch != snapshot.watch:
                    raise LocalWatchAuthorityError(
                        "Local Watch immutable identity differs"
                    )
                validate_local_watch_command(
                    command,
                    existing_versions=snapshot.versions,
                    conversion_proposal=conversion_proposal,
                )
                if command.action is LocalWatchAction.APPEND_VERSION:
                    self._insert_version(command)
                    self._connection.execute(
                        "UPDATE event_scoped_local_watch_heads SET current_version_id=?,"
                        "current_version_digest=?,current_version_ordinal=?,updated_at=? "
                        "WHERE watch_id=?",
                        (
                            command.version.watch_version_id,
                            command.version.canonical_digest,
                            command.version.version_ordinal,
                            command.version.recorded_at,
                            command.watch.watch_id,
                        ),
                    )
                else:
                    assert command.closure is not None
                    self._connection.execute(
                        "INSERT INTO event_scoped_local_watch_closures VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            command.closure.closure_id,
                            command.watch.watch_id,
                            command.version.watch_version_id,
                            command.version.canonical_digest,
                            command.closure.canonical_bytes,
                            command.closure.canonical_digest,
                            command.closure.outcome.value,
                            command.closure.effective_at,
                            command.closure.locality_coverage_proposal_digest,
                            None
                            if command.reentry is None
                            else command.reentry.canonical_bytes,
                            None if command.reentry is None else command.reentry.digest,
                            None
                            if command.reentry is None
                            else command.reentry.reentry_id,
                            command.canonical_bytes,
                            command.digest,
                            command.command_id,
                            command.request_id,
                            command.actor_identity_digest,
                            command.idempotency_key,
                            command.closure.recorded_at,
                        ),
                    )
                    self._connection.execute(
                        "UPDATE event_scoped_local_watch_heads SET closed=1,"
                        "closure_digest=?,updated_at=? WHERE watch_id=?",
                        (
                            command.closure.canonical_digest,
                            command.closure.recorded_at,
                            command.watch.watch_id,
                        ),
                    )
            retained = self._load(command.watch.watch_id)
            self._connection.execute("COMMIT")
            return retained
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise

    def read_port(self) -> LocalWatchReadPort:
        return LocalWatchReadPort(_TOKEN_PORT, self._connection)

    def close(self) -> None:
        self._connection.close()


@_total("Local Watch authority open failed")
def open_local_watch_authority(
    path: str | Path,
    *,
    applied_at: str,
    timeout_seconds: float = 5.0,
) -> LocalWatchAuthority:
    _timestamp(applied_at, "applied_at")
    database = Path(path)
    existed = database.exists() and database.stat().st_size > 0
    connection = sqlite3.connect(
        database,
        isolation_level=None,
        timeout=timeout_seconds,
        check_same_thread=False,
    )
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        if existed:
            prepare_pending_migration_backup(connection)
        apply_pending_migrations(connection, applied_at=applied_at)
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise LocalWatchAuthorityError("checked v29 schema differs")
        return LocalWatchAuthority(_TOKEN_PORT, connection)
    except BaseException:
        connection.close()
        raise


__all__ = [
    "LOCAL_WATCH_AUTHORITY",
    "LOCAL_WATCH_COMMAND",
    "LOCAL_WATCH_REENTRY",
    "LOCAL_WATCH_REENTRY_AUTHORITY",
    "LocalWatchAction",
    "LocalWatchAuthority",
    "LocalWatchAuthorityError",
    "LocalWatchCommand",
    "LocalWatchReadPort",
    "LocalWatchReentry",
    "LocalWatchReentryKind",
    "LocalWatchSnapshot",
    "open_local_watch_authority",
    "validate_local_watch_command",
]
