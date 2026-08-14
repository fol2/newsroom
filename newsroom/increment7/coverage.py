"""Prospective and retrospective Coverage Audit/Gap contracts."""

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

COVERAGE_COMPARATOR = "newsroom.increment7.coverage-comparator.v1"
COVERAGE_AUDIT = "newsroom.increment7.coverage-audit.v1"
COVERAGE_GAP = "newsroom.increment7.coverage-gap.v1"
COVERAGE_GAP_DECISION = "newsroom.increment7.coverage-gap-decision.v1"
COVERAGE_PROSPECTIVE_RETROSPECTIVE_BOUNDARY = "PRE_REGISTERED_VS_LABELLED_HINDSIGHT"
COVERAGE_LIMITATION_AUTHORITY = "BEST_EFFORT_EXPLICIT_OR_DEFERRED"
MAX_COVERAGE_BYTES = 1_048_576

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_UTC = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)


class CoverageContractError(ValueError):
    """Untrusted comparator, audit or Gap values failed closed."""


class CoverageAuditMode(StrEnum):
    PROSPECTIVE_PRE_REGISTERED = "PROSPECTIVE_PRE_REGISTERED"
    RETROSPECTIVE_INVESTIGATION = "RETROSPECTIVE_INVESTIGATION"


class CoverageBasisKind(StrEnum):
    PLANNED_AGENDA = "PLANNED_AGENDA"
    EXPECTED_SOURCE_CLASS = "EXPECTED_SOURCE_CLASS"
    OWNER_APPROVED_BENCHMARK = "OWNER_APPROVED_BENCHMARK"


class CoverageObservationKind(StrEnum):
    SEARCH_RESULT_REFERENCE = "SEARCH_RESULT_REFERENCE"
    EDITORIAL_RECORD = "EDITORIAL_RECORD"
    SOURCE_CHECK = "SOURCE_CHECK"
    EXPECTATION_NOT_OBSERVED = "EXPECTATION_NOT_OBSERVED"


class CoverageAssessmentState(StrEnum):
    COMPLETE_BEST_EFFORT = "COMPLETE_BEST_EFFORT"
    PARTIAL_LIMITED = "PARTIAL_LIMITED"
    DEFERRED = "DEFERRED"


class CoverageGapScope(StrEnum):
    ISOLATED = "ISOLATED"
    SYSTEMIC = "SYSTEMIC"
    UNDETERMINED = "UNDETERMINED"


class CoverageGapState(StrEnum):
    PROPOSED = "PROPOSED"
    DEFERRED_ASSESSMENT = "DEFERRED_ASSESSMENT"


class CoverageGapDisposition(StrEnum):
    CONFIRMED_BEST_EFFORT_GAP = "CONFIRMED_BEST_EFFORT_GAP"
    NOT_CONFIRMED = "NOT_CONFIRMED"
    DEFERRED_INSUFFICIENT_BASIS = "DEFERRED_INSUFFICIENT_BASIS"


class _NoEffect:
    authorises_external_effect = False
    authorises_search = False
    authorises_provider = False
    authorises_credentials = False
    authorises_egress = False
    authorises_spend = False
    authorises_schedule = False
    authorises_evidence = False
    authorises_locality = False
    authorises_source_portfolio = False
    authorises_publication = False
    comparator_is_ground_truth = False
    gap_is_automatic_truth = False
    hindsight_promoted_to_prospective = False
    creates_signal = False
    creates_lead = False
    creates_candidate = False
    creates_watch = False
    production_activation_authorised = False


def _text(value: object, field: str, maximum: int = 2_048) -> str:
    try:
        size = len(value.encode()) if type(value) is str else 0
    except UnicodeError as exc:
        raise CoverageContractError(f"{field} must be canonical text") from exc
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or size > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise CoverageContractError(f"{field} must be canonical text")
    return value


def _token(value: object, field: str) -> str:
    value = _text(value, field, 256)
    if _TOKEN.fullmatch(value) is None:
        raise CoverageContractError(f"{field} must be a canonical token")
    return value


def _uuid(value: object, field: str) -> str:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        raise CoverageContractError(f"{field} must be a canonical UUID")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError as exc:
        raise CoverageContractError(f"{field} must be a canonical UUID") from exc
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise CoverageContractError(f"{field} must be a SHA-256 digest") from exc


