from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.authority.types import UtcTimestamp, require_token
from newsroom.sources import CheckOutcomeId, VersionedPolicyRef

from ._model_common import (
    optional_uuid,
    require_idempotency_key,
)
from .types import (
    CheckAttemptId,
    CheckContractError,
    CheckRequestId,
    FindingCategory,
    FindingScopeKind,
    FindingSeverity,
    OperationalFindingId,
    OperationalFindingOccurrenceId,
    bounded_text,
    canonical_digest,
    require_policy,
    require_uuid_text,
)


@dataclass(frozen=True, slots=True)
class OperationalFindingRequest:
    finding_id: OperationalFindingId
    scope_kind: FindingScopeKind
    scope_id: str
    category: FindingCategory
    severity: FindingSeverity
    finding_policy: VersionedPolicyRef
    summary: str
    opened_by_request_id: CheckRequestId | None
    opened_by_attempt_id: CheckAttemptId | None
    opened_by_outcome_id: CheckOutcomeId | None
    opened_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.finding_id, OperationalFindingId):
            raise CheckContractError(
                "Operational Finding identity must be typed"
            )
        if not isinstance(self.scope_kind, FindingScopeKind):
            raise CheckContractError("Finding scope kind must be typed")
        require_uuid_text(self.scope_id, field="finding_scope_id")
        if not isinstance(self.category, FindingCategory):
            raise CheckContractError("Finding category must be typed")
        if not isinstance(self.severity, FindingSeverity):
            raise CheckContractError("Finding severity must be typed")
        require_policy(self.finding_policy, field="finding_policy")
        bounded_text(
            self.summary,
            field="finding_summary",
            maximum_bytes=4096,
        )
        optional_uuid(
            self.opened_by_request_id,
            CheckRequestId,
            field="Finding Check Request",
        )
        optional_uuid(
            self.opened_by_attempt_id,
            CheckAttemptId,
            field="Finding Check Attempt",
        )
        optional_uuid(
            self.opened_by_outcome_id,
            CheckOutcomeId,
            field="Finding Check Outcome",
        )
        if not any(
            value is not None
            for value in (
                self.opened_by_request_id,
                self.opened_by_attempt_id,
                self.opened_by_outcome_id,
            )
        ):
            raise CheckContractError(
                "Operational Finding requires exact Check lineage"
            )
        if not isinstance(self.opened_at, UtcTimestamp):
            raise CheckContractError("Finding opening time must be typed")
        require_idempotency_key(self.idempotency_key)

    def canonical_value(self) -> dict[str, object]:
        return {
            "finding_id": str(self.finding_id),
            "scope_kind": self.scope_kind.value,
            "scope_id": self.scope_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "finding_policy": self.finding_policy.canonical_value(),
            "summary": self.summary,
            "opened_by_request_id": (
                None
                if self.opened_by_request_id is None
                else str(self.opened_by_request_id)
            ),
            "opened_by_attempt_id": (
                None
                if self.opened_by_attempt_id is None
                else str(self.opened_by_attempt_id)
            ),
            "opened_by_outcome_id": (
                None
                if self.opened_by_outcome_id is None
                else str(self.opened_by_outcome_id)
            ),
            "opened_at": self.opened_at.to_text(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        return digest_canonical(
            {
                "scope_kind": self.scope_kind.value,
                "scope_id": self.scope_id,
                "category": self.category.value,
                "finding_policy": self.finding_policy.canonical_value(),
            }
        )


@dataclass(frozen=True, slots=True)
class OperationalFindingOccurrenceRequest:
    occurrence_id: OperationalFindingOccurrenceId
    finding_id: OperationalFindingId
    request_id: CheckRequestId | None
    attempt_id: CheckAttemptId | None
    outcome_id: CheckOutcomeId | None
    code: str
    detail_digest: str
    observed_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(
            self.occurrence_id,
            OperationalFindingOccurrenceId,
        ):
            raise CheckContractError(
                "Finding occurrence identity must be typed"
            )
        if not isinstance(self.finding_id, OperationalFindingId):
            raise CheckContractError("Finding case identity must be typed")
        optional_uuid(
            self.request_id,
            CheckRequestId,
            field="Finding occurrence Check Request",
        )
        optional_uuid(
            self.attempt_id,
            CheckAttemptId,
            field="Finding occurrence Check Attempt",
        )
        optional_uuid(
            self.outcome_id,
            CheckOutcomeId,
            field="Finding occurrence Check Outcome",
        )
        if not any(
            value is not None
            for value in (
                self.request_id,
                self.attempt_id,
                self.outcome_id,
            )
        ):
            raise CheckContractError(
                "Finding occurrence requires exact Check lineage"
            )
        require_token(self.code, field="finding_occurrence_code")
        canonical_digest(
            self.detail_digest,
            field="finding_occurrence_detail_digest",
        )
        if not isinstance(self.observed_at, UtcTimestamp):
            raise CheckContractError(
                "Finding occurrence time must be typed"
            )
        require_idempotency_key(self.idempotency_key)

    def canonical_value(self) -> dict[str, object]:
        return {
            "occurrence_id": str(self.occurrence_id),
            "finding_id": str(self.finding_id),
            "request_id": (
                None if self.request_id is None else str(self.request_id)
            ),
            "attempt_id": (
                None if self.attempt_id is None else str(self.attempt_id)
            ),
            "outcome_id": (
                None if self.outcome_id is None else str(self.outcome_id)
            ),
            "code": self.code,
            "detail_digest": self.detail_digest,
            "observed_at": self.observed_at.to_text(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        value = self.canonical_value()
        value.pop("occurrence_id")
        value.pop("observed_at")
        return digest_canonical(value)


__all__ = [
    "OperationalFindingOccurrenceRequest",
    "OperationalFindingRequest",
]
