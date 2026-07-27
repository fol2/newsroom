from __future__ import annotations

from typing import Any

from newsroom.authority.types import UtcTimestamp
from newsroom.discovery_adapters import AdapterRequestId, ObservationProposalId
from newsroom.sources import (
    CheckOutcomeId,
    SourceDefinitionId,
    SourceDefinitionVersionId,
)

from ._payload_builders import (
    _IDEMPOTENCY,
    _candidate,
    _canonicalize,
    _coverage,
    _policy,
    _trigger,
)
from .check_models import (
    CheckAttemptRequest,
    CheckOutcomeRequest,
    CheckRequestRequest,
)
from .types import (
    CheckAttemptId,
    CheckAttemptKind,
    CheckOutcomeKind,
    CheckRequestId,
    QuarantineDisposition,
)


def check_request_payload(value: Any) -> bytes:
    return _canonicalize(
        value,
        fields=frozenset(
            {
                "request_id",
                "definition_id",
                "definition_version_id",
                "trigger",
                "coverage",
                "rights_decision_id",
                "rights_policy_version",
                "adapter_request_digest",
                "producer_slot_digest",
                "baseline_policy",
                "revision_policy",
                "transition_policy",
                "validator_policy",
                "purpose",
                "requested_at",
            }
        ),
        name="Check Request",
        build=lambda item: CheckRequestRequest(
            request_id=CheckRequestId.parse(item["request_id"]),
            definition_id=SourceDefinitionId.parse(item["definition_id"]),
            definition_version_id=SourceDefinitionVersionId.parse(
                item["definition_version_id"]
            ),
            trigger=_trigger(item["trigger"]),
            coverage=_coverage(item["coverage"]),
            rights_decision_id=item["rights_decision_id"],
            rights_policy_version=item["rights_policy_version"],
            adapter_request_digest=item["adapter_request_digest"],
            producer_slot_digest=item["producer_slot_digest"],
            baseline_policy=_policy(
                item["baseline_policy"],
                field="baseline_policy",
            ),
            revision_policy=_policy(
                item["revision_policy"],
                field="revision_policy",
            ),
            transition_policy=_policy(
                item["transition_policy"],
                field="transition_policy",
            ),
            validator_policy=_policy(
                item["validator_policy"],
                field="validator_policy",
            ),
            purpose=item["purpose"],
            requested_at=UtcTimestamp.parse(item["requested_at"]),
            idempotency_key=_IDEMPOTENCY,
        ),
    )


def check_attempt_payload(value: Any) -> bytes:
    return _canonicalize(
        value,
        fields=frozenset(
            {
                "attempt_id",
                "request_id",
                "attempt_number",
                "kind",
                "prior_attempt_id",
                "adapter_request_id",
                "adapter_request_digest",
                "started_at",
            }
        ),
        name="Check Attempt",
        build=lambda item: CheckAttemptRequest(
            attempt_id=CheckAttemptId.parse(item["attempt_id"]),
            request_id=CheckRequestId.parse(item["request_id"]),
            attempt_number=item["attempt_number"],
            kind=CheckAttemptKind(item["kind"]),
            prior_attempt_id=(
                None
                if item["prior_attempt_id"] is None
                else CheckAttemptId.parse(item["prior_attempt_id"])
            ),
            adapter_request_id=AdapterRequestId.parse(
                item["adapter_request_id"]
            ),
            adapter_request_digest=item["adapter_request_digest"],
            started_at=UtcTimestamp.parse(item["started_at"]),
            idempotency_key=_IDEMPOTENCY,
        ),
    )


def check_outcome_payload(value: Any) -> bytes:
    return _canonicalize(
        value,
        fields=frozenset(
            {
                "outcome_id",
                "request_id",
                "attempt_id",
                "proposal_id",
                "definition_id",
                "definition_version_id",
                "kind",
                "reason_codes",
                "quarantine",
                "incomplete",
                "receipt_digest",
                "capture_digest",
                "parser_result_digest",
                "source_body_digest",
                "producer_slot_digest",
                "representation_digest",
                "validator_digest",
                "candidate_observations",
                "completed_at",
            }
        ),
        name="Check Outcome",
        build=lambda item: CheckOutcomeRequest(
            outcome_id=CheckOutcomeId.parse(item["outcome_id"]),
            request_id=CheckRequestId.parse(item["request_id"]),
            attempt_id=CheckAttemptId.parse(item["attempt_id"]),
            proposal_id=ObservationProposalId.parse(item["proposal_id"]),
            definition_id=SourceDefinitionId.parse(item["definition_id"]),
            definition_version_id=SourceDefinitionVersionId.parse(
                item["definition_version_id"]
            ),
            kind=CheckOutcomeKind(item["kind"]),
            reason_codes=tuple(item["reason_codes"]),
            quarantine=QuarantineDisposition(item["quarantine"]),
            incomplete=item["incomplete"],
            receipt_digest=item["receipt_digest"],
            capture_digest=item["capture_digest"],
            parser_result_digest=item["parser_result_digest"],
            source_body_digest=item["source_body_digest"],
            producer_slot_digest=item["producer_slot_digest"],
            representation_digest=item["representation_digest"],
            validator_digest=item["validator_digest"],
            candidate_observations=tuple(
                _candidate(entry)
                for entry in item["candidate_observations"]
            ),
            completed_at=UtcTimestamp.parse(item["completed_at"]),
            idempotency_key=_IDEMPOTENCY,
        ),
    )


__all__ = [
    "check_attempt_payload",
    "check_outcome_payload",
    "check_request_payload",
]
