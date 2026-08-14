"""Immutable, non-activating locality coverage qualification seams."""

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

LOCALITY_REFERENCE = "newsroom.increment7.locality-reference.v1"
LOCALITY_COVERAGE_UNIT = "newsroom.increment7.locality-coverage-unit.v1"
LOCALITY_COVERAGE_PROPOSAL = "newsroom.increment7.locality-coverage-proposal.v1"
LOCALITY_COVERAGE_DECISION = "newsroom.increment7.locality-coverage-decision.v1"
LOCALITY_COMPLETENESS = "BEST_EFFORT_EXPLICIT_GAPS_NO_COMPLETENESS_CLAIM"
LOCALITY_ACTIVATION = "DECISION_RECORD_ONLY_NO_SELECTION_OR_ENABLEMENT"
MAX_LOCALITY_BYTES = 1_048_576

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_UTC = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)


class LocalityQualificationError(ValueError):
    """A locality seam failed its exact immutable contract."""


class LocalityKind(StrEnum):
    ADMINISTRATIVE_AREA = "ADMINISTRATIVE_AREA"
    EDITORIAL_REGION = "EDITORIAL_REGION"
    SERVICE_AREA = "SERVICE_AREA"
    OTHER_VERSIONED_BOUNDARY = "OTHER_VERSIONED_BOUNDARY"


class LocalityServiceBoundary(StrEnum):
    CIVIC_AND_PUBLIC_BODIES = "CIVIC_AND_PUBLIC_BODIES"
    EMERGENCY_AND_SAFETY = "EMERGENCY_AND_SAFETY"
    HEALTH_AND_SOCIAL_CARE = "HEALTH_AND_SOCIAL_CARE"
    TRANSPORT_AND_INFRASTRUCTURE = "TRANSPORT_AND_INFRASTRUCTURE"
    GENERAL_LOCAL_NEWS_RESEARCH = "GENERAL_LOCAL_NEWS_RESEARCH"


class LocalityCompletenessClass(StrEnum):
    BEST_EFFORT_WITH_EXPLICIT_GAPS = "BEST_EFFORT_WITH_EXPLICIT_GAPS"


