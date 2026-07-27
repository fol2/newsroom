from __future__ import annotations

from typing import Any

from newsroom.authority.types import UtcTimestamp
from newsroom.sources import (
    CheckOutcomeId,
    ObservationModel,
    SourceDefinitionId,
    SourceDefinitionVersionId,
)

from ._payload_builders import (
    _IDEMPOTENCY,
    _canonicalize,
    _manifest_entry,
    _policy,
)
from .baseline_models import BaselineDecisionRequest
from .types import (
    BaselineDecisionId,
    BaselineDecisionKind,
    BaselineDisposition,
    CheckRequestId,
)


def baseline_decision_payload(value: Any) -> bytes:
    return _canonicalize(
        value,
        fields=frozenset(
            {
                "decision_id",
                "definition_id",
                "definition_version_id",
                "check_request_id",
                "check_outcome_id",
                "kind",
                "disposition",
                "observation_model",
                "baseline_policy",
                "previous_decision_id",
                "entries",
                "item_keys_digest",
                "source_body_digest",
                "producer_slot_digest",
                "representation_digest",
                "validator_digest",
                "reason_codes",
                "decided_at",
            }
        ),
        name="Baseline Decision",
        build=lambda item: BaselineDecisionRequest(
            decision_id=BaselineDecisionId.parse(item["decision_id"]),
            definition_id=SourceDefinitionId.parse(item["definition_id"]),
            definition_version_id=SourceDefinitionVersionId.parse(
                item["definition_version_id"]
            ),
            check_request_id=CheckRequestId.parse(
                item["check_request_id"]
            ),
            check_outcome_id=CheckOutcomeId.parse(
                item["check_outcome_id"]
            ),
            kind=BaselineDecisionKind(item["kind"]),
            disposition=BaselineDisposition(item["disposition"]),
            observation_model=ObservationModel(item["observation_model"]),
            baseline_policy=_policy(
                item["baseline_policy"],
                field="baseline_policy",
            ),
            previous_decision_id=(
                None
                if item["previous_decision_id"] is None
                else BaselineDecisionId.parse(
                    item["previous_decision_id"]
                )
            ),
            entries=tuple(
                _manifest_entry(entry) for entry in item["entries"]
            ),
            source_body_digest=item["source_body_digest"],
            producer_slot_digest=item["producer_slot_digest"],
            representation_digest=item["representation_digest"],
            validator_digest=item["validator_digest"],
            reason_codes=tuple(item["reason_codes"]),
            decided_at=UtcTimestamp.parse(item["decided_at"]),
            idempotency_key=_IDEMPOTENCY,
        ),
    )


__all__ = ["baseline_decision_payload"]