def _timestamp(value: object, field: str) -> str:
    value = _text(value, field, 27)
    if _UTC.fullmatch(value) is None:
        raise CoverageContractError(f"{field} must be an exact UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise CoverageContractError(f"{field} must be an exact UTC timestamp") from exc
    return value


def _enum[T: StrEnum](kind: type[T], value: object, field: str) -> T:
    if type(value) is not str and type(value) is not kind:
        raise CoverageContractError(f"{field} differs")
    try:
        return kind(value)
    except ValueError as exc:
        raise CoverageContractError(f"{field} differs") from exc


def _strings(
    value: object, field: str, *, required: bool = False, digests: bool = False
) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > 64 or (required and not value):
        raise CoverageContractError(f"{field} must be a bounded array")
    validator = _digest if digests else _token
    result = tuple(validator(item, field) for item in value)
    if tuple(sorted(set(result))) != result:
        raise CoverageContractError(f"{field} must be unique and sorted")
    return result


def _array(value: object, field: str) -> list[object]:
    if type(value) is not list:
        raise CoverageContractError(f"{field} must be a bounded array")
    return value


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CoverageContractError(f"duplicate object name: {key}")
        result[key] = value
    return result


def _document(raw: bytes, schema: str, fields: tuple[str, ...]) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_COVERAGE_BYTES:
        raise CoverageContractError("Coverage bytes are not bounded")
    try:
        value = json.loads(raw.decode(), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except CoverageContractError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
        RecursionError,
        ValueError,
    ) as exc:
        raise CoverageContractError("Coverage bytes are not canonical JSON") from exc
    if type(value) is not dict or raw != canonical:
        raise CoverageContractError("Coverage bytes are not exact canonical JSON")
    if tuple(value) != tuple(sorted(fields)) or value.get("schema_version") != schema:
        raise CoverageContractError("Coverage fields or schema differ")
    return value


def _record_dict(record: object, fields: tuple[str, ...]) -> dict[str, object]:
    result: dict[str, object] = {}
    for field in fields:
        value = getattr(record, field)
        if isinstance(value, StrEnum):
            value = value.value
        elif isinstance(value, tuple):
            value = [
                item.to_dict() if hasattr(item, "to_dict") else item for item in value
            ]
        result[field] = value
    return result


_OBSERVATION_FIELDS = ("kind", "observed_at", "reference_digest")


@dataclass(frozen=True, slots=True)
class CoverageObservation(_NoEffect):
    kind: CoverageObservationKind
    reference_digest: str
    observed_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _enum(CoverageObservationKind, self.kind, "kind")
        )
        _digest(self.reference_digest, "reference_digest")
        _timestamp(self.observed_at, "observed_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "observed_at": self.observed_at,
            "reference_digest": self.reference_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict or tuple(value) != _OBSERVATION_FIELDS:
            raise CoverageContractError("Coverage Observation fields differ")
        return cls(**value)  # type: ignore[arg-type]


_COMPARATOR_FIELDS = (
    "schema_version",
    "comparator_id",
    "audit_mode",
    "coverage_basis_kind",
    "subject_key",
    "expectation_reference_digests",
    "coverage_unit_digests",
    "source_class_scope",
    "search_request_digests",
    "window_start",
    "window_end",
    "retrospective_trigger_digest",
    "governing_policy_digests",
    "registered_at",
)


@dataclass(frozen=True, slots=True)
class CoverageComparator(_NoEffect):
    comparator_id: str
    audit_mode: CoverageAuditMode
    coverage_basis_kind: CoverageBasisKind
    subject_key: str
    expectation_reference_digests: tuple[str, ...]
    coverage_unit_digests: tuple[str, ...]
    source_class_scope: tuple[str, ...]
    search_request_digests: tuple[str, ...]
    window_start: str
    window_end: str
    retrospective_trigger_digest: str | None
    governing_policy_digests: tuple[str, ...]
    registered_at: str
    schema_version: str = COVERAGE_COMPARATOR

    def __post_init__(self) -> None:
        if self.schema_version != COVERAGE_COMPARATOR:
            raise CoverageContractError("Coverage Comparator schema differs")
        _uuid(self.comparator_id, "comparator_id")
        object.__setattr__(
            self,
            "audit_mode",
            _enum(CoverageAuditMode, self.audit_mode, "audit_mode"),
        )
        object.__setattr__(
            self,
            "coverage_basis_kind",
            _enum(CoverageBasisKind, self.coverage_basis_kind, "coverage_basis_kind"),
        )
        _token(self.subject_key, "subject_key")
        for field in (
            "expectation_reference_digests",
            "coverage_unit_digests",
            "search_request_digests",
            "governing_policy_digests",
        ):
            object.__setattr__(
                self,
                field,
                _strings(getattr(self, field), field, required=True, digests=True),
            )
        object.__setattr__(
            self,
            "source_class_scope",
            _strings(self.source_class_scope, "source_class_scope", required=True),
        )
        _timestamp(self.window_start, "window_start")
        _timestamp(self.window_end, "window_end")
        _timestamp(self.registered_at, "registered_at")
        if self.window_end <= self.window_start:
            raise CoverageContractError("Comparator window must be ordered")
        prospective = self.audit_mode is CoverageAuditMode.PROSPECTIVE_PRE_REGISTERED
        if prospective:
            if (
                self.registered_at > self.window_start
                or self.retrospective_trigger_digest is not None
            ):
                raise CoverageContractError(
                    "prospective Comparator was not pre-registered"
                )
        elif self.retrospective_trigger_digest is None:
            raise CoverageContractError(
                "retrospective Comparator lacks investigation trigger"
            )
        else:
            _digest(self.retrospective_trigger_digest, "retrospective_trigger_digest")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(_record_dict(self, _COMPARATOR_FIELDS))

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, COVERAGE_COMPARATOR, _COMPARATOR_FIELDS)
        for field in (
            "expectation_reference_digests",
            "coverage_unit_digests",
            "source_class_scope",
            "search_request_digests",
            "governing_policy_digests",
        ):
            value[field] = tuple(_array(value[field], field))
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise CoverageContractError("Coverage Comparator replay differs")
        return result


