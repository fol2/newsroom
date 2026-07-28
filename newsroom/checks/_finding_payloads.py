from __future__ import annotations

from typing import Any

from newsroom.authority.types import UtcTimestamp
from newsroom.sources import CheckOutcomeId

from ._payload_builders import _IDEMPOTENCY, _canonicalize, _policy
from .finding_models import (
    OperationalFindingOccurrenceRequest,
    OperationalFindingRequest,
)
from .types import (
    CheckAttemptId,
    CheckRequestId,
    FindingCategory,
    FindingScopeKind,
    FindingSeverity,
    OperationalFindingId,
    OperationalFindingOccurrenceId,
)


def operational_finding_payload(value: Any) -> bytes:
    return _canonicalize(
        value,
        fields=frozenset(
            {
                "finding_id",
                "scope_kind",
                "scope_id",
                "category",
                "severity",
                "finding_policy",
                "summary",
                "opened_by_request_id",
                "opened_by_attempt_id",
                "opened_by_outcome_id",
                "opened_at",
            }
        ),
        name="Operational Finding",
        build=lambda item: OperationalFindingRequest(
            finding_id=OperationalFindingId.parse(item["finding_id"]),
            scope_kind=FindingScopeKind(item["scope_kind"]),
            scope_id=item["scope_id"],
            category=FindingCategory(item["category"]),
            severity=FindingSeverity(item["severity"]),
            finding_policy=_policy(
                item["finding_policy"],
                field="finding_policy",
            ),
            summary=item["summary"],
            opened_by_request_id=(
                None
                if item["opened_by_request_id"] is None
                else CheckRequestId.parse(item["opened_by_request_id"])
            ),
            opened_by_attempt_id=(
                None
                if item["opened_by_attempt_id"] is None
                else CheckAttemptId.parse(item["opened_by_attempt_id"])
            ),
            opened_by_outcome_id=(
                None
                if item["opened_by_outcome_id"] is None
                else CheckOutcomeId.parse(item["opened_by_outcome_id"])
            ),
            opened_at=UtcTimestamp.parse(item["opened_at"]),
            idempotency_key=_IDEMPOTENCY,
        ),
    )


def operational_finding_occurrence_payload(value: Any) -> bytes:
    return _canonicalize(
        value,
        fields=frozenset(
            {
                "occurrence_id",
                "finding_id",
                "request_id",
                "attempt_id",
                "outcome_id",
                "code",
                "detail_digest",
                "observed_at",
            }
        ),
        name="Operational Finding occurrence",
        build=lambda item: OperationalFindingOccurrenceRequest(
            occurrence_id=OperationalFindingOccurrenceId.parse(
                item["occurrence_id"]
            ),
            finding_id=OperationalFindingId.parse(item["finding_id"]),
            request_id=(
                None
                if item["request_id"] is None
                else CheckRequestId.parse(item["request_id"])
            ),
            attempt_id=(
                None
                if item["attempt_id"] is None
                else CheckAttemptId.parse(item["attempt_id"])
            ),
            outcome_id=(
                None
                if item["outcome_id"] is None
                else CheckOutcomeId.parse(item["outcome_id"])
            ),
            code=item["code"],
            detail_digest=item["detail_digest"],
            observed_at=UtcTimestamp.parse(item["observed_at"]),
            idempotency_key=_IDEMPOTENCY,
        ),
    )


__all__ = [
    "operational_finding_occurrence_payload",
    "operational_finding_payload",
]
