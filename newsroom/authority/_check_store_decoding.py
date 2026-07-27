from __future__ import annotations

from typing import Any, Callable, TypeVar

from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.policy import PayloadSchemaValidationError
from newsroom.authority.types import UtcTimestamp
from newsroom.checks._payload_builders import (
    _absence_guard,
    _agenda_guard,
    _candidate,
    _coverage,
    _manifest_entry,
    _policy,
    _source_time,
    _trigger,
)
from newsroom.checks.baseline_models import BaselineDecisionRequest
from newsroom.checks.check_models import (
    CheckAttemptRequest,
    CheckOutcomeRequest,
    CheckRequestRequest,
)
from newsroom.checks.finding_models import (
    OperationalFindingOccurrenceRequest,
    OperationalFindingRequest,
)
from newsroom.checks.transition_models import ObservableTransitionRequest
from newsroom.checks.types import (
    BaselineDecisionId,
    BaselineDecisionKind,
    BaselineDisposition,
    CheckAttemptId,
    CheckAttemptKind,
    CheckOutcomeKind,
    CheckRequestId,
    FindingCategory,
    FindingScopeKind,
    FindingSeverity,
    ObservableTransitionId,
    ObservableTransitionKind,
    OperationalFindingId,
    OperationalFindingOccurrenceId,
    QuarantineDisposition,
    TransitionBasis,
)
from newsroom.discovery_adapters import AdapterRequestId, ObservationProposalId
from newsroom.sources import (
    CheckOutcomeId,
    DiscoveryRepresentationId,
    ObservationModel,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
)


_Request = TypeVar("_Request")


def _decode(identity: str, build: Callable[[], _Request]) -> _Request:
    try:
        return build()
    except (
        KeyError,
        TypeError,
        ValueError,
        PayloadSchemaValidationError,
    ) as exc:
        raise AuthorityPersistenceError(
            f"{identity} canonical payload is invalid"
        ) from exc


def decode_check_request(
    value: dict[str, Any], *, idempotency_key: str
) -> CheckRequestRequest:
    return _decode(
        "Check Request",
        lambda: CheckRequestRequest(
            request_id=CheckRequestId.parse(str(value["request_id"])),
            definition_id=SourceDefinitionId.parse(
                str(value["definition_id"])
            ),
            definition_version_id=SourceDefinitionVersionId.parse(
                str(value["definition_version_id"])
            ),
            trigger=_trigger(value["trigger"]),
            coverage=_coverage(value["coverage"]),
            rights_decision_id=str(value["rights_decision_id"]),
            rights_policy_version=str(value["rights_policy_version"]),
            adapter_request_digest=str(value["adapter_request_digest"]),
            producer_slot_digest=str(value["producer_slot_digest"]),
            baseline_policy=_policy(
                value["baseline_policy"], field="baseline_policy"
            ),
            revision_policy=_policy(
                value["revision_policy"], field="revision_policy"
            ),
            transition_policy=_policy(
                value["transition_policy"], field="transition_policy"
            ),
            validator_policy=_policy(
                value["validator_policy"], field="validator_policy"
            ),
            purpose=str(value["purpose"]),
            requested_at=UtcTimestamp.parse(str(value["requested_at"])),
            idempotency_key=idempotency_key,
        ),
    )


def decode_check_attempt(
    value: dict[str, Any], *, idempotency_key: str
) -> CheckAttemptRequest:
    return _decode(
        "Check Attempt",
        lambda: CheckAttemptRequest(
            attempt_id=CheckAttemptId.parse(str(value["attempt_id"])),
            request_id=CheckRequestId.parse(str(value["request_id"])),
            attempt_number=int(value["attempt_number"]),
            kind=CheckAttemptKind(str(value["kind"])),
            prior_attempt_id=(
                None
                if value["prior_attempt_id"] is None
                else CheckAttemptId.parse(str(value["prior_attempt_id"]))
            ),
            adapter_request_id=AdapterRequestId.parse(
                str(value["adapter_request_id"])
            ),
            adapter_request_digest=str(value["adapter_request_digest"]),
            started_at=UtcTimestamp.parse(str(value["started_at"])),
            idempotency_key=idempotency_key,
        ),
    )