class LocalityProposalPosture(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"


class LocalityDecisionOutcome(StrEnum):
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"
    RETAIN_RESEARCH_ONLY = "RETAIN_RESEARCH_ONLY"


class _NoEffect:
    authorises_external_effect = False
    authorises_locality = False
    authorises_source_portfolio = False
    authorises_provider = False
    authorises_credentials = False
    authorises_egress = False
    authorises_spend = False
    authorises_schedule = False
    authorises_search = False
    authorises_evidence = False
    authorises_publication = False
    claims_completeness = False
    creates_signal = False
    creates_lead = False
    creates_candidate = False
    creates_watch = False
    permanent_locality_selected = False
    production_activation_authorised = False


def _text(value: object, field: str, maximum: int = 2_048) -> str:
    try:
        size = len(value.encode()) if type(value) is str else 0
    except UnicodeError as exc:
        raise LocalityQualificationError(f"{field} must be canonical text") from exc
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or size > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise LocalityQualificationError(f"{field} must be canonical text")
    return value


def _token(value: object, field: str) -> str:
    value = _text(value, field, 256)
    if _TOKEN.fullmatch(value) is None:
        raise LocalityQualificationError(f"{field} must be a canonical token")
    return value


def _uuid(value: object, field: str) -> str:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        raise LocalityQualificationError(f"{field} must be a canonical UUID")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError as exc:
        raise LocalityQualificationError(f"{field} must be a canonical UUID") from exc
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise LocalityQualificationError(f"{field} must be a SHA-256 digest") from exc


def _timestamp(value: object, field: str) -> str:
    value = _text(value, field, 27)
    if _UTC.fullmatch(value) is None:
        raise LocalityQualificationError(f"{field} must be an exact UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise LocalityQualificationError(
            f"{field} must be an exact UTC timestamp"
        ) from exc
    return value


def _enum[T: StrEnum](kind: type[T], value: object, field: str) -> T:
    if type(value) is not str and type(value) is not kind:
        raise LocalityQualificationError(f"{field} differs")
    try:
        return kind(value)
    except ValueError as exc:
        raise LocalityQualificationError(f"{field} differs") from exc


def _strings(
    value: object,
    field: str,
    *,
    required: bool = False,
    digests: bool = False,
) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > 64 or (required and not value):
        raise LocalityQualificationError(f"{field} must be a bounded array")
    validator = _digest if digests else _token
    result = tuple(validator(item, field) for item in value)
    if tuple(sorted(set(result))) != result:
        raise LocalityQualificationError(f"{field} must be unique and sorted")
    return result


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LocalityQualificationError(f"duplicate object name: {key}")
        result[key] = value
    return result


def _document(raw: bytes, schema: str, fields: tuple[str, ...]) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_LOCALITY_BYTES:
        raise LocalityQualificationError("locality bytes are not bounded")
    try:
        value = json.loads(raw.decode(), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except LocalityQualificationError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
        RecursionError,
        ValueError,
    ) as exc:
        raise LocalityQualificationError(
            "locality bytes are not canonical JSON"
        ) from exc
    if type(value) is not dict or raw != canonical:
        raise LocalityQualificationError("locality bytes are not exact canonical JSON")
    if tuple(value) != tuple(sorted(fields)) or value.get("schema_version") != schema:
        raise LocalityQualificationError("locality fields or schema differ")
    return value


def _record_dict(record: object, fields: tuple[str, ...]) -> dict[str, object]:
    result: dict[str, object] = {}
    for field in fields:
        value = getattr(record, field)
        if isinstance(value, StrEnum):
            value = value.value
        elif isinstance(value, tuple):
            value = list(value)
        result[field] = value
    return result


_REFERENCE_FIELDS = (
    "schema_version",
    "locality_reference_id",
    "locality_kind",
    "canonical_code",
    "display_label",
    "boundary_definition_version",
    "boundary_digest",
    "provenance_digests",
    "recorded_at",
)


@dataclass(frozen=True, slots=True)
class LocalityReference(_NoEffect):
    locality_reference_id: str
    locality_kind: LocalityKind
    canonical_code: str
    display_label: str
    boundary_definition_version: str
    boundary_digest: str
    provenance_digests: tuple[str, ...]
    recorded_at: str
    schema_version: str = LOCALITY_REFERENCE

    def __post_init__(self) -> None:
        if self.schema_version != LOCALITY_REFERENCE:
            raise LocalityQualificationError("Locality Reference schema differs")
        _uuid(self.locality_reference_id, "locality_reference_id")
        object.__setattr__(
            self,
            "locality_kind",
            _enum(LocalityKind, self.locality_kind, "locality_kind"),
        )
        _token(self.canonical_code, "canonical_code")
        _text(self.display_label, "display_label", 512)
        _token(self.boundary_definition_version, "boundary_definition_version")
        _digest(self.boundary_digest, "boundary_digest")
        object.__setattr__(
            self,
            "provenance_digests",
            _strings(
                self.provenance_digests,
                "provenance_digests",
                required=True,
                digests=True,
            ),
        )
        _timestamp(self.recorded_at, "recorded_at")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(_record_dict(self, _REFERENCE_FIELDS))

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, LOCALITY_REFERENCE, _REFERENCE_FIELDS)
        value["provenance_digests"] = tuple(value["provenance_digests"])  # type: ignore[arg-type]
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise LocalityQualificationError("Locality Reference replay differs")
        return result


_UNIT_FIELDS = (
    "schema_version",
    "coverage_unit_id",
    "locality_reference_id",
    "locality_reference_digest",
    "service_boundary",
    "source_class_scope",
    "explicit_exclusions",
    "known_gap_codes",
    "completeness_class",
    "rights_basis_digest",
    "operational_profile_digest",
    "recorded_at",
)