_AUDIT_FIELDS = (
    "schema_version",
    "audit_id",
    "comparator_id",
    "comparator_digest",
    "audit_mode",
    "observations",
    "assessment_state",
    "limitation_codes",
    "auditor_identity_digest",
    "completed_at",
)


@dataclass(frozen=True, slots=True)
class CoverageAudit(_NoEffect):
    audit_id: str
    comparator_id: str
    comparator_digest: str
    audit_mode: CoverageAuditMode
    observations: tuple[CoverageObservation, ...]
    assessment_state: CoverageAssessmentState
    limitation_codes: tuple[str, ...]
    auditor_identity_digest: str
    completed_at: str
    schema_version: str = COVERAGE_AUDIT

    def __post_init__(self) -> None:
        if self.schema_version != COVERAGE_AUDIT:
            raise CoverageContractError("Coverage Audit schema differs")
        _uuid(self.audit_id, "audit_id")
        _uuid(self.comparator_id, "comparator_id")
        _digest(self.comparator_digest, "comparator_digest")
        object.__setattr__(
            self,
            "audit_mode",
            _enum(CoverageAuditMode, self.audit_mode, "audit_mode"),
        )
        if (
            type(self.observations) is not tuple
            or not self.observations
            or len(self.observations) > 256
        ):
            raise CoverageContractError("Coverage observations must be bounded")
        observations = tuple(
            item
            if type(item) is CoverageObservation
            else CoverageObservation.from_dict(item)
            for item in self.observations
        )
        if (
            tuple(
                sorted(
                    observations,
                    key=lambda item: (item.observed_at, item.reference_digest),
                )
            )
            != observations
        ):
            raise CoverageContractError(
                "Coverage observations must be deterministically ordered"
            )
        if len({(item.kind, item.reference_digest) for item in observations}) != len(
            observations
        ):
            raise CoverageContractError("Coverage observations must be unique")
        object.__setattr__(self, "observations", observations)
        object.__setattr__(
            self,
            "assessment_state",
            _enum(CoverageAssessmentState, self.assessment_state, "assessment_state"),
        )
        object.__setattr__(
            self,
            "limitation_codes",
            _strings(self.limitation_codes, "limitation_codes", required=True),
        )
        _digest(self.auditor_identity_digest, "auditor_identity_digest")
        _timestamp(self.completed_at, "completed_at")
        if any(item.observed_at > self.completed_at for item in observations):
            raise CoverageContractError("Coverage observation occurs after completion")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(_record_dict(self, _AUDIT_FIELDS))

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, COVERAGE_AUDIT, _AUDIT_FIELDS)
        value["observations"] = tuple(
            CoverageObservation.from_dict(item)
            for item in _array(value["observations"], "observations")
        )
        value["limitation_codes"] = tuple(
            _array(value["limitation_codes"], "limitation_codes")
        )
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise CoverageContractError("Coverage Audit replay differs")
        return result


_GAP_FIELDS = (
    "schema_version",
    "gap_id",
    "audit_id",
    "audit_digest",
    "gap_scope",
    "gap_state",
    "affected_coverage_unit_digests",
    "missing_expectation_digests",
    "repetition_evidence_digests",
    "limitation_codes",
    "proposed_at",
)