def decode_check_outcome(
    value: dict[str, Any], *, idempotency_key: str
) -> CheckOutcomeRequest:
    return _decode(
        "Check Outcome",
        lambda: CheckOutcomeRequest(
            outcome_id=CheckOutcomeId.parse(str(value["outcome_id"])),
            request_id=CheckRequestId.parse(str(value["request_id"])),
            attempt_id=CheckAttemptId.parse(str(value["attempt_id"])),
            proposal_id=ObservationProposalId.parse(
                str(value["proposal_id"])
            ),
            definition_id=SourceDefinitionId.parse(
                str(value["definition_id"])
            ),
            definition_version_id=SourceDefinitionVersionId.parse(
                str(value["definition_version_id"])
            ),
            kind=CheckOutcomeKind(str(value["kind"])),
            reason_codes=tuple(str(item) for item in value["reason_codes"]),
            quarantine=QuarantineDisposition(str(value["quarantine"])),
            incomplete=bool(value["incomplete"]),
            receipt_digest=(
                None
                if value["receipt_digest"] is None
                else str(value["receipt_digest"])
            ),
            capture_digest=(
                None
                if value["capture_digest"] is None
                else str(value["capture_digest"])
            ),
            parser_result_digest=(
                None
                if value["parser_result_digest"] is None
                else str(value["parser_result_digest"])
            ),
            source_body_digest=(
                None
                if value["source_body_digest"] is None
                else str(value["source_body_digest"])
            ),
            producer_slot_digest=(
                None
                if value["producer_slot_digest"] is None
                else str(value["producer_slot_digest"])
            ),
            representation_digest=(
                None
                if value["representation_digest"] is None
                else str(value["representation_digest"])
            ),
            validator_digest=(
                None
                if value["validator_digest"] is None
                else str(value["validator_digest"])
            ),
            candidate_observations=tuple(
                _candidate(item) for item in value["candidate_observations"]
            ),
            completed_at=UtcTimestamp.parse(str(value["completed_at"])),
            idempotency_key=idempotency_key,
        ),
    )


def decode_baseline_decision(
    value: dict[str, Any], *, idempotency_key: str
) -> BaselineDecisionRequest:
    return _decode(
        "Baseline Decision",
        lambda: BaselineDecisionRequest(
            decision_id=BaselineDecisionId.parse(str(value["decision_id"])),
            definition_id=SourceDefinitionId.parse(
                str(value["definition_id"])
            ),
            definition_version_id=SourceDefinitionVersionId.parse(
                str(value["definition_version_id"])
            ),
            check_request_id=CheckRequestId.parse(
                str(value["check_request_id"])
            ),
            check_outcome_id=CheckOutcomeId.parse(
                str(value["check_outcome_id"])
            ),
            kind=BaselineDecisionKind(str(value["kind"])),
            disposition=BaselineDisposition(str(value["disposition"])),
            observation_model=ObservationModel(str(value["observation_model"])),
            baseline_policy=_policy(
                value["baseline_policy"], field="baseline_policy"
            ),
            previous_decision_id=(
                None
                if value["previous_decision_id"] is None
                else BaselineDecisionId.parse(
                    str(value["previous_decision_id"])
                )
            ),
            entries=tuple(
                _manifest_entry(item) for item in value["entries"]
            ),
            source_body_digest=(
                None
                if value["source_body_digest"] is None
                else str(value["source_body_digest"])
            ),
            producer_slot_digest=(
                None
                if value["producer_slot_digest"] is None
                else str(value["producer_slot_digest"])
            ),
            representation_digest=(
                None
                if value["representation_digest"] is None
                else str(value["representation_digest"])
            ),
            validator_digest=(
                None
                if value["validator_digest"] is None
                else str(value["validator_digest"])
            ),
            reason_codes=tuple(str(item) for item in value["reason_codes"]),
            decided_at=UtcTimestamp.parse(str(value["decided_at"])),
            idempotency_key=idempotency_key,
        ),
    )


