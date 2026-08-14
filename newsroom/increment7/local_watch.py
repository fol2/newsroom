"""Strict, effect-free Event-Scoped Local Watch contracts for Increment 7D1.

A watch is one bounded editorial question.  These values describe identity,
configuration, expiry and closure; they grant no source access, scheduling,
locality selection, discovery admission, evidence, Candidate or publication
power.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Self

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)

EVENT_SCOPED_LOCAL_WATCH = "newsroom.increment7.event-scoped-local-watch.v1"
LOCAL_WATCH_VERSION = "newsroom.increment7.local-watch-version.v1"
LOCAL_WATCH_CLOSURE = "newsroom.increment7.local-watch-closure.v1"
LOCAL_WATCH_EXPIRY = "EXPLICIT_DEADLINE_DEFAULTS_TO_CLOSURE"
LOCAL_WATCH_CONVERSION_CONDITION = (
    "SEPARATE_LOCALITY_COVERAGE_PROPOSAL_AND_DECISION_REQUIRED"
)
NO_PERMANENT_LOCALITY_INFERENCE = (
    "ONE_OR_REPEATED_WATCHES_CREATE_NO_PERMANENT_LOCALITY_SELECTION"
)
MAX_LOCAL_WATCH_BYTES = 1_048_576
MAX_WATCH_DURATION_SECONDS = 31 * 24 * 60 * 60

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_UTC = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)


class LocalWatchContractError(ValueError):
    """Untrusted Local Watch bytes or values failed the exact v1 contract."""


class LocalWatchSubjectKind(StrEnum):
    EVENT_HYPOTHESIS = "EVENT_HYPOTHESIS"
    NEWS_LEAD = "NEWS_LEAD"
    STORY_CANDIDATE = "STORY_CANDIDATE"
    MAJOR_INCIDENT_QUESTION = "MAJOR_INCIDENT_QUESTION"
    WATCH_CONDITION = "WATCH_CONDITION"
    EVIDENCE_INTAKE_QUESTION = "EVIDENCE_INTAKE_QUESTION"


class LocalWatchSourceRole(StrEnum):
    ORIGINATING_AUTHORITY = "ORIGINATING_AUTHORITY"
    RESPONSIBLE_OPERATOR = "RESPONSIBLE_OPERATOR"
    ESTABLISHED_LOCAL_MEDIA_RADAR = "ESTABLISHED_LOCAL_MEDIA_RADAR"
    PUBLIC_SAFETY_AUTHORITY = "PUBLIC_SAFETY_AUTHORITY"
    ESSENTIAL_SERVICE_AUTHORITY = "ESSENTIAL_SERVICE_AUTHORITY"


class LocalWatchPrivacyClass(StrEnum):
    PUBLIC_EVENT_SCOPE_ONLY = "PUBLIC_EVENT_SCOPE_ONLY"
    AGGREGATED_AUDIENCE_BASIS = "AGGREGATED_AUDIENCE_BASIS"


class LocalWatchTransitionKind(StrEnum):
    DISCOVERY_SIGNAL_REENTRY = "DISCOVERY_SIGNAL_REENTRY"
    OPERATIONAL_FINDING = "OPERATIONAL_FINDING"
    OWNER_REVIEW = "OWNER_REVIEW"
    CLOSE = "CLOSE"


class LocalWatchVersionStatus(StrEnum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    PAUSED = "PAUSED"
    EXTENDED = "EXTENDED"


class LocalWatchClosureCondition(StrEnum):
    EXPIRY_REACHED = "EXPIRY_REACHED"
    EVENT_RESOLVED = "EVENT_RESOLVED"
    OWNER_DECISION = "OWNER_DECISION"
    RIGHTS_WITHDRAWN = "RIGHTS_WITHDRAWN"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    OPERATIONAL_PROFILE_INVALID = "OPERATIONAL_PROFILE_INVALID"


class LocalWatchConversionCondition(StrEnum):
    REVIEWED_COVERAGE_GAP = "REVIEWED_COVERAGE_GAP"
    PROSPECTIVE_CONTRIBUTION = "PROSPECTIVE_CONTRIBUTION"
    RIGHTS_READY = "RIGHTS_READY"
    OPERATIONAL_READINESS = "OPERATIONAL_READINESS"
    AUDIENCE_NEED_AGGREGATED = "AUDIENCE_NEED_AGGREGATED"
    RESILIENCE_NEED = "RESILIENCE_NEED"


class LocalWatchClosureOutcome(StrEnum):
    EXPIRED = "EXPIRED"
    CLOSED_BY_OWNER = "CLOSED_BY_OWNER"
    EVENT_RESOLVED = "EVENT_RESOLVED"
    CANCELLED = "CANCELLED"
    CONVERSION_PROPOSED = "CONVERSION_PROPOSED"
    SUPERSEDED = "SUPERSEDED"


class _NoEffect:
    authorises_authority = False
    authorises_persistence = False
    authorises_external_effect = False
    authorises_source_access = False
    authorises_search = False
    authorises_provider = False
    authorises_credentials = False
    authorises_egress = False
    authorises_spend = False
    authorises_schedule = False
    authorises_evidence = False
    authorises_locality = False
    authorises_source_portfolio = False
    authorises_permanent_selection = False
    authorises_publication = False
    creates_signal = False
    creates_lead = False
    creates_candidate = False
    creates_coverage_unit = False
    creates_locality_proposal = False
    production_activation_authorised = False


def _text(value: object, field: str, maximum: int = 2_048) -> str:
    try:
        size = len(value.encode()) if type(value) is str else 0
    except UnicodeError as exc:
        raise LocalWatchContractError(f"{field} must be canonical text") from exc
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or size > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise LocalWatchContractError(f"{field} must be canonical text")
    return value


def _token(value: object, field: str) -> str:
    value = _text(value, field, 256)
    if _TOKEN.fullmatch(value) is None:
        raise LocalWatchContractError(f"{field} must be a canonical token")
    return value


def _uuid(value: object, field: str) -> str:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        raise LocalWatchContractError(f"{field} must be a canonical UUID")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError as exc:
        raise LocalWatchContractError(f"{field} must be a canonical UUID") from exc
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise LocalWatchContractError(f"{field} must be a SHA-256 digest") from exc


def _timestamp(value: object, field: str) -> str:
    value = _text(value, field, 27)
    if _UTC.fullmatch(value) is None:
        raise LocalWatchContractError(f"{field} must be an exact UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise LocalWatchContractError(
            f"{field} must be an exact UTC timestamp"
        ) from exc
    return value


def _instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _enum[T: StrEnum](kind: type[T], value: object, field: str) -> T:
    if type(value) is not str and type(value) is not kind:
        raise LocalWatchContractError(f"{field} differs")
    try:
        return kind(value)
    except ValueError as exc:
        raise LocalWatchContractError(f"{field} differs") from exc


def _strings(
    value: object,
    field: str,
    *,
    required: bool = False,
    digests: bool = False,
    maximum: int = 32,
) -> tuple[str, ...]:
    if (
        type(value) not in (tuple, list)
        or len(value) > maximum
        or (required and not value)
    ):
        raise LocalWatchContractError(f"{field} must be a bounded array")
    validator = _digest if digests else _token
    result = tuple(validator(item, field) for item in value)
    if tuple(sorted(set(result))) != result:
        raise LocalWatchContractError(f"{field} must be unique and sorted")
    return result


def _enums[T: StrEnum](
    kind: type[T], value: object, field: str, *, required: bool = False
) -> tuple[T, ...]:
    if type(value) not in (tuple, list) or len(value) > 16 or (required and not value):
        raise LocalWatchContractError(f"{field} must be a bounded array")
    result = tuple(_enum(kind, item, field) for item in value)
    if tuple(sorted(set(result), key=str)) != result:
        raise LocalWatchContractError(f"{field} must be unique and sorted")
    return result


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LocalWatchContractError(f"duplicate object name: {key}")
        result[key] = value
    return result


def _document(raw: bytes, schema: str, fields: tuple[str, ...]) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_LOCAL_WATCH_BYTES:
        raise LocalWatchContractError("Local Watch bytes are not bounded")
    try:
        value = json.loads(raw.decode(), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except LocalWatchContractError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
        RecursionError,
        ValueError,
    ) as exc:
        raise LocalWatchContractError(
            "Local Watch bytes are not canonical JSON"
        ) from exc
    if type(value) is not dict or raw != canonical:
        raise LocalWatchContractError("Local Watch bytes are not exact canonical JSON")
    if tuple(value) != tuple(sorted(fields)) or value.get("schema_version") != schema:
        raise LocalWatchContractError("Local Watch fields or schema differ")
    return value


def _record_dict(record: object, fields: tuple[str, ...]) -> dict[str, object]:
    result: dict[str, object] = {}
    for field in fields:
        value = getattr(record, field)
        if isinstance(value, StrEnum):
            value = value.value
        elif isinstance(value, tuple):
            value = [
                item.to_dict()
                if hasattr(item, "to_dict")
                else item.value
                if isinstance(item, StrEnum)
                else item
                for item in value
            ]
        elif hasattr(value, "to_dict"):
            value = value.to_dict()
        result[field] = value
    return result


_SOURCE_FIELDS = (
    "boundary_digest",
    "rights_decision_digest",
    "source_role",
    "source_version_digest",
    "source_version_id",
)


@dataclass(frozen=True, slots=True)
class LocalWatchSourceBinding(_NoEffect):
    source_version_id: str
    source_version_digest: str
    source_role: LocalWatchSourceRole
    rights_decision_digest: str
    boundary_digest: str

    def __post_init__(self) -> None:
        _token(self.source_version_id, "source_version_id")
        _digest(self.source_version_digest, "source_version_digest")
        object.__setattr__(
            self,
            "source_role",
            _enum(LocalWatchSourceRole, self.source_role, "source_role"),
        )
        _digest(self.rights_decision_digest, "rights_decision_digest")
        _digest(self.boundary_digest, "boundary_digest")

    def to_dict(self) -> dict[str, object]:
        return _record_dict(self, _SOURCE_FIELDS)

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict or tuple(value) != tuple(sorted(_SOURCE_FIELDS)):
            raise LocalWatchContractError("Local Watch Source Binding fields differ")
        return cls(**value)  # type: ignore[arg-type]


_BUDGET_FIELDS = (
    "max_checks",
    "max_cost_microunits",
    "max_fetched_bytes",
    "max_results",
    "max_wall_seconds",
)


@dataclass(frozen=True, slots=True)
class LocalWatchGrossBudget(_NoEffect):
    max_checks: int
    max_results: int
    max_fetched_bytes: int
    max_wall_seconds: int
    max_cost_microunits: int

    def __post_init__(self) -> None:
        bounds = {
            "max_checks": (1, 1_000),
            "max_results": (1, 10_000),
            "max_fetched_bytes": (1, 1_000_000_000),
            "max_wall_seconds": (1, MAX_WATCH_DURATION_SECONDS),
            "max_cost_microunits": (0, 1_000_000_000),
        }
        for field, (minimum, maximum) in bounds.items():
            value = getattr(self, field)
            if type(value) is not int or not minimum <= value <= maximum:
                raise LocalWatchContractError(f"{field} must be a bounded integer")

    def to_dict(self) -> dict[str, object]:
        return _record_dict(self, _BUDGET_FIELDS)

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict or tuple(value) != tuple(sorted(_BUDGET_FIELDS)):
            raise LocalWatchContractError("Local Watch Gross Budget fields differ")
        return cls(**value)  # type: ignore[arg-type]


_WATCH_FIELDS = (
    "schema_version",
    "watch_id",
    "subject_kind",
    "subject_id",
    "subject_version_digest",
    "event_purpose",
    "owner_identity_digest",
    "governing_policy_digests",
    "privacy_classification",
    "privacy_policy_digest",
    "created_at",
)


@dataclass(frozen=True, slots=True)
class EventScopedLocalWatch(_NoEffect):
    watch_id: str
    subject_kind: LocalWatchSubjectKind
    subject_id: str
    subject_version_digest: str
    event_purpose: str
    owner_identity_digest: str
    governing_policy_digests: tuple[str, ...]
    privacy_classification: LocalWatchPrivacyClass
    privacy_policy_digest: str
    created_at: str

    def __post_init__(self) -> None:
        _uuid(self.watch_id, "watch_id")
        object.__setattr__(
            self,
            "subject_kind",
            _enum(LocalWatchSubjectKind, self.subject_kind, "subject_kind"),
        )
        _token(self.subject_id, "subject_id")
        _digest(self.subject_version_digest, "subject_version_digest")
        _text(self.event_purpose, "event_purpose")
        _digest(self.owner_identity_digest, "owner_identity_digest")
        object.__setattr__(
            self,
            "governing_policy_digests",
            _strings(
                self.governing_policy_digests,
                "governing_policy_digests",
                required=True,
                digests=True,
            ),
        )
        object.__setattr__(
            self,
            "privacy_classification",
            _enum(
                LocalWatchPrivacyClass,
                self.privacy_classification,
                "privacy_classification",
            ),
        )
        _digest(self.privacy_policy_digest, "privacy_policy_digest")
        _timestamp(self.created_at, "created_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": EVENT_SCOPED_LOCAL_WATCH,
            **_record_dict(
                self,
                tuple(field for field in _WATCH_FIELDS if field != "schema_version"),
            ),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, EVENT_SCOPED_LOCAL_WATCH, _WATCH_FIELDS)
        value.pop("schema_version")
        value["governing_policy_digests"] = tuple(value["governing_policy_digests"])
        return cls(**value)  # type: ignore[arg-type]


_VERSION_FIELDS = (
    "schema_version",
    "watch_version_id",
    "watch_id",
    "version_ordinal",
    "previous_version_digest",
    "watch_digest",
    "status",
    "locality_reference_digests",
    "service_boundary_digests",
    "source_bindings",
    "permitted_transition_kinds",
    "gross_budget",
    "rights_basis_digests",
    "operational_profile_digest",
    "starts_at",
    "review_at",
    "expires_at",
    "closure_conditions",
    "conversion_conditions",
    "change_reason",
    "actor_identity_digest",
    "recorded_at",
)


@dataclass(frozen=True, slots=True)
class LocalWatchVersion(_NoEffect):
    watch_version_id: str
    watch_id: str
    version_ordinal: int
    previous_version_digest: str | None
    watch_digest: str
    status: LocalWatchVersionStatus
    locality_reference_digests: tuple[str, ...]
    service_boundary_digests: tuple[str, ...]
    source_bindings: tuple[LocalWatchSourceBinding, ...]
    permitted_transition_kinds: tuple[LocalWatchTransitionKind, ...]
    gross_budget: LocalWatchGrossBudget
    rights_basis_digests: tuple[str, ...]
    operational_profile_digest: str
    starts_at: str
    review_at: str
    expires_at: str
    closure_conditions: tuple[LocalWatchClosureCondition, ...]
    conversion_conditions: tuple[LocalWatchConversionCondition, ...]
    change_reason: str
    actor_identity_digest: str
    recorded_at: str

    def __post_init__(self) -> None:
        _uuid(self.watch_version_id, "watch_version_id")
        _uuid(self.watch_id, "watch_id")
        if (
            type(self.version_ordinal) is not int
            or not 1 <= self.version_ordinal <= 10_000
        ):
            raise LocalWatchContractError("version_ordinal must be a bounded integer")
        if self.version_ordinal == 1:
            if self.previous_version_digest is not None:
                raise LocalWatchContractError("first version cannot have a predecessor")
        elif self.previous_version_digest is None:
            raise LocalWatchContractError("later version requires a predecessor")
        if self.previous_version_digest is not None:
            _digest(self.previous_version_digest, "previous_version_digest")
        _digest(self.watch_digest, "watch_digest")
        object.__setattr__(
            self, "status", _enum(LocalWatchVersionStatus, self.status, "status")
        )
        locality = _strings(
            self.locality_reference_digests,
            "locality_reference_digests",
            digests=True,
        )
        service = _strings(
            self.service_boundary_digests,
            "service_boundary_digests",
            digests=True,
        )
        if not locality and not service:
            raise LocalWatchContractError(
                "one exact locality or service boundary is required"
            )
        object.__setattr__(self, "locality_reference_digests", locality)
        object.__setattr__(self, "service_boundary_digests", service)
        if (
            type(self.source_bindings) not in (tuple, list)
            or not self.source_bindings
            or len(self.source_bindings) > 16
        ):
            raise LocalWatchContractError(
                "source_bindings must be a bounded non-empty array"
            )
        bindings = tuple(
            item
            if type(item) is LocalWatchSourceBinding
            else LocalWatchSourceBinding.from_dict(item)
            for item in self.source_bindings
        )
        keys = tuple(item.source_version_id for item in bindings)
        if tuple(sorted(set(keys))) != keys:
            raise LocalWatchContractError("source_bindings must be unique and sorted")
        allowed_boundaries = set(locality) | set(service)
        if any(item.boundary_digest not in allowed_boundaries for item in bindings):
            raise LocalWatchContractError(
                "source binding boundary is outside exact watch scope"
            )
        object.__setattr__(self, "source_bindings", bindings)
        transitions = _enums(
            LocalWatchTransitionKind,
            self.permitted_transition_kinds,
            "permitted_transition_kinds",
            required=True,
        )
        if LocalWatchTransitionKind.CLOSE not in transitions:
            raise LocalWatchContractError("CLOSE must remain a permitted transition")
        object.__setattr__(self, "permitted_transition_kinds", transitions)
        if type(self.gross_budget) is not LocalWatchGrossBudget:
            object.__setattr__(
                self, "gross_budget", LocalWatchGrossBudget.from_dict(self.gross_budget)
            )
        object.__setattr__(
            self,
            "rights_basis_digests",
            _strings(
                self.rights_basis_digests,
                "rights_basis_digests",
                required=True,
                digests=True,
            ),
        )
        _digest(self.operational_profile_digest, "operational_profile_digest")
        starts = _timestamp(self.starts_at, "starts_at")
        review = _timestamp(self.review_at, "review_at")
        expires = _timestamp(self.expires_at, "expires_at")
        if not _instant(starts) < _instant(review) <= _instant(expires):
            raise LocalWatchContractError(
                "watch chronology must be start < review <= expiry"
            )
        if (
            _instant(expires) - _instant(starts)
        ).total_seconds() > MAX_WATCH_DURATION_SECONDS:
            raise LocalWatchContractError("watch duration exceeds the bounded maximum")
        closure = _enums(
            LocalWatchClosureCondition,
            self.closure_conditions,
            "closure_conditions",
            required=True,
        )
        if LocalWatchClosureCondition.EXPIRY_REACHED not in closure:
            raise LocalWatchContractError("expiry must default to explicit closure")
        object.__setattr__(self, "closure_conditions", closure)
        conversion = _enums(
            LocalWatchConversionCondition,
            self.conversion_conditions,
            "conversion_conditions",
        )
        if conversion and len(conversion) < 2:
            raise LocalWatchContractError("conversion cannot depend on one factor")
        object.__setattr__(self, "conversion_conditions", conversion)
        _text(self.change_reason, "change_reason")
        _digest(self.actor_identity_digest, "actor_identity_digest")
        _timestamp(self.recorded_at, "recorded_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": LOCAL_WATCH_VERSION,
            **_record_dict(
                self,
                tuple(field for field in _VERSION_FIELDS if field != "schema_version"),
            ),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, LOCAL_WATCH_VERSION, _VERSION_FIELDS)
        value.pop("schema_version")
        for field in (
            "locality_reference_digests",
            "service_boundary_digests",
            "source_bindings",
            "permitted_transition_kinds",
            "rights_basis_digests",
            "closure_conditions",
            "conversion_conditions",
        ):
            value[field] = tuple(value[field])
        return cls(**value)  # type: ignore[arg-type]


def validate_local_watch_version_chain(
    watch: EventScopedLocalWatch, versions: tuple[LocalWatchVersion, ...]
) -> tuple[LocalWatchVersion, ...]:
    if type(versions) is not tuple or not versions or len(versions) > 10_000:
        raise LocalWatchContractError("versions must be a bounded non-empty chain")
    for index, version in enumerate(versions):
        if type(version) is not LocalWatchVersion:
            raise LocalWatchContractError("version type differs")
        if (
            version.watch_id != watch.watch_id
            or version.watch_digest != watch.canonical_digest
        ):
            raise LocalWatchContractError("version is not bound to the exact watch")
        if version.version_ordinal != index + 1:
            raise LocalWatchContractError("version ordinal is not contiguous")
        expected = None if index == 0 else versions[index - 1].canonical_digest
        if version.previous_version_digest != expected:
            raise LocalWatchContractError("version predecessor differs")
        if index and _instant(version.recorded_at) <= _instant(
            versions[index - 1].recorded_at
        ):
            raise LocalWatchContractError(
                "version chronology is not strictly increasing"
            )
    if _instant(versions[-1].expires_at) - _instant(versions[0].starts_at) > timedelta(
        seconds=MAX_WATCH_DURATION_SECONDS
    ):
        raise LocalWatchContractError("version chain would make the watch indefinite")
    return versions


_CLOSURE_FIELDS = (
    "schema_version",
    "closure_id",
    "watch_id",
    "watch_version_id",
    "watch_version_digest",
    "outcome",
    "effective_at",
    "reason",
    "evidence_reference_digests",
    "locality_coverage_proposal_digest",
    "actor_identity_digest",
    "recorded_at",
)


@dataclass(frozen=True, slots=True)
class LocalWatchClosure(_NoEffect):
    closure_id: str
    watch_id: str
    watch_version_id: str
    watch_version_digest: str
    outcome: LocalWatchClosureOutcome
    effective_at: str
    reason: str
    evidence_reference_digests: tuple[str, ...]
    locality_coverage_proposal_digest: str | None
    actor_identity_digest: str
    recorded_at: str

    def __post_init__(self) -> None:
        _uuid(self.closure_id, "closure_id")
        _uuid(self.watch_id, "watch_id")
        _uuid(self.watch_version_id, "watch_version_id")
        _digest(self.watch_version_digest, "watch_version_digest")
        object.__setattr__(
            self, "outcome", _enum(LocalWatchClosureOutcome, self.outcome, "outcome")
        )
        _timestamp(self.effective_at, "effective_at")
        _text(self.reason, "reason")
        object.__setattr__(
            self,
            "evidence_reference_digests",
            _strings(
                self.evidence_reference_digests,
                "evidence_reference_digests",
                digests=True,
            ),
        )
        if self.outcome is LocalWatchClosureOutcome.CONVERSION_PROPOSED:
            if self.locality_coverage_proposal_digest is None:
                raise LocalWatchContractError(
                    "conversion closure requires a separate proposal digest"
                )
        elif self.locality_coverage_proposal_digest is not None:
            raise LocalWatchContractError(
                "only conversion closure may reference a locality proposal"
            )
        if self.locality_coverage_proposal_digest is not None:
            _digest(
                self.locality_coverage_proposal_digest,
                "locality_coverage_proposal_digest",
            )
        _digest(self.actor_identity_digest, "actor_identity_digest")
        _timestamp(self.recorded_at, "recorded_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": LOCAL_WATCH_CLOSURE,
            **_record_dict(
                self,
                tuple(field for field in _CLOSURE_FIELDS if field != "schema_version"),
            ),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, LOCAL_WATCH_CLOSURE, _CLOSURE_FIELDS)
        value.pop("schema_version")
        value["evidence_reference_digests"] = tuple(value["evidence_reference_digests"])
        return cls(**value)  # type: ignore[arg-type]


def validate_local_watch_closure(
    watch: EventScopedLocalWatch,
    version: LocalWatchVersion,
    closure: LocalWatchClosure,
) -> LocalWatchClosure:
    if (
        version.watch_id != watch.watch_id
        or version.watch_digest != watch.canonical_digest
    ):
        raise LocalWatchContractError("version is not bound to the exact watch")
    if version.version_ordinal == 1:
        validate_local_watch_version_chain(watch, (version,))
    if (
        closure.watch_id != watch.watch_id
        or closure.watch_version_id != version.watch_version_id
        or closure.watch_version_digest != version.canonical_digest
    ):
        raise LocalWatchContractError("closure is not bound to the exact watch version")
    if _instant(closure.effective_at) < _instant(version.starts_at):
        raise LocalWatchContractError("closure cannot precede watch start")
    if _instant(closure.effective_at) > _instant(version.expires_at):
        raise LocalWatchContractError("closure cannot follow watch expiry")
    if (
        closure.outcome is LocalWatchClosureOutcome.EXPIRED
        and closure.effective_at != version.expires_at
    ):
        raise LocalWatchContractError("expiry closure must use the exact expiry")
    if (
        closure.outcome is LocalWatchClosureOutcome.CONVERSION_PROPOSED
        and not version.conversion_conditions
    ):
        raise LocalWatchContractError(
            "watch version does not permit a conversion proposal"
        )
    return closure


__all__ = [
    "EVENT_SCOPED_LOCAL_WATCH",
    "LOCAL_WATCH_CLOSURE",
    "LOCAL_WATCH_CONVERSION_CONDITION",
    "LOCAL_WATCH_EXPIRY",
    "LOCAL_WATCH_VERSION",
    "MAX_LOCAL_WATCH_BYTES",
    "MAX_WATCH_DURATION_SECONDS",
    "NO_PERMANENT_LOCALITY_INFERENCE",
    "EventScopedLocalWatch",
    "LocalWatchClosure",
    "LocalWatchClosureCondition",
    "LocalWatchClosureOutcome",
    "LocalWatchContractError",
    "LocalWatchConversionCondition",
    "LocalWatchGrossBudget",
    "LocalWatchPrivacyClass",
    "LocalWatchSourceBinding",
    "LocalWatchSourceRole",
    "LocalWatchSubjectKind",
    "LocalWatchTransitionKind",
    "LocalWatchVersion",
    "LocalWatchVersionStatus",
    "validate_local_watch_closure",
    "validate_local_watch_version_chain",
]