@dataclass(frozen=True, slots=True)
class CoverageGap(_NoEffect):
    gap_id: str
    audit_id: str
    audit_digest: str
    gap_scope: CoverageGapScope
    gap_state: CoverageGapState
    affected_coverage_unit_digests: tuple[str, ...]
    missing_expectation_digests: tuple[str, ...]
    repetition_evidence_digests: tuple[str, ...]
    limitation_codes: tuple[str, ...]
    proposed_at: str
    schema_version: str = COVERAGE_GAP

    def __post_init__(self) -> None:
        if self.schema_version != COVERAGE_GAP:
            raise CoverageContractError("Coverage Gap schema differs")
        _uuid(self.gap_id, "gap_id")
        _uuid(self.audit_id, "audit_id")
        _digest(self.audit_digest, "audit_digest")
        object.__setattr__(
            self, "gap_scope", _enum(CoverageGapScope, self.gap_scope, "gap_scope")
        )
        object.__setattr__(
            self, "gap_state", _enum(CoverageGapState, self.gap_state, "gap_state")
        )
        for field in (
            "affected_coverage_unit_digests",
            "missing_expectation_digests",
            "repetition_evidence_digests",
        ):
            object.__setattr__(
                self,
                field,
                _strings(
                    getattr(self, field),
                    field,
                    required=field != "repetition_evidence_digests",
                    digests=True,
                ),
            )
        object.__setattr__(
            self,
            "limitation_codes",
            _strings(self.limitation_codes, "limitation_codes", required=True),
        )
        _timestamp(self.proposed_at, "proposed_at")
        if (
            self.gap_scope is CoverageGapScope.ISOLATED
            and len(self.affected_coverage_unit_digests) != 1
        ):
            raise CoverageContractError("isolated Gap must bind one coverage unit")
        if self.gap_scope is CoverageGapScope.SYSTEMIC and (
            len(self.affected_coverage_unit_digests) < 2
            or not self.repetition_evidence_digests
        ):
            raise CoverageContractError("systemic Gap lacks repeated coverage evidence")
        deferred = self.gap_state is CoverageGapState.DEFERRED_ASSESSMENT
        if deferred != (self.gap_scope is CoverageGapScope.UNDETERMINED):
            raise CoverageContractError("deferred Gap scope differs")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(_record_dict(self, _GAP_FIELDS))

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, COVERAGE_GAP, _GAP_FIELDS)
        for field in (
            "affected_coverage_unit_digests",
            "missing_expectation_digests",
            "repetition_evidence_digests",
            "limitation_codes",
        ):
            value[field] = tuple(_array(value[field], field))
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise CoverageContractError("Coverage Gap replay differs")
        return result


_DECISION_FIELDS = (
    "schema_version",
    "decision_id",
    "gap_id",
    "gap_digest",
    "disposition",
    "review_evidence_digests",
    "acknowledged_limitation_codes",
    "reviewer_identity_digest",
    "reason_codes",
    "supersedes_decision_digest",
    "decided_at",
)


@dataclass(frozen=True, slots=True)
class CoverageGapDecision(_NoEffect):
    decision_id: str
    gap_id: str
    gap_digest: str
    disposition: CoverageGapDisposition
    review_evidence_digests: tuple[str, ...]
    acknowledged_limitation_codes: tuple[str, ...]
    reviewer_identity_digest: str
    reason_codes: tuple[str, ...]
    supersedes_decision_digest: str | None
    decided_at: str
    schema_version: str = COVERAGE_GAP_DECISION

    def __post_init__(self) -> None:
        if self.schema_version != COVERAGE_GAP_DECISION:
            raise CoverageContractError("Coverage Gap Decision schema differs")
        _uuid(self.decision_id, "decision_id")
        _uuid(self.gap_id, "gap_id")
        _digest(self.gap_digest, "gap_digest")
        object.__setattr__(
            self,
            "disposition",
            _enum(CoverageGapDisposition, self.disposition, "disposition"),
        )
        object.__setattr__(
            self,
            "review_evidence_digests",
            _strings(
                self.review_evidence_digests,
                "review_evidence_digests",
                required=True,
                digests=True,
            ),
        )
        for field in ("acknowledged_limitation_codes", "reason_codes"):
            object.__setattr__(
                self, field, _strings(getattr(self, field), field, required=True)
            )
        _digest(self.reviewer_identity_digest, "reviewer_identity_digest")
        if self.supersedes_decision_digest is not None:
            _digest(self.supersedes_decision_digest, "supersedes_decision_digest")
        _timestamp(self.decided_at, "decided_at")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(_record_dict(self, _DECISION_FIELDS))

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, COVERAGE_GAP_DECISION, _DECISION_FIELDS)
        for field in (
            "review_evidence_digests",
            "acknowledged_limitation_codes",
            "reason_codes",
        ):
            value[field] = tuple(_array(value[field], field))
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise CoverageContractError("Coverage Gap Decision replay differs")
        return result


