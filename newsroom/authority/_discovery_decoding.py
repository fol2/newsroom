from __future__ import annotations

import json
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import UtcTimestamp
from newsroom.checks import CheckOutcomeId, ObservableTransitionId, ObservableTransitionKind, OperationalFindingId
from newsroom.discovery._payload_builders import (
    _coverage,
    _dependency,
    _gate_basis,
    _next_action,
    _policy,
    _reason,
    _role,
    _timestamp,
    _transition_kinds,
    _urgency,
)
from newsroom.discovery.models import (
    DiscoverySignalRequest,
    GateDecisionRequest,
    LeadDispositionDecisionRequest,
    NewsLeadRequest,
    WatchConditionRequest,
)
from newsroom.discovery.types import (
    DecisionTerminality,
    DiscoverySignalId,
    GateDecisionId,
    GateOutcome,
    LeadDispositionDecisionId,
    LeadDispositionOutcome,
    NewsLeadId,
    WatchConditionId,
)
from newsroom.sources import (
    DiscoveryOccurrenceId,
    DiscoveryRepresentationId,
    PortfolioFunction,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
)

_REHYDRATED_IDEMPOTENCY = "rehydrated-authority-record"


def _mapping(data: bytes, *, name: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityPersistenceError(f"stored {name} canonical bytes are invalid") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != data:
        raise AuthorityPersistenceError(f"stored {name} bytes are not canonical JSON")
    return value


def signal_request_from_bytes(data: bytes) -> DiscoverySignalRequest:
    item = _mapping(data, name="Discovery Signal")
    try:
        return DiscoverySignalRequest(
            signal_id=DiscoverySignalId.parse(item["signal_id"]),
            definition_id=SourceDefinitionId.parse(item["definition_id"]),
            definition_version_id=SourceDefinitionVersionId.parse(item["definition_version_id"]),
            item_id=SourceItemId.parse(item["item_id"]),
            revision_id=SourceRevisionId.parse(item["revision_id"]),
            representation_id=DiscoveryRepresentationId.parse(item["representation_id"]),
            check_outcome_id=CheckOutcomeId.parse(item["check_outcome_id"]),
            occurrence_id=DiscoveryOccurrenceId.parse(item["occurrence_id"]),
            transition_id=ObservableTransitionId.parse(item["transition_id"]),
            purpose=item["purpose"],
            discriminator=item["discriminator"],
            admission_policy=_policy(item["admission_policy"], field="signal_admission_policy"),
            incomplete=item["incomplete"],
            operational_finding_ids=tuple(
                OperationalFindingId.parse(value)
                for value in item["operational_finding_ids"]
            ),
            admitted_at=UtcTimestamp.parse(item["admitted_at"]),
            idempotency_key=_REHYDRATED_IDEMPOTENCY,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorityPersistenceError("stored Discovery Signal is malformed") from exc


def gate_request_from_bytes(data: bytes) -> GateDecisionRequest:
    item = _mapping(data, name="Gate Decision")
    try:
        return GateDecisionRequest(
            decision_id=GateDecisionId.parse(item["decision_id"]),
            signal_id=DiscoverySignalId.parse(item["signal_id"]),
            decision_ordinal=item["decision_ordinal"],
            previous_decision_id=(
                None
                if item["previous_decision_id"] is None
                else GateDecisionId.parse(item["previous_decision_id"])
            ),
            evaluated_definition_version_id=SourceDefinitionVersionId.parse(
                item["evaluated_definition_version_id"]
            ),
            coverage=_coverage(item["coverage"]),
            rights_decision_id=item["rights_decision_id"],
            rights_policy_version=item["rights_policy_version"],
            signal_admission_policy=_policy(
                item["signal_admission_policy"], field="signal_admission_policy"
            ),
            gate_policy=_policy(item["gate_policy"], field="gate_policy"),
            duplicate_policy=_policy(item["duplicate_policy"], field="duplicate_policy"),
            newness_policy=_policy(item["newness_policy"], field="newness_policy"),
            time_validity_policy=_policy(
                item["time_validity_policy"], field="time_validity_policy"
            ),
            exclusion_policy=_policy(item["exclusion_policy"], field="exclusion_policy"),
            basis=_gate_basis(item["basis"]),
            outcome=GateOutcome(item["outcome"]),
            terminality=DecisionTerminality(item["terminality"]),
            primary_reason=_reason(item["primary_reason"]),
            supporting_reasons=tuple(_reason(value) for value in item["supporting_reasons"]),
            reason_taxonomy_version=item["reason_taxonomy_version"],
            outcome_taxonomy_version=item["outcome_taxonomy_version"],
            next_action=(
                None if item["next_action"] is None else _next_action(item["next_action"])
            ),
            decided_at=UtcTimestamp.parse(item["decided_at"]),
            idempotency_key=_REHYDRATED_IDEMPOTENCY,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorityPersistenceError("stored Gate Decision is malformed") from exc


def lead_request_from_bytes(data: bytes) -> NewsLeadRequest:
    item = _mapping(data, name="News Lead")
    try:
        return NewsLeadRequest(
            lead_id=NewsLeadId.parse(item["lead_id"]),
            signal_id=DiscoverySignalId.parse(item["signal_id"]),
            promoting_gate_decision_id=GateDecisionId.parse(item["promoting_gate_decision_id"]),
            definition_id=SourceDefinitionId.parse(item["definition_id"]),
            definition_version_id=SourceDefinitionVersionId.parse(item["definition_version_id"]),
            item_id=SourceItemId.parse(item["item_id"]),
            revision_id=SourceRevisionId.parse(item["revision_id"]),
            representation_id=DiscoveryRepresentationId.parse(item["representation_id"]),
            occurrence_id=DiscoveryOccurrenceId.parse(item["occurrence_id"]),
            transition_id=ObservableTransitionId.parse(item["transition_id"]),
            transition_kind=ObservableTransitionKind(item["transition_kind"]),
            coverage=_coverage(item["coverage"]),
            source_roles=tuple(_role(value) for value in item["source_roles"]),
            portfolio_functions=tuple(PortfolioFunction(value) for value in item["portfolio_functions"]),
            source_dependencies=tuple(_dependency(value) for value in item["source_dependencies"]),
            incompleteness_warnings=tuple(item["incompleteness_warnings"]),
            urgency=_urgency(item["urgency"]),
            lead_policy=_policy(item["lead_policy"], field="lead_policy"),
            reason_taxonomy_version=item["reason_taxonomy_version"],
            outcome_taxonomy_version=item["outcome_taxonomy_version"],
            created_at=UtcTimestamp.parse(item["created_at"]),
            idempotency_key=_REHYDRATED_IDEMPOTENCY,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorityPersistenceError("stored News Lead is malformed") from exc


def watch_request_from_bytes(data: bytes) -> WatchConditionRequest:
    item = _mapping(data, name="Watch Condition")
    try:
        return WatchConditionRequest(
            watch_condition_id=WatchConditionId.parse(item["watch_condition_id"]),
            lead_id=NewsLeadId.parse(item["lead_id"]),
            resume_transition_kinds=_transition_kinds(item["resume_transition_kinds"]),
            expected_occurrence=item["expected_occurrence"],
            corroborating_lead_id=(
                None
                if item["corroborating_lead_id"] is None
                else NewsLeadId.parse(item["corroborating_lead_id"])
            ),
            review_at=_timestamp(item["review_at"], field="watch.review_at", optional=True),
            expires_at=_timestamp(item["expires_at"], field="watch.expires_at", optional=True),
            operator_review_condition=item["operator_review_condition"],
            closure_rule=item["closure_rule"],
            watch_policy=_policy(item["watch_policy"], field="watch_policy"),
            recorded_at=UtcTimestamp.parse(item["recorded_at"]),
            idempotency_key=_REHYDRATED_IDEMPOTENCY,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorityPersistenceError("stored Watch Condition is malformed") from exc


def disposition_request_from_bytes(data: bytes) -> LeadDispositionDecisionRequest:
    item = _mapping(data, name="Lead Disposition Decision")
    try:
        return LeadDispositionDecisionRequest(
            decision_id=LeadDispositionDecisionId.parse(item["decision_id"]),
            lead_id=NewsLeadId.parse(item["lead_id"]),
            decision_ordinal=item["decision_ordinal"],
            previous_decision_id=(
                None
                if item["previous_decision_id"] is None
                else LeadDispositionDecisionId.parse(item["previous_decision_id"])
            ),
            outcome=LeadDispositionOutcome(item["outcome"]),
            terminality=DecisionTerminality(item["terminality"]),
            primary_reason=_reason(item["primary_reason"]),
            supporting_reasons=tuple(_reason(value) for value in item["supporting_reasons"]),
            watch_condition_id=(
                None
                if item["watch_condition_id"] is None
                else WatchConditionId.parse(item["watch_condition_id"])
            ),
            next_action=_next_action(item["next_action"]),
            urgency_route=_urgency(item["urgency_route"]),
            disposition_policy=_policy(
                item["disposition_policy"], field="lead_disposition_policy"
            ),
            reason_taxonomy_version=item["reason_taxonomy_version"],
            outcome_taxonomy_version=item["outcome_taxonomy_version"],
            decided_at=UtcTimestamp.parse(item["decided_at"]),
            idempotency_key=_REHYDRATED_IDEMPOTENCY,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorityPersistenceError("stored Lead Disposition is malformed") from exc


__all__ = [
    "disposition_request_from_bytes",
    "gate_request_from_bytes",
    "lead_request_from_bytes",
    "signal_request_from_bytes",
    "watch_request_from_bytes",
]
