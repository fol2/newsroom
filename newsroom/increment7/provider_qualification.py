"""Immutable provider qualification decision seams for Increment 7E1.

These contracts record research posture only. They expose no provider client,
credential, query, network, spending, schedule, retry or activation capability.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Self

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)

PROVIDER_PROPOSAL = "newsroom.increment7.provider-proposal.v1"
PROVIDER_DECISION = "newsroom.increment7.provider-decision.v1"
PROVIDER_QUALIFICATION_AUTHORITY = "DECISION_RECORD_ONLY_NO_ACTIVATION"
PROVIDER_CURRENT_POSTURE = MappingProxyType(
    {
        "GDELT": "HELD",
        "BRAVE_SEARCH": "RIGHTS_REVIEW_REQUIRED",
        "SEARXNG": "RESEARCH",
        "UNOFFICIAL_WRAPPER": "RESEARCH",
    }
)
MAX_PROVIDER_QUALIFICATION_BYTES = 1_048_576

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}\Z")
_UTC = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)


class ProviderQualificationError(ValueError):
    """Untrusted provider qualification values failed the exact v1 contract."""


class ProviderKind(StrEnum):
    GDELT = "GDELT"
    BRAVE_SEARCH = "BRAVE_SEARCH"
    SEARXNG = "SEARXNG"
    UNOFFICIAL_WRAPPER = "UNOFFICIAL_WRAPPER"
    OTHER = "OTHER"


class ProviderQualificationStatus(StrEnum):
    RESEARCH = "RESEARCH"
    RIGHTS_REVIEW_REQUIRED = "RIGHTS_REVIEW_REQUIRED"
    HELD = "HELD"
    REJECTED = "REJECTED"
    QUALIFIED_FOR_SEPARATE_ADMISSION_REVIEW = "QUALIFIED_FOR_SEPARATE_ADMISSION_REVIEW"


class ProviderPrerequisite(StrEnum):
    AMPLIFICATION_LIMITS = "AMPLIFICATION_LIMITS"
    EVALUATION_PLAN = "EVALUATION_PLAN"
    GROSS_BUDGET = "GROSS_BUDGET"
    OPERATIONAL_PROFILE = "OPERATIONAL_PROFILE"
    OWNER_AUTHORITY = "OWNER_AUTHORITY"
    PROVIDER_SOURCE_VERSION = "PROVIDER_SOURCE_VERSION"
    QUERY_DATA_HANDLING = "QUERY_DATA_HANDLING"
    RIGHTS_BASIS = "RIGHTS_BASIS"


class ProviderPrerequisiteOutcome(StrEnum):
    SATISFIED = "SATISFIED"
    MISSING = "MISSING"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class _NoEffect:
    authorises_external_effect = False
    authorises_provider = False
    authorises_credentials = False
    authorises_query_execution = False
    authorises_egress = False
    authorises_spend = False
    authorises_schedule = False
    authorises_retry = False
    authorises_fallback = False
    authorises_model_submission = False
    authorises_evidence = False
    authorises_publication = False
    authorises_locality = False
    creates_signal = False
    creates_lead = False
    creates_candidate = False
    production_activation_authorised = False


def _text(value: object, field: str, maximum: int = 2_048) -> str:
    try:
        size = len(value.encode()) if type(value) is str else 0
    except UnicodeError as exc:
        raise ProviderQualificationError(f"{field} must be canonical text") from exc
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or size > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ProviderQualificationError(f"{field} must be canonical text")
    return value


def _token(value: object, field: str) -> str:
    value = _text(value, field, 256)
    if _TOKEN.fullmatch(value) is None:
        raise ProviderQualificationError(f"{field} must be a canonical token")
    return value


def _uuid(value: object, field: str) -> str:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        raise ProviderQualificationError(f"{field} must be a canonical UUID")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError as exc:
        raise ProviderQualificationError(f"{field} must be a canonical UUID") from exc
    return value


def _digest(value: object, field: str) -> str:
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise ProviderQualificationError(f"{field} must be a SHA-256 digest") from exc


def _timestamp(value: object, field: str) -> str:
    value = _text(value, field, 27)
    if _UTC.fullmatch(value) is None:
        raise ProviderQualificationError(f"{field} must be an exact UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise ProviderQualificationError(
            f"{field} must be an exact UTC timestamp"
        ) from exc
    return value


def _enum[T: StrEnum](kind: type[T], value: object, field: str) -> T:
    if type(value) is not str and type(value) is not kind:
        raise ProviderQualificationError(f"{field} differs")
    try:
        return kind(value)
    except ValueError as exc:
        raise ProviderQualificationError(f"{field} differs") from exc


def _strings(
    value: object, field: str, *, required: bool = False, digests: bool = False
) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > 64 or (required and not value):
        raise ProviderQualificationError(f"{field} must be a bounded array")
    validator = _digest if digests else _token
    result = tuple(validator(item, field) for item in value)
    if tuple(sorted(set(result))) != result:
        raise ProviderQualificationError(f"{field} must be unique and sorted")
    return result


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProviderQualificationError(f"duplicate object name: {key}")
        result[key] = value
    return result


def _array(value: object, field: str) -> tuple[object, ...]:
    if type(value) is not list:
        raise ProviderQualificationError(f"{field} must be an array")
    return tuple(value)


def _document(raw: bytes, schema: str, fields: tuple[str, ...]) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_PROVIDER_QUALIFICATION_BYTES:
        raise ProviderQualificationError("provider qualification bytes are not bounded")
    try:
        value = json.loads(raw.decode(), object_pairs_hook=_pairs)
        canonical = canonical_json_bytes(value)
    except ProviderQualificationError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
        RecursionError,
        ValueError,
    ) as exc:
        raise ProviderQualificationError(
            "provider qualification bytes are not canonical JSON"
        ) from exc
    if type(value) is not dict or raw != canonical:
        raise ProviderQualificationError(
            "provider qualification bytes are not exact canonical JSON"
        )
    if tuple(value) != tuple(sorted(fields)) or value.get("schema_version") != schema:
        raise ProviderQualificationError(
            "provider qualification fields or schema differ"
        )
    return value


_ASSESSMENT_FIELDS = ("outcome", "prerequisite", "reference_digest")


@dataclass(frozen=True, slots=True)
class ProviderPrerequisiteAssessment(_NoEffect):
    prerequisite: ProviderPrerequisite
    outcome: ProviderPrerequisiteOutcome
    reference_digest: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "prerequisite",
            _enum(ProviderPrerequisite, self.prerequisite, "prerequisite"),
        )
        object.__setattr__(
            self,
            "outcome",
            _enum(ProviderPrerequisiteOutcome, self.outcome, "outcome"),
        )
        if self.outcome is ProviderPrerequisiteOutcome.SATISFIED:
            if self.reference_digest is None:
                raise ProviderQualificationError(
                    "satisfied prerequisite lacks an exact reference"
                )
            _digest(self.reference_digest, "reference_digest")
        elif self.reference_digest is not None:
            raise ProviderQualificationError(
                "unsatisfied prerequisite carries an authority reference"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "prerequisite": self.prerequisite.value,
            "reference_digest": self.reference_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict or tuple(value) != _ASSESSMENT_FIELDS:
            raise ProviderQualificationError("prerequisite assessment fields differ")
        return cls(**value)  # type: ignore[arg-type]


_PROPOSAL_FIELDS = (
    "schema_version",
    "proposal_id",
    "provider_id",
    "provider_kind",
    "provider_display_name",
    "proposed_posture",
    "capability_scope",
    "provider_source_version",
    "research_reference_digests",
    "proposer_identity_digest",
    "proposed_at",
)


@dataclass(frozen=True, slots=True)
class ProviderProposal(_NoEffect):
    proposal_id: str
    provider_id: str
    provider_kind: ProviderKind
    provider_display_name: str
    proposed_posture: ProviderQualificationStatus
    capability_scope: tuple[str, ...]
    provider_source_version: str
    research_reference_digests: tuple[str, ...]
    proposer_identity_digest: str
    proposed_at: str
    schema_version: str = PROVIDER_PROPOSAL

    def __post_init__(self) -> None:
        if self.schema_version != PROVIDER_PROPOSAL:
            raise ProviderQualificationError("Provider Proposal schema differs")
        _uuid(self.proposal_id, "proposal_id")
        _token(self.provider_id, "provider_id")
        object.__setattr__(
            self,
            "provider_kind",
            _enum(ProviderKind, self.provider_kind, "provider_kind"),
        )
        _text(self.provider_display_name, "provider_display_name", 512)
        object.__setattr__(
            self,
            "proposed_posture",
            _enum(
                ProviderQualificationStatus,
                self.proposed_posture,
                "proposed_posture",
            ),
        )
        expected = ProviderQualificationStatus(
            PROVIDER_CURRENT_POSTURE.get(self.provider_kind.value, "RESEARCH")
        )
        if self.proposed_posture is not expected:
            raise ProviderQualificationError(
                "Provider current posture must be preserved"
            )
        object.__setattr__(
            self,
            "capability_scope",
            _strings(self.capability_scope, "capability_scope", required=True),
        )
        _token(self.provider_source_version, "provider_source_version")
        object.__setattr__(
            self,
            "research_reference_digests",
            _strings(
                self.research_reference_digests,
                "research_reference_digests",
                required=True,
                digests=True,
            ),
        )
        _digest(self.proposer_identity_digest, "proposer_identity_digest")
        _timestamp(self.proposed_at, "proposed_at")

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                field: (
                    getattr(self, field).value
                    if isinstance(getattr(self, field), StrEnum)
                    else list(getattr(self, field))
                    if isinstance(getattr(self, field), tuple)
                    else getattr(self, field)
                )
                for field in _PROPOSAL_FIELDS
            }
        )

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, PROVIDER_PROPOSAL, _PROPOSAL_FIELDS)
        for field in ("capability_scope", "research_reference_digests"):
            value[field] = _array(value[field], field)
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise ProviderQualificationError("Provider Proposal replay differs")
        return result


_DECISION_FIELDS = (
    "schema_version",
    "decision_id",
    "proposal_id",
    "proposal_digest",
    "status",
    "prerequisite_assessments",
    "supersedes_decision_digest",
    "decider_identity_digest",
    "reason_codes",
    "decided_at",
)


@dataclass(frozen=True, slots=True)
class ProviderDecision(_NoEffect):
    decision_id: str
    proposal_id: str
    proposal_digest: str
    status: ProviderQualificationStatus
    prerequisite_assessments: tuple[ProviderPrerequisiteAssessment, ...]
    supersedes_decision_digest: str | None
    decider_identity_digest: str
    reason_codes: tuple[str, ...]
    decided_at: str
    schema_version: str = PROVIDER_DECISION

    def __post_init__(self) -> None:
        if self.schema_version != PROVIDER_DECISION:
            raise ProviderQualificationError("Provider Decision schema differs")
        _uuid(self.decision_id, "decision_id")
        _uuid(self.proposal_id, "proposal_id")
        _digest(self.proposal_digest, "proposal_digest")
        object.__setattr__(
            self, "status", _enum(ProviderQualificationStatus, self.status, "status")
        )
        if type(self.prerequisite_assessments) is not tuple:
            raise ProviderQualificationError("prerequisite assessments differ")
        assessments = tuple(
            item
            if type(item) is ProviderPrerequisiteAssessment
            else ProviderPrerequisiteAssessment.from_dict(item)
            for item in self.prerequisite_assessments
        )
        if tuple(item.prerequisite for item in assessments) != tuple(
            ProviderPrerequisite
        ):
            raise ProviderQualificationError(
                "all prerequisite assessments must be exact and ordered"
            )
        object.__setattr__(self, "prerequisite_assessments", assessments)
        if self.supersedes_decision_digest is not None:
            _digest(self.supersedes_decision_digest, "supersedes_decision_digest")
        _digest(self.decider_identity_digest, "decider_identity_digest")
        object.__setattr__(
            self,
            "reason_codes",
            _strings(self.reason_codes, "reason_codes", required=True),
        )
        _timestamp(self.decided_at, "decided_at")
        all_satisfied = all(
            item.outcome is ProviderPrerequisiteOutcome.SATISFIED
            for item in assessments
        )
        qualified = (
            self.status
            is ProviderQualificationStatus.QUALIFIED_FOR_SEPARATE_ADMISSION_REVIEW
        )
        if qualified and not all_satisfied:
            raise ProviderQualificationError(
                "qualification status and prerequisites differ"
            )

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "decided_at": self.decided_at,
                "decider_identity_digest": self.decider_identity_digest,
                "decision_id": self.decision_id,
                "prerequisite_assessments": [
                    item.to_dict() for item in self.prerequisite_assessments
                ],
                "proposal_digest": self.proposal_digest,
                "proposal_id": self.proposal_id,
                "reason_codes": list(self.reason_codes),
                "schema_version": self.schema_version,
                "status": self.status.value,
                "supersedes_decision_digest": self.supersedes_decision_digest,
            }
        )

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        value = _document(raw, PROVIDER_DECISION, _DECISION_FIELDS)
        value["prerequisite_assessments"] = tuple(
            ProviderPrerequisiteAssessment.from_dict(item)
            for item in _array(
                value["prerequisite_assessments"], "prerequisite_assessments"
            )
        )
        value["reason_codes"] = _array(value["reason_codes"], "reason_codes")
        result = cls(**value)  # type: ignore[arg-type]
        if result.canonical_bytes != raw:
            raise ProviderQualificationError("Provider Decision replay differs")
        return result


def validate_provider_decision(
    proposal: ProviderProposal,
    decision: ProviderDecision,
    previous: ProviderDecision | None = None,
) -> None:
    _validate_provider_decision_binding(proposal, decision)
    if previous is None:
        if decision.supersedes_decision_digest is not None:
            raise ProviderQualificationError(
                "initial Provider Decision supersedes another"
            )
    else:
        _validate_provider_decision_binding(proposal, previous)
        if (
            decision.decision_id == previous.decision_id
            or decision.proposal_id != previous.proposal_id
            or decision.supersedes_decision_digest != previous.digest
            or decision.decided_at < previous.decided_at
        ):
            raise ProviderQualificationError("Provider Decision predecessor differs")


def _validate_provider_decision_binding(
    proposal: ProviderProposal,
    decision: ProviderDecision,
) -> None:
    if type(proposal) is not ProviderProposal or type(decision) is not ProviderDecision:
        raise ProviderQualificationError(
            "Provider decision binding requires exact records"
        )
    expected_current = ProviderQualificationStatus(
        PROVIDER_CURRENT_POSTURE.get(proposal.provider_kind.value, "RESEARCH")
    )
    allowed = {expected_current, ProviderQualificationStatus.REJECTED}
    if (
        decision.proposal_id != proposal.proposal_id
        or decision.proposal_digest != proposal.digest
        or decision.decided_at < proposal.proposed_at
        or decision.status not in allowed
    ):
        raise ProviderQualificationError(
            "Provider Decision exceeds Proposal or current posture"
        )


__all__ = [
    "MAX_PROVIDER_QUALIFICATION_BYTES",
    "PROVIDER_CURRENT_POSTURE",
    "PROVIDER_DECISION",
    "PROVIDER_PROPOSAL",
    "PROVIDER_QUALIFICATION_AUTHORITY",
    "ProviderDecision",
    "ProviderKind",
    "ProviderPrerequisite",
    "ProviderPrerequisiteAssessment",
    "ProviderPrerequisiteOutcome",
    "ProviderProposal",
    "ProviderQualificationError",
    "ProviderQualificationStatus",
    "validate_provider_decision",
]