def decode_observable_transition(
    value: dict[str, Any], *, idempotency_key: str
) -> ObservableTransitionRequest:
    return _decode(
        "Observable Transition",
        lambda: ObservableTransitionRequest(
            transition_id=ObservableTransitionId.parse(
                str(value["transition_id"])
            ),
            definition_id=SourceDefinitionId.parse(
                str(value["definition_id"])
            ),
            definition_version_id=SourceDefinitionVersionId.parse(
                str(value["definition_version_id"])
            ),
            check_outcome_id=CheckOutcomeId.parse(
                str(value["check_outcome_id"])
            ),
            item_id=SourceItemId.parse(str(value["item_id"])),
            kind=ObservableTransitionKind(str(value["kind"])),
            basis=TransitionBasis(str(value["basis"])),
            observation_model=ObservationModel(str(value["observation_model"])),
            prior_revision_id=(
                None
                if value["prior_revision_id"] is None
                else SourceRevisionId.parse(str(value["prior_revision_id"]))
            ),
            current_revision_id=(
                None
                if value["current_revision_id"] is None
                else SourceRevisionId.parse(str(value["current_revision_id"]))
            ),
            representation_id=(
                None
                if value["representation_id"] is None
                else DiscoveryRepresentationId.parse(
                    str(value["representation_id"])
                )
            ),
            related_item_id=(
                None
                if value["related_item_id"] is None
                else SourceItemId.parse(str(value["related_item_id"]))
            ),
            change_facets=tuple(str(item) for item in value["change_facets"]),
            transition_policy=_policy(
                value["transition_policy"], field="transition_policy"
            ),
            absence_guard=(
                None
                if value["absence_guard"] is None
                else _absence_guard(value["absence_guard"])
            ),
            agenda_guard=(
                None
                if value["agenda_guard"] is None
                else _agenda_guard(value["agenda_guard"])
            ),
            source_asserted_time=_source_time(value["source_asserted_time"]),
            observed_at=UtcTimestamp.parse(str(value["observed_at"])),
            transition_discriminator=str(value["transition_discriminator"]),
            idempotency_key=idempotency_key,
        ),
    )


def decode_operational_finding(
    value: dict[str, Any], *, idempotency_key: str
) -> OperationalFindingRequest:
    return _decode(
        "Operational Finding",
        lambda: OperationalFindingRequest(
            finding_id=OperationalFindingId.parse(str(value["finding_id"])),
            scope_kind=FindingScopeKind(str(value["scope_kind"])),
            scope_id=str(value["scope_id"]),
            category=FindingCategory(str(value["category"])),
            severity=FindingSeverity(str(value["severity"])),
            finding_policy=_policy(
                value["finding_policy"], field="finding_policy"
            ),
            summary=str(value["summary"]),
            opened_by_request_id=(
                None
                if value["opened_by_request_id"] is None
                else CheckRequestId.parse(str(value["opened_by_request_id"]))
            ),
            opened_by_attempt_id=(
                None
                if value["opened_by_attempt_id"] is None
                else CheckAttemptId.parse(str(value["opened_by_attempt_id"]))
            ),
            opened_by_outcome_id=(
                None
                if value["opened_by_outcome_id"] is None
                else CheckOutcomeId.parse(str(value["opened_by_outcome_id"]))
            ),
            opened_at=UtcTimestamp.parse(str(value["opened_at"])),
            idempotency_key=idempotency_key,
        ),
    )


def decode_operational_finding_occurrence(
    value: dict[str, Any], *, idempotency_key: str
) -> OperationalFindingOccurrenceRequest:
    return _decode(
        "Operational Finding occurrence",
        lambda: OperationalFindingOccurrenceRequest(
            occurrence_id=OperationalFindingOccurrenceId.parse(
                str(value["occurrence_id"])
            ),
            finding_id=OperationalFindingId.parse(str(value["finding_id"])),
            request_id=(
                None
                if value["request_id"] is None
                else CheckRequestId.parse(str(value["request_id"]))
            ),
            attempt_id=(
                None
                if value["attempt_id"] is None
                else CheckAttemptId.parse(str(value["attempt_id"]))
            ),
            outcome_id=(
                None
                if value["outcome_id"] is None
                else CheckOutcomeId.parse(str(value["outcome_id"]))
            ),
            code=str(value["code"]),
            detail_digest=str(value["detail_digest"]),
            observed_at=UtcTimestamp.parse(str(value["observed_at"])),
            idempotency_key=idempotency_key,
        ),
    )


__all__ = [
    "decode_baseline_decision",
    "decode_check_attempt",
    "decode_check_outcome",
    "decode_check_request",
    "decode_observable_transition",
    "decode_operational_finding",
    "decode_operational_finding_occurrence",
]
