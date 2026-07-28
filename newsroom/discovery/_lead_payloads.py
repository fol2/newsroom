from __future__ import annotations

from typing import Any

from newsroom.authority.types import UtcTimestamp
from newsroom.checks import ObservableTransitionId, ObservableTransitionKind
from newsroom.sources import (
    DiscoveryOccurrenceId,
    DiscoveryRepresentationId,
    PortfolioFunction,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
)

from ._payload_builders import (
    _IDEMPOTENCY,
    _canonicalize,
    _coverage,
    _dependency,
    _next_action,
    _policy,
    _reason,
    _role,
    _timestamp,
    _transition_kinds,
    _urgency,
)
from .models import (
    LeadDispositionDecisionRequest,
    NewsLeadRequest,
    WatchConditionRequest,
)
from .types import (
    DecisionTerminality,
    DiscoverySignalId,
    GateDecisionId,
    LeadDispositionDecisionId,
    LeadDispositionOutcome,
    NewsLeadId,
    WatchConditionId,
)


def news_lead_payload(value: Any) -> bytes:
    return _canonicalize(
        value,
        fields=frozenset(
            {
                "lead_id",
                "signal_id",
                "promoting_gate_decision_id",
                "definition_id",
                "definition_version_id",
                "item_id",
                "revision_id",
                "representation_id",
                "occurrence_id",
                "transition_id",
                "transition_kind",
                "coverage",
                "source_roles",
                "portfolio_functions",
                "source_dependencies",
                "incompleteness_warnings",
                "urgency",
                "lead_policy",
                "reason_taxonomy_version",
                "outcome_taxonomy_version",
                "created_at",
            }
        ),
        name="News Lead",
        build=lambda item: NewsLeadRequest(
            lead_id=NewsLeadId.parse(item["lead_id"]),
            signal_id=DiscoverySignalId.parse(item["signal_id"]),
            promoting_gate_decision_id=GateDecisionId.parse(
                item["promoting_gate_decision_id"]
            ),
            definition_id=SourceDefinitionId.parse(item["definition_id"]),
            definition_version_id=SourceDefinitionVersionId.parse(
                item["definition_version_id"]
            ),
            item_id=SourceItemId.parse(item["item_id"]),
            revision_id=SourceRevisionId.parse(item["revision_id"]),
            representation_id=DiscoveryRepresentationId.parse(
                item["representation_id"]
            ),
            occurrence_id=DiscoveryOccurrenceId.parse(item["occurrence_id"]),
            transition_id=ObservableTransitionId.parse(item["transition_id"]),
            transition_kind=ObservableTransitionKind(item["transition_kind"]),
            coverage=_coverage(item["coverage"]),
            source_roles=tuple(_role(role) for role in item["source_roles"]),
            portfolio_functions=tuple(
                PortfolioFunction(value) for value in item["portfolio_functions"]
            ),
            source_dependencies=tuple(
                _dependency(dependency) for dependency in item["source_dependencies"]
            ),
            incompleteness_warnings=tuple(item["incompleteness_warnings"]),
            urgency=_urgency(item["urgency"]),
            lead_policy=_policy(item["lead_policy"], field="lead_policy"),
            reason_taxonomy_version=item["reason_taxonomy_version"],
            outcome_taxonomy_version=item["outcome_taxonomy_version"],
            created_at=UtcTimestamp.parse(item["created_at"]),
            idempotency_key=_IDEMPOTENCY,
        ),
    )


def watch_condition_payload(value: Any) -> bytes:
    return _canonicalize(
        value,
        fields=frozenset(
            {
                "watch_condition_id",
                "lead_id",
                "resume_transition_kinds",
                "expected_occurrence",
                "corroborating_lead_id",
                "review_at",
                "expires_at",
                "operator_review_condition",
                "closure_rule",
                "watch_policy",
                "recorded_at",
            }
        ),
        name="Watch Condition",
        build=lambda item: WatchConditionRequest(
            watch_condition_id=WatchConditionId.parse(item["watch_condition_id"]),
            lead_id=NewsLeadId.parse(item["lead_id"]),
            resume_transition_kinds=_transition_kinds(
                item["resume_transition_kinds"]
            ),
            expected_occurrence=item["expected_occurrence"],
            corroborating_lead_id=(
                None
                if item["corroborating_lead_id"] is None
                else NewsLeadId.parse(item["corroborating_lead_id"])
            ),
            review_at=_timestamp(
                item["review_at"], field="watch.review_at", optional=True
            ),
            expires_at=_timestamp(
                item["expires_at"], field="watch.expires_at", optional=True
            ),
            operator_review_condition=item["operator_review_condition"],
            closure_rule=item["closure_rule"],
            watch_policy=_policy(item["watch_policy"], field="watch_policy"),
            recorded_at=UtcTimestamp.parse(item["recorded_at"]),
            idempotency_key=_IDEMPOTENCY,
        ),
    )


def lead_disposition_payload(value: Any) -> bytes:
    return _canonicalize(
        value,
        fields=frozenset(
            {
                "decision_id",
                "lead_id",
                "decision_ordinal",
                "previous_decision_id",
                "outcome",
                "terminality",
                "primary_reason",
                "supporting_reasons",
                "watch_condition_id",
                "next_action",
                "urgency_route",
                "disposition_policy",
                "reason_taxonomy_version",
                "outcome_taxonomy_version",
                "decided_at",
            }
        ),
        name="Lead Disposition Decision",
        build=lambda item: LeadDispositionDecisionRequest(
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
            supporting_reasons=tuple(
                _reason(reason) for reason in item["supporting_reasons"]
            ),
            watch_condition_id=(
                None
                if item["watch_condition_id"] is None
                else WatchConditionId.parse(item["watch_condition_id"])
            ),
            next_action=_next_action(item["next_action"]),
            urgency_route=_urgency(item["urgency_route"]),
            disposition_policy=_policy(
                item["disposition_policy"],
                field="lead_disposition_policy",
            ),
            reason_taxonomy_version=item["reason_taxonomy_version"],
            outcome_taxonomy_version=item["outcome_taxonomy_version"],
            decided_at=UtcTimestamp.parse(item["decided_at"]),
            idempotency_key=_IDEMPOTENCY,
        ),
    )


__all__ = [
    "lead_disposition_payload",
    "news_lead_payload",
    "watch_condition_payload",
]
