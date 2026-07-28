from __future__ import annotations

from typing import Any

from newsroom.authority.types import UtcTimestamp
from newsroom.sources import SourceDefinitionVersionId

from ._payload_builders import (
    _IDEMPOTENCY,
    _canonicalize,
    _coverage,
    _gate_basis,
    _next_action,
    _policy,
    _reason,
)
from .models import GateDecisionRequest
from .types import (
    DecisionTerminality,
    DiscoverySignalId,
    GateDecisionId,
    GateOutcome,
)


def gate_decision_payload(value: Any) -> bytes:
    return _canonicalize(
        value,
        fields=frozenset(
            {
                "decision_id",
                "signal_id",
                "decision_ordinal",
                "previous_decision_id",
                "evaluated_definition_version_id",
                "coverage",
                "rights_decision_id",
                "rights_policy_version",
                "signal_admission_policy",
                "gate_policy",
                "duplicate_policy",
                "newness_policy",
                "time_validity_policy",
                "exclusion_policy",
                "basis",
                "outcome",
                "terminality",
                "primary_reason",
                "supporting_reasons",
                "reason_taxonomy_version",
                "outcome_taxonomy_version",
                "next_action",
                "decided_at",
            }
        ),
        name="Gate Decision",
        build=lambda item: GateDecisionRequest(
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
                item["signal_admission_policy"],
                field="signal_admission_policy",
            ),
            gate_policy=_policy(item["gate_policy"], field="gate_policy"),
            duplicate_policy=_policy(
                item["duplicate_policy"],
                field="duplicate_policy",
            ),
            newness_policy=_policy(
                item["newness_policy"],
                field="newness_policy",
            ),
            time_validity_policy=_policy(
                item["time_validity_policy"],
                field="time_validity_policy",
            ),
            exclusion_policy=_policy(
                item["exclusion_policy"],
                field="exclusion_policy",
            ),
            basis=_gate_basis(item["basis"]),
            outcome=GateOutcome(item["outcome"]),
            terminality=DecisionTerminality(item["terminality"]),
            primary_reason=_reason(item["primary_reason"]),
            supporting_reasons=tuple(
                _reason(reason) for reason in item["supporting_reasons"]
            ),
            reason_taxonomy_version=item["reason_taxonomy_version"],
            outcome_taxonomy_version=item["outcome_taxonomy_version"],
            next_action=(
                None
                if item["next_action"] is None
                else _next_action(item["next_action"])
            ),
            decided_at=UtcTimestamp.parse(item["decided_at"]),
            idempotency_key=_IDEMPOTENCY,
        ),
    )


__all__ = ["gate_decision_payload"]
