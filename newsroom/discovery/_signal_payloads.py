from __future__ import annotations

from typing import Any

from newsroom.authority.types import UtcTimestamp
from newsroom.checks import CheckOutcomeId, ObservableTransitionId, OperationalFindingId
from newsroom.sources import (
    DiscoveryOccurrenceId,
    DiscoveryRepresentationId,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
)

from ._payload_builders import _IDEMPOTENCY, _canonicalize, _policy
from .models import DiscoverySignalRequest
from .types import DiscoverySignalId


def discovery_signal_payload(value: Any) -> bytes:
    return _canonicalize(
        value,
        fields=frozenset(
            {
                "signal_id",
                "definition_id",
                "definition_version_id",
                "item_id",
                "revision_id",
                "representation_id",
                "check_outcome_id",
                "occurrence_id",
                "transition_id",
                "purpose",
                "discriminator",
                "admission_policy",
                "incomplete",
                "operational_finding_ids",
                "admitted_at",
            }
        ),
        name="Discovery Signal",
        build=lambda item: DiscoverySignalRequest(
            signal_id=DiscoverySignalId.parse(item["signal_id"]),
            definition_id=SourceDefinitionId.parse(item["definition_id"]),
            definition_version_id=SourceDefinitionVersionId.parse(
                item["definition_version_id"]
            ),
            item_id=SourceItemId.parse(item["item_id"]),
            revision_id=SourceRevisionId.parse(item["revision_id"]),
            representation_id=DiscoveryRepresentationId.parse(
                item["representation_id"]
            ),
            check_outcome_id=CheckOutcomeId.parse(item["check_outcome_id"]),
            occurrence_id=DiscoveryOccurrenceId.parse(item["occurrence_id"]),
            transition_id=ObservableTransitionId.parse(item["transition_id"]),
            purpose=item["purpose"],
            discriminator=item["discriminator"],
            admission_policy=_policy(
                item["admission_policy"],
                field="signal_admission_policy",
            ),
            incomplete=item["incomplete"],
            operational_finding_ids=tuple(
                OperationalFindingId.parse(value)
                for value in item["operational_finding_ids"]
            ),
            admitted_at=UtcTimestamp.parse(item["admitted_at"]),
            idempotency_key=_IDEMPOTENCY,
        ),
    )


__all__ = ["discovery_signal_payload"]