def validate_coverage_chain(
    comparator: CoverageComparator,
    audit: CoverageAudit,
    gap: CoverageGap,
    decision: CoverageGapDecision,
    previous_decision: CoverageGapDecision | None = None,
) -> None:
    if any(
        type(value) is not kind
        for value, kind in (
            (comparator, CoverageComparator),
            (audit, CoverageAudit),
            (gap, CoverageGap),
            (decision, CoverageGapDecision),
        )
    ):
        raise CoverageContractError("Coverage chain requires exact records")
    observation_digests = {item.reference_digest for item in audit.observations}
    unobserved_expectations = {
        item.reference_digest
        for item in audit.observations
        if item.kind is CoverageObservationKind.EXPECTATION_NOT_OBSERVED
    }
    if (
        audit.comparator_id != comparator.comparator_id
        or audit.comparator_digest != comparator.digest
        or audit.audit_mode is not comparator.audit_mode
        or audit.completed_at < comparator.window_end
        or gap.audit_id != audit.audit_id
        or gap.audit_digest != audit.digest
        or gap.proposed_at < audit.completed_at
        or not set(gap.affected_coverage_unit_digests).issubset(
            comparator.coverage_unit_digests
        )
        or not set(gap.missing_expectation_digests).issubset(
            comparator.expectation_reference_digests
        )
        or not set(gap.missing_expectation_digests).issubset(
            unobserved_expectations
        )
        or not set(gap.limitation_codes).issuperset(audit.limitation_codes)
        or decision.gap_id != gap.gap_id
        or decision.gap_digest != gap.digest
        or decision.decided_at < gap.proposed_at
        or not set(gap.limitation_codes).issubset(
            decision.acknowledged_limitation_codes
        )
        or not set(decision.review_evidence_digests).issubset(observation_digests)
    ):
        raise CoverageContractError("Coverage chain lineage or review basis differs")
    deferred = audit.assessment_state is CoverageAssessmentState.DEFERRED
    if deferred != (gap.gap_state is CoverageGapState.DEFERRED_ASSESSMENT):
        raise CoverageContractError("deferred Coverage assessment differs")
    if (
        gap.gap_state is CoverageGapState.DEFERRED_ASSESSMENT
        and decision.disposition
        is not CoverageGapDisposition.DEFERRED_INSUFFICIENT_BASIS
    ):
        raise CoverageContractError("deferred Gap received a conclusive disposition")
    if (
        gap.gap_state is not CoverageGapState.DEFERRED_ASSESSMENT
        and decision.disposition
        is CoverageGapDisposition.DEFERRED_INSUFFICIENT_BASIS
    ):
        raise CoverageContractError("non-deferred Gap received a deferred disposition")
    if previous_decision is None:
        if decision.supersedes_decision_digest is not None:
            raise CoverageContractError("initial Gap Decision supersedes another")
    elif (
        type(previous_decision) is not CoverageGapDecision
        or previous_decision.gap_id != gap.gap_id
        or previous_decision.gap_digest != gap.digest
        or decision.decision_id == previous_decision.decision_id
        or decision.supersedes_decision_digest != previous_decision.digest
        or decision.decided_at < previous_decision.decided_at
    ):
        raise CoverageContractError("Gap Decision predecessor differs")


__all__ = [
    "COVERAGE_AUDIT",
    "COVERAGE_COMPARATOR",
    "COVERAGE_GAP",
    "COVERAGE_GAP_DECISION",
    "COVERAGE_LIMITATION_AUTHORITY",
    "COVERAGE_PROSPECTIVE_RETROSPECTIVE_BOUNDARY",
    "CoverageAssessmentState",
    "CoverageAudit",
    "CoverageAuditMode",
    "CoverageBasisKind",
    "CoverageComparator",
    "CoverageContractError",
    "CoverageGap",
    "CoverageGapDecision",
    "CoverageGapDisposition",
    "CoverageGapScope",
    "CoverageGapState",
    "CoverageObservation",
    "CoverageObservationKind",
    "validate_coverage_chain",
]