@dataclass(frozen=True, slots=True)
class LocalityCoverageUnit(_NoEffect):
    coverage_unit_id: str
    locality_reference_id: str
    locality_reference_digest: str
    service_boundary: LocalityServiceBoundary
    source_class_scope: tuple[str, ...]
    explicit_exclusions: tuple[str, ...]
    known_gap_codes: tuple[str, ...]
    completeness_class: LocalityCompletenessClass
    rights_basis_digest: str
    operational_profile_digest: str
    recorded_at: str
    schema_version: str = LOCALITY_COVERAGE_UNIT

    def __post_init__(self) -> None:
        if self.schema_version != LOCALITY_COVERAGE_UNIT:
            raise LocalityQualificationError("Locality Coverage Unit schema differs")
        _uuid(self.coverage_unit_id, "coverage_unit_id")
        _uuid(self.locality_reference_id, "locality_reference_id")
        _digest(self.locality_reference_digest, "locality_reference_digest")
        object.__setattr__(
            self,
            "service_boundary",
            _enum(LocalityServiceBoundary, self.service_boundary, "service_boundary"),
        )
        for field, required in (
            ("source_class_scope", True),
            ("explicit_exclusions", False),
            ("known_gap_codes", True),
        ):
            object.__setattr__(
                self, field, _strings(getattr(self, field), field, required=required)
            )
        object.__setattr__(
            self,
            "completeness_class",
            _enum(
                LocalityCompletenessClass,
                self.completeness_class,
                "completeness_class",
            ),
        )
        _digest(self.rights_basis_digest, "rights_basis_digest")
        _digest(self.operational_profile_digest, "operational_profile_digest")
        _timestamp(self.recorded_at, "recorded_at")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(_record_dict(self, _UNIT_FIELDS))

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, LOCALITY_COVERAGE_UNIT, _UNIT_FIELDS)
        for field in ("source_class_scope", "explicit_exclusions", "known_gap_codes"):
            value[field] = tuple(value[field])  # type: ignore[arg-type]
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise LocalityQualificationError("Locality Coverage Unit replay differs")
        return result


_PROPOSAL_FIELDS = (
    "schema_version",
    "proposal_id",
    "coverage_unit_id",
    "coverage_unit_digest",
    "posture",
    "provider_decision_digests",
    "proposed_source_reference_digests",
    "unresolved_gap_codes",
    "owner_identity_digest",
    "proposed_at",
)


@dataclass(frozen=True, slots=True)
class LocalityCoverageProposal(_NoEffect):
    proposal_id: str
    coverage_unit_id: str
    coverage_unit_digest: str
    posture: LocalityProposalPosture
    provider_decision_digests: tuple[str, ...]
    proposed_source_reference_digests: tuple[str, ...]
    unresolved_gap_codes: tuple[str, ...]
    owner_identity_digest: str
    proposed_at: str
    schema_version: str = LOCALITY_COVERAGE_PROPOSAL

    def __post_init__(self) -> None:
        if self.schema_version != LOCALITY_COVERAGE_PROPOSAL:
            raise LocalityQualificationError(
                "Locality Coverage Proposal schema differs"
            )
        _uuid(self.proposal_id, "proposal_id")
        _uuid(self.coverage_unit_id, "coverage_unit_id")
        _digest(self.coverage_unit_digest, "coverage_unit_digest")
        object.__setattr__(
            self,
            "posture",
            _enum(LocalityProposalPosture, self.posture, "posture"),
        )
        object.__setattr__(
            self,
            "provider_decision_digests",
            _strings(
                self.provider_decision_digests,
                "provider_decision_digests",
                required=True,
                digests=True,
            ),
        )
        object.__setattr__(
            self,
            "proposed_source_reference_digests",
            _strings(
                self.proposed_source_reference_digests,
                "proposed_source_reference_digests",
                required=True,
                digests=True,
            ),
        )
        object.__setattr__(
            self,
            "unresolved_gap_codes",
            _strings(
                self.unresolved_gap_codes,
                "unresolved_gap_codes",
                required=True,
            ),
        )
        _digest(self.owner_identity_digest, "owner_identity_digest")
        _timestamp(self.proposed_at, "proposed_at")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(_record_dict(self, _PROPOSAL_FIELDS))

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, LOCALITY_COVERAGE_PROPOSAL, _PROPOSAL_FIELDS)
        for field in (
            "provider_decision_digests",
            "proposed_source_reference_digests",
            "unresolved_gap_codes",
        ):
            value[field] = tuple(value[field])  # type: ignore[arg-type]
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise LocalityQualificationError(
                "Locality Coverage Proposal replay differs"
            )
        return result


