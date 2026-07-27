from __future__ import annotations

from typing import Any

from newsroom.authority.types import UtcTimestamp
from newsroom.sources import (
    CheckOutcomeId,
    DiscoveryRepresentationId,
    ObservationModel,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
)

from ._payload_builders import (
    _IDEMPOTENCY,
    _absence_guard,
    _agenda_guard,
    _canonicalize,
    _policy,
    _source_time,
)
from .transition_models import ObservableTransitionRequest
from .types import (
    ObservableTransitionId,
    ObservableTransitionKind,
    TransitionBasis,
)


def observable_transition_payload(value: Any) -> bytes:
    return _canonicalize(
        value,
        fields=frozenset(
            {
                "transition_id",
                "definition_id",
                "definition_version_id",
                "check_outcome_id",
                "item_id",
                "kind",
                "basis",
                "observation_model",
                "prior_revision_id",
                "current_revision_id",
                "representation_id",
                "related_item_id",
                "change_facets",
                "transition_policy",
                "absence_guard",
                "agenda_guard",
                "source_asserted_time",
                "observed_at",
                "transition_discriminator",
            }
        ),
        name="Observable Transition",
        build=lambda item: ObservableTransitionRequest(
            transition_id=ObservableTransitionId.parse(
                item["transition_id"]
            ),
            definition_id=SourceDefinitionId.parse(item["definition_id"]),
            definition_version_id=SourceDefinitionVersionId.parse(
                item["definition_version_id"]
            ),
            check_outcome_id=CheckOutcomeId.parse(
                item["check_outcome_id"]
            ),
            item_id=SourceItemId.parse(item["item_id"]),
            kind=ObservableTransitionKind(item["kind"]),
            basis=TransitionBasis(item["basis"]),
            observation_model=ObservationModel(item["observation_model"]),
            prior_revision_id=(
                None
                if item["prior_revision_id"] is None
                else SourceRevisionId.parse(item["prior_revision_id"])
            ),
            current_revision_id=(
                None
                if item["current_revision_id"] is None
                else SourceRevisionId.parse(item["current_revision_id"])
            ),
            representation_id=(
                None
                if item["representation_id"] is None
                else DiscoveryRepresentationId.parse(
                    item["representation_id"]
                )
            ),
            related_item_id=(
                None
                if item["related_item_id"] is None
                else SourceItemId.parse(item["related_item_id"])
            ),
            change_facets=tuple(item["change_facets"]),
            transition_policy=_policy(
                item["transition_policy"],
                field="transition_policy",
            ),
            absence_guard=(
                None
                if item["absence_guard"] is None
                else _absence_guard(item["absence_guard"])
            ),
            agenda_guard=(
                None
                if item["agenda_guard"] is None
                else _agenda_guard(item["agenda_guard"])
            ),
            source_asserted_time=_source_time(
                item["source_asserted_time"]
            ),
            observed_at=UtcTimestamp.parse(item["observed_at"]),
            transition_discriminator=item["transition_discriminator"],
            idempotency_key=_IDEMPOTENCY,
        ),
    )


__all__ = ["observable_transition_payload"]
