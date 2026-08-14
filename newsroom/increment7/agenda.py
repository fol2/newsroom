"""Strict, effect-free Planned Agenda contracts for Increment 7A1.

Agenda values are immutable expectations.  Constructing, parsing, opening a
window, or observing clock passage grants no Signal, Lead, Candidate, evidence,
publication, provider, scheduling, or other runtime authority.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Self

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)

PLANNED_AGENDA_ITEM = "newsroom.increment7.planned-agenda-item.v1"
PLANNED_AGENDA_VERSION = "newsroom.increment7.planned-agenda-version.v1"
AGENDA_TIME_PRECISION = "EXPLICIT_AND_UNWIDENED"
AGENDA_RESOLUTION_VOCABULARY = "newsroom.increment7.agenda-resolution-vocabulary.v1"
NO_CLOCK_GENERATED_EDITORIAL_RECORD = (
    "CLOCK_PASSAGE_CREATES_NO_SIGNAL_LEAD_CANDIDATE_OR_EVIDENCE"
)
MAX_AGENDA_CANONICAL_BYTES = 1_048_576
MAX_TEXT_BYTES = 2_048
MAX_PATHS = 16
MAX_REFERENCES = 32
MAX_UNCERTAINTIES = 32

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_DATE = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])\Z")
_UTC = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)


class AgendaContractError(ValueError):
    """Untrusted Agenda bytes or values failed the exact v1 contract."""


class AgendaKind(StrEnum):
    RELEASE = "RELEASE"
    PROCEEDING = "PROCEEDING"
    EFFECTIVE_DATE = "EFFECTIVE_DATE"
    DEADLINE = "DEADLINE"
    EXPECTED_DEVELOPMENT = "EXPECTED_DEVELOPMENT"


class AgendaScheduleStatus(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"
    POSTPONED_WITHOUT_DATE = "POSTPONED_WITHOUT_DATE"
    CANCELLED = "CANCELLED"
    WITHDRAWN = "WITHDRAWN"


class AgendaTimePrecision(StrEnum):
    EXACT_INSTANT = "EXACT_INSTANT"
    EXACT_WINDOW = "EXACT_WINDOW"
    DATE_ONLY = "DATE_ONLY"
    APPROXIMATE = "APPROXIMATE"
    TIME_ZONE_AMBIGUOUS = "TIME_ZONE_AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


class AgendaResolutionKind(StrEnum):
    OCCURRENCE_CONFIRMED = "OCCURRENCE_CONFIRMED"
    MISSED_NOT_OBSERVED = "MISSED_NOT_OBSERVED"
    LATE_OCCURRENCE = "LATE_OCCURRENCE"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED_WITH_SOURCE_EVIDENCE = "CANCELLED_WITH_SOURCE_EVIDENCE"
    POSTPONED_WITH_SOURCE_EVIDENCE = "POSTPONED_WITH_SOURCE_EVIDENCE"
    WITHDRAWN_WITH_SOURCE_EVIDENCE = "WITHDRAWN_WITH_SOURCE_EVIDENCE"
    CHECK_FAILED = "CHECK_FAILED"
    CHECK_PARTIAL = "CHECK_PARTIAL"
    CHECK_UNAVAILABLE = "CHECK_UNAVAILABLE"
    AMBIGUOUS = "AMBIGUOUS"


class CoverageBasis(StrEnum):
    ORIGINATING_AUTHORITY = "ORIGINATING_AUTHORITY"
    RESPONSIBLE_OPERATOR = "RESPONSIBLE_OPERATOR"
    PLANNED_AGENDA = "PLANNED_AGENDA"
    ESTABLISHED_MEDIA_RADAR = "ESTABLISHED_MEDIA_RADAR"
    SPECIALIST_OR_LOCAL_RADAR = "SPECIALIST_OR_LOCAL_RADAR"
    MANUAL_EDITOR_OR_READER = "MANUAL_EDITOR_OR_READER"


class AgendaPathKind(StrEnum):
    EXPECTATION = "EXPECTATION"
    OCCURRENCE_CONFIRMATION = "OCCURRENCE_CONFIRMATION"


class AgendaUrgency(StrEnum):
    IMMEDIATE = "IMMEDIATE"
    TIME_SENSITIVE = "TIME_SENSITIVE"
    ROUTINE = "ROUTINE"
    UNKNOWN = "UNKNOWN"


class _NoEffect:
    authorises_authority = False
    authorises_persistence = False
    authorises_external_effect = False
    authorises_publication = False
    authorises_evidence = False
    authorises_egress = False
    authorises_provider = False
    authorises_schedule = False
    production_activation_authorised = False
    creates_signal = False
    creates_lead = False
    creates_candidate = False
    creates_occurrence = False


def _exact_dict(
    value: object, fields: tuple[str, ...], label: str
) -> dict[str, object]:
    if type(value) is not dict or tuple(value) != tuple(sorted(fields)):
        raise AgendaContractError(f"{label} fields are not exact and ordered")
    return value


def _text(value: object, field: str, *, maximum: int = MAX_TEXT_BYTES) -> str:
    try:
        encoded_size = len(value.encode()) if type(value) is str else 0
    except UnicodeEncodeError as exc:
        raise AgendaContractError(f"{field} must be bounded canonical text") from exc
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or encoded_size > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise AgendaContractError(f"{field} must be bounded canonical text")
    return value


def _enum[T: StrEnum](enum_type: type[T], value: object, field: str) -> T:
    if type(value) is not str and type(value) is not enum_type:
        raise AgendaContractError(f"{field} must be a closed vocabulary value")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise AgendaContractError(f"{field} must be a closed vocabulary value") from exc


def _token(value: object, field: str) -> str:
    value = _text(value, field, maximum=256)
    if _TOKEN.fullmatch(value) is None:
        raise AgendaContractError(f"{field} must be a canonical token")
    return value


def _uuid(value: object, field: str) -> str:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        raise AgendaContractError(f"{field} must be a canonical UUID")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError as exc:
        raise AgendaContractError(f"{field} must be a canonical UUID") from exc
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise AgendaContractError(
            f"{field} must be a canonical SHA-256 digest"
        ) from exc


def _timestamp(value: object, field: str) -> str:
    value = _text(value, field, maximum=27)
    if _UTC.fullmatch(value) is None:
        raise AgendaContractError(f"{field} must be an exact UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise AgendaContractError(f"{field} must be an exact UTC timestamp") from exc
    return value


def _strings(value: object, field: str, maximum: int) -> tuple[str, ...]:
    if type(value) is not list or len(value) > maximum:
        raise AgendaContractError(f"{field} must be a bounded array")
    result = tuple(_text(item, field) for item in value)
    if tuple(sorted(set(result))) != result:
        raise AgendaContractError(f"{field} must be unique and sorted")
    return result


def _load(raw: bytes, schema: str, fields: tuple[str, ...]) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_AGENDA_CANONICAL_BYTES:
        raise AgendaContractError("Agenda bytes are not bounded")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except AgendaContractError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
        RecursionError,
        ValueError,
    ) as exc:
        raise AgendaContractError("Agenda bytes are not canonical JSON") from exc
    if raw != canonical:
        raise AgendaContractError("Agenda bytes are not exact canonical JSON")
    record = _exact_dict(value, fields, "Agenda record")
    if record["schema_version"] != schema:
        raise AgendaContractError("Agenda schema version differs")
    return record


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise AgendaContractError(f"duplicate object name: {name}")
        result[name] = value
    return result


@dataclass(frozen=True, slots=True)
class AgendaPathReference(_NoEffect):
    kind: AgendaPathKind
    source_definition_version_id: str
    path_policy_version: str
    rights_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _enum(AgendaPathKind, self.kind, "kind"),
        )
        _uuid(self.source_definition_version_id, "source_definition_version_id")
        _token(self.path_policy_version, "path_policy_version")
        _token(self.rights_reference, "rights_reference")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "source_definition_version_id": self.source_definition_version_id,
            "path_policy_version": self.path_policy_version,
            "rights_reference": self.rights_reference,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        fields = (
            "kind",
            "source_definition_version_id",
            "path_policy_version",
            "rights_reference",
        )
        raw = _exact_dict(value, fields, "Agenda path")
        return cls(**raw)  # type: ignore[arg-type]


_ITEM_FIELDS = (
    "schema_version",
    "agenda_item_id",
    "agenda_kind",
    "stable_subject_key",
    "created_from_source_revision_id",
    "created_at",
)


@dataclass(frozen=True, slots=True)
class PlannedAgendaItem(_NoEffect):
    agenda_item_id: str
    agenda_kind: AgendaKind
    stable_subject_key: str
    created_from_source_revision_id: str
    created_at: str
    schema_version: str = PLANNED_AGENDA_ITEM

    def __post_init__(self) -> None:
        if self.schema_version != PLANNED_AGENDA_ITEM:
            raise AgendaContractError("Agenda Item schema version differs")
        _uuid(self.agenda_item_id, "agenda_item_id")
        object.__setattr__(
            self,
            "agenda_kind",
            _enum(AgendaKind, self.agenda_kind, "agenda_kind"),
        )
        _token(self.stable_subject_key, "stable_subject_key")
        _uuid(self.created_from_source_revision_id, "created_from_source_revision_id")
        _timestamp(self.created_at, "created_at")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                name: getattr(self, name).value
                if isinstance(getattr(self, name), StrEnum)
                else getattr(self, name)
                for name in _ITEM_FIELDS
            }
        )

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls(**_load(raw, PLANNED_AGENDA_ITEM, _ITEM_FIELDS))  # type: ignore[arg-type]


_VERSION_FIELDS = (
    "schema_version",
    "agenda_version_id",
    "agenda_item_id",
    "version_ordinal",
    "predecessor_version_digest",
    "source_revision_id",
    "coverage_basis",
    "expected_subject",
    "time_precision",
    "asserted_start",
    "asserted_end",
    "time_zone",
    "schedule_status",
    "expectation_path",
    "occurrence_confirmation_paths",
    "geography",
    "urgency",
    "relationship_references",
    "uncertainties",
    "recorded_at",
)


@dataclass(frozen=True, slots=True)
class PlannedAgendaVersion(_NoEffect):
    agenda_version_id: str
    agenda_item_id: str
    version_ordinal: int
    predecessor_version_digest: str | None
    source_revision_id: str
    coverage_basis: CoverageBasis
    expected_subject: str
    time_precision: AgendaTimePrecision
    asserted_start: str | None
    asserted_end: str | None
    time_zone: str | None
    schedule_status: AgendaScheduleStatus
    expectation_path: AgendaPathReference
    occurrence_confirmation_paths: tuple[AgendaPathReference, ...]
    geography: str | None
    urgency: AgendaUrgency
    relationship_references: tuple[str, ...]
    uncertainties: tuple[str, ...]
    recorded_at: str
    schema_version: str = PLANNED_AGENDA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PLANNED_AGENDA_VERSION:
            raise AgendaContractError("Agenda Version schema version differs")
        _uuid(self.agenda_version_id, "agenda_version_id")
        _uuid(self.agenda_item_id, "agenda_item_id")
        if (
            type(self.version_ordinal) is not int
            or not 1 <= self.version_ordinal <= 1_000_000
        ):
            raise AgendaContractError(
                "version_ordinal must be a bounded positive integer"
            )
        if self.version_ordinal == 1:
            if self.predecessor_version_digest is not None:
                raise AgendaContractError(
                    "first Agenda Version cannot have a predecessor"
                )
        elif self.predecessor_version_digest is None:
            raise AgendaContractError(
                "successor Agenda Version requires predecessor digest"
            )
        else:
            _digest(self.predecessor_version_digest, "predecessor_version_digest")
        _uuid(self.source_revision_id, "source_revision_id")
        object.__setattr__(
            self,
            "coverage_basis",
            _enum(CoverageBasis, self.coverage_basis, "coverage_basis"),
        )
        _text(self.expected_subject, "expected_subject")
        object.__setattr__(
            self,
            "time_precision",
            _enum(AgendaTimePrecision, self.time_precision, "time_precision"),
        )
        object.__setattr__(
            self,
            "schedule_status",
            _enum(AgendaScheduleStatus, self.schedule_status, "schedule_status"),
        )
        object.__setattr__(
            self,
            "urgency",
            _enum(AgendaUrgency, self.urgency, "urgency"),
        )
        self._validate_time()
        if (
            type(self.expectation_path) is not AgendaPathReference
            or self.expectation_path.kind is not AgendaPathKind.EXPECTATION
        ):
            raise AgendaContractError("expectation_path must be an expectation path")
        if type(self.occurrence_confirmation_paths) is not tuple:
            raise AgendaContractError(
                "occurrence_confirmation_paths must be bounded confirmation paths"
            )
        paths = self.occurrence_confirmation_paths
        if (
            not paths
            or len(paths) > MAX_PATHS
            or any(
                type(path) is not AgendaPathReference
                or path.kind is not AgendaPathKind.OCCURRENCE_CONFIRMATION
                for path in paths
            )
        ):
            raise AgendaContractError(
                "occurrence_confirmation_paths must be bounded confirmation paths"
            )
        if tuple(
            sorted({canonical_json_bytes(path.to_dict()) for path in paths})
        ) != tuple(canonical_json_bytes(path.to_dict()) for path in paths):
            raise AgendaContractError(
                "occurrence_confirmation_paths must be unique and sorted"
            )
        object.__setattr__(self, "occurrence_confirmation_paths", paths)
        if self.geography is not None:
            _text(self.geography, "geography")
        for field, values, maximum in (
            ("relationship_references", self.relationship_references, MAX_REFERENCES),
            ("uncertainties", self.uncertainties, MAX_UNCERTAINTIES),
        ):
            if type(values) is not tuple or len(values) > maximum:
                raise AgendaContractError(f"{field} must be unique, sorted and bounded")
            for value in values:
                (_digest if field == "relationship_references" else _text)(value, field)
            if tuple(sorted(set(values))) != values:
                raise AgendaContractError(f"{field} must be unique, sorted and bounded")
        _timestamp(self.recorded_at, "recorded_at")

    def _validate_time(self) -> None:
        start, end, zone, precision = (
            self.asserted_start,
            self.asserted_end,
            self.time_zone,
            self.time_precision,
        )
        if zone is not None:
            _text(zone, "time_zone", maximum=128)
        if precision in {
            AgendaTimePrecision.EXACT_INSTANT,
            AgendaTimePrecision.EXACT_WINDOW,
        }:
            if start is None or zone is None:
                raise AgendaContractError(
                    "exact time requires UTC start and explicit time zone"
                )
            _timestamp(start, "asserted_start")
            if precision is AgendaTimePrecision.EXACT_INSTANT and end is not None:
                raise AgendaContractError("exact instant cannot have an end")
            if precision is AgendaTimePrecision.EXACT_WINDOW:
                if end is None:
                    raise AgendaContractError(
                        "exact window requires an ordered UTC end"
                    )
                _timestamp(end, "asserted_end")
                if end <= start:
                    raise AgendaContractError(
                        "exact window requires an ordered UTC end"
                    )
        elif precision is AgendaTimePrecision.DATE_ONLY:
            if start is None or end is not None:
                raise AgendaContractError("date-only schedule must remain date-only")
            start = _text(start, "asserted_start", maximum=10)
            if _DATE.fullmatch(start) is None:
                raise AgendaContractError("date-only schedule must remain date-only")
            try:
                datetime.strptime(start, "%Y-%m-%d")
            except ValueError as exc:
                raise AgendaContractError(
                    "date-only schedule must remain date-only"
                ) from exc
        elif precision is AgendaTimePrecision.TIME_ZONE_AMBIGUOUS:
            if start is None or zone is not None:
                raise AgendaContractError(
                    "time-zone-ambiguous schedule cannot invent a zone"
                )
            _text(start, "asserted_start", maximum=128)
            if end is not None:
                _text(end, "asserted_end", maximum=128)
        elif precision is AgendaTimePrecision.APPROXIMATE:
            if start is None:
                raise AgendaContractError(
                    "approximate schedule requires its asserted text"
                )
            _text(start, "asserted_start", maximum=128)
            if end is not None:
                _text(end, "asserted_end", maximum=128)
        elif any(value is not None for value in (start, end, zone)):
            raise AgendaContractError(
                "unknown schedule cannot contain invented time fields"
            )
        if (
            self.schedule_status
            in {
                AgendaScheduleStatus.CANCELLED,
                AgendaScheduleStatus.WITHDRAWN,
                AgendaScheduleStatus.POSTPONED_WITHOUT_DATE,
            }
            and not self.uncertainties
        ):
            raise AgendaContractError(
                "non-active status requires attributed source uncertainty"
            )

    def _dict(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for name in _VERSION_FIELDS:
            value = getattr(self, name)
            if isinstance(value, StrEnum):
                value = value.value
            elif isinstance(value, AgendaPathReference):
                value = value.to_dict()
            elif name == "occurrence_confirmation_paths":
                value = [path.to_dict() for path in value]
            elif isinstance(value, tuple):
                value = list(value)
            result[name] = value
        return result

    def _assertion_dict(self) -> dict[str, object]:
        lineage_fields = {
            "agenda_version_id",
            "version_ordinal",
            "predecessor_version_digest",
            "recorded_at",
        }
        return {
            name: value
            for name, value in self._dict().items()
            if name not in lineage_fields
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self._dict())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _load(raw, PLANNED_AGENDA_VERSION, _VERSION_FIELDS)
        value["expectation_path"] = AgendaPathReference.from_dict(
            value["expectation_path"]
        )
        paths = value["occurrence_confirmation_paths"]
        if type(paths) is not list:
            raise AgendaContractError("occurrence_confirmation_paths must be an array")
        value["occurrence_confirmation_paths"] = tuple(
            AgendaPathReference.from_dict(path) for path in paths
        )
        for field in ("relationship_references", "uncertainties"):
            raw_values = value[field]
            if type(raw_values) is not list:
                raise AgendaContractError(f"{field} must be an array")
            value[field] = tuple(raw_values)
        return cls(**value)  # type: ignore[arg-type]


def validate_agenda_successor(
    prior: PlannedAgendaVersion, successor: PlannedAgendaVersion
) -> None:
    """Validate immutable adjacency without allocating or retaining a Version."""
    if (
        type(prior) is not PlannedAgendaVersion
        or type(successor) is not PlannedAgendaVersion
    ):
        raise AgendaContractError(
            "Agenda successor values must be exact typed Versions"
        )
    if (
        successor.agenda_version_id == prior.agenda_version_id
        or successor.agenda_item_id != prior.agenda_item_id
        or successor.version_ordinal != prior.version_ordinal + 1
        or successor.predecessor_version_digest != prior.digest
    ):
        raise AgendaContractError(
            "Agenda successor does not extend the exact prior Version"
        )
    if successor._assertion_dict() == prior._assertion_dict():
        raise AgendaContractError(
            "Agenda successor must record a substantive source assertion"
        )


__all__ = [
    "AGENDA_RESOLUTION_VOCABULARY",
    "AGENDA_TIME_PRECISION",
    "MAX_AGENDA_CANONICAL_BYTES",
    "NO_CLOCK_GENERATED_EDITORIAL_RECORD",
    "PLANNED_AGENDA_ITEM",
    "PLANNED_AGENDA_VERSION",
    "AgendaContractError",
    "AgendaKind",
    "AgendaPathKind",
    "AgendaPathReference",
    "AgendaResolutionKind",
    "AgendaScheduleStatus",
    "AgendaTimePrecision",
    "AgendaUrgency",
    "CoverageBasis",
    "PlannedAgendaItem",
    "PlannedAgendaVersion",
    "validate_agenda_successor",
]