_DECISION_FIELDS = (
    "schema_version",
    "decision_id",
    "proposal_id",
    "proposal_digest",
    "outcome",
    "assessed_gap_codes",
    "reason_codes",
    "decider_identity_digest",
    "supersedes_decision_digest",
    "decided_at",
)


@dataclass(frozen=True, slots=True)
class LocalityCoverageDecision(_NoEffect):
    decision_id: str
    proposal_id: str
    proposal_digest: str
    outcome: LocalityDecisionOutcome
    assessed_gap_codes: tuple[str, ...]
    reason_codes: tuple[str, ...]
    decider_identity_digest: str
    supersedes_decision_digest: str | None
    decided_at: str
    schema_version: str = LOCALITY_COVERAGE_DECISION

    def __post_init__(self) -> None:
        if self.schema_version != LOCALITY_COVERAGE_DECISION:
            raise LocalityQualificationError(
                "Locality Coverage Decision schema differs"
            )
        _uuid(self.decision_id, "decision_id")
        _uuid(self.proposal_id, "proposal_id")
        _digest(self.proposal_digest, "proposal_digest")
        object.__setattr__(
            self,
            "outcome",
            _enum(LocalityDecisionOutcome, self.outcome, "outcome"),
        )
        for field in ("assessed_gap_codes", "reason_codes"):
            object.__setattr__(
                self,
                field,
                _strings(getattr(self, field), field, required=True),
            )
        _digest(self.decider_identity_digest, "decider_identity_digest")
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
        value = _document(raw, LOCALITY_COVERAGE_DECISION, _DECISION_FIELDS)
        for field in ("assessed_gap_codes", "reason_codes"):
            value[field] = tuple(value[field])  # type: ignore[arg-type]
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise LocalityQualificationError(
                "Locality Coverage Decision replay differs"
            )
        return result


def validate_locality_coverage_chain(
    reference: LocalityReference,
    unit: LocalityCoverageUnit,
    proposal: LocalityCoverageProposal,
    decision: LocalityCoverageDecision,
    previous: LocalityCoverageDecision | None = None,
) -> None:
    if any(
        type(value) is not kind
        for value, kind in (
            (reference, LocalityReference),
            (unit, LocalityCoverageUnit),
            (proposal, LocalityCoverageProposal),
            (decision, LocalityCoverageDecision),
        )
    ):
        raise LocalityQualificationError("locality chain requires exact records")
    if (
        unit.locality_reference_id != reference.locality_reference_id
        or unit.locality_reference_digest != reference.digest
        or unit.recorded_at < reference.recorded_at
        or proposal.coverage_unit_id != unit.coverage_unit_id
        or proposal.coverage_unit_digest != unit.digest
        or proposal.proposed_at < unit.recorded_at
        or not set(unit.known_gap_codes).issubset(proposal.unresolved_gap_codes)
        or decision.proposal_id != proposal.proposal_id
        or decision.proposal_digest != proposal.digest
        or decision.decided_at < proposal.proposed_at
        or set(decision.assessed_gap_codes) != set(proposal.unresolved_gap_codes)
    ):
        raise LocalityQualificationError("locality coverage lineage or gaps differ")
    if previous is None:
        if decision.supersedes_decision_digest is not None:
            raise LocalityQualificationError(
                "initial locality decision supersedes another"
            )
    else:
        validate_locality_coverage_chain(reference, unit, proposal, previous)
        if (
            decision.supersedes_decision_digest != previous.digest
            or decision.decided_at < previous.decided_at
        ):
            raise LocalityQualificationError("locality decision predecessor differs")


__all__ = [
    "LOCALITY_ACTIVATION",
    "LOCALITY_COMPLETENESS",
    "LOCALITY_COVERAGE_DECISION",
    "LOCALITY_COVERAGE_PROPOSAL",
    "LOCALITY_COVERAGE_UNIT",
    "LOCALITY_REFERENCE",
    "LocalityCompletenessClass",
    "LocalityCoverageDecision",
    "LocalityCoverageProposal",
    "LocalityCoverageUnit",
    "LocalityDecisionOutcome",
    "LocalityKind",
    "LocalityProposalPosture",
    "LocalityQualificationError",
    "LocalityReference",
    "LocalityServiceBoundary",
    "validate_locality_coverage_chain",
]
