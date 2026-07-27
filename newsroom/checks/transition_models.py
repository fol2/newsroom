from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.authority.types import UtcTimestamp, require_token
from newsroom.sources import (
    CheckOutcomeId,
    DiscoveryRepresentationId,
    ObservationModel,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
    SourceTime,
    VersionedPolicyRef,
)

from ._model_common import (
    optional_uuid,
    require_idempotency_key,
    require_source_identity,
)
from .baseline_models import AbsenceEndingGuard, AgendaMissGuard
from .types import (
    CheckContractError,
    ObservableTransitionId,
    ObservableTransitionKind,
    TransitionBasis,
    is_agenda_transition,
    is_ending_transition,
    require_policy,
    sorted_unique_text,
)


@dataclass(frozen=True, slots=True)
class ObservableTransitionRequest:
    transition_id: ObservableTransitionId
    definition_id: SourceDefinitionId
    definition_version_id: SourceDefinitionVersionId
    check_outcome_id: CheckOutcomeId
    item_id: SourceItemId
    kind: ObservableTransitionKind
    basis: TransitionBasis
    observation_model: ObservationModel
    prior_revision_id: SourceRevisionId | None
    current_revision_id: SourceRevisionId | None
    representation_id: DiscoveryRepresentationId | None
    related_item_id: SourceItemId | None
    change_facets: tuple[str, ...]
    transition_policy: VersionedPolicyRef
    absence_guard: AbsenceEndingGuard | None
    agenda_guard: AgendaMissGuard | None
    source_asserted_time: SourceTime
    observed_at: UtcTimestamp
    transition_discriminator: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.transition_id, ObservableTransitionId):
            raise CheckContractError(
                "observable transition identity must be typed"
            )
        require_source_identity(
            self.definition_id,
            self.definition_version_id,
            identity="observable transition",
        )
        if not isinstance(self.check_outcome_id, CheckOutcomeId):
            raise CheckContractError("transition Check Outcome must be typed")
        if not isinstance(self.item_id, SourceItemId):
            raise CheckContractError("transition Source Item must be typed")
        if not isinstance(self.kind, ObservableTransitionKind):
            raise CheckContractError("observable transition kind must be typed")
        if not isinstance(self.basis, TransitionBasis):
            raise CheckContractError("transition basis must be typed")
        if not isinstance(self.observation_model, ObservationModel):
            raise CheckContractError(
                "transition observation model must be typed"
            )
        optional_uuid(
            self.prior_revision_id,
            SourceRevisionId,
            field="prior transition revision",
        )
        optional_uuid(
            self.current_revision_id,
            SourceRevisionId,
            field="current transition revision",
        )
        optional_uuid(
            self.representation_id,
            DiscoveryRepresentationId,
            field="transition representation",
        )
        optional_uuid(
            self.related_item_id,
            SourceItemId,
            field="related transition item",
        )
        sorted_unique_text(
            self.change_facets,
            field="transition_change_facets",
            maximum_items=64,
            maximum_item_bytes=128,
            allow_empty=True,
        )
        require_policy(self.transition_policy, field="transition_policy")
        if self.absence_guard is not None and not isinstance(
            self.absence_guard, AbsenceEndingGuard
        ):
            raise CheckContractError("absence guard must be typed")
        if self.agenda_guard is not None and not isinstance(
            self.agenda_guard, AgendaMissGuard
        ):
            raise CheckContractError("agenda miss guard must be typed")
        if not isinstance(self.source_asserted_time, SourceTime):
            raise CheckContractError(
                "source-asserted transition time must be typed"
            )
        if not isinstance(self.observed_at, UtcTimestamp):
            raise CheckContractError("transition observation time must be typed")
        require_token(
            self.transition_discriminator,
            field="transition_discriminator",
        )
        require_idempotency_key(self.idempotency_key)
        self._validate_transition_shape()

    def _require_revision_pair(
        self,
        *,
        may_be_same: bool = False,
    ) -> None:
        if (
            self.prior_revision_id is None
            or self.current_revision_id is None
        ):
            raise CheckContractError(
                "transition requires exact prior and current Revisions"
            )
        if (
            not may_be_same
            and self.prior_revision_id == self.current_revision_id
        ):
            raise CheckContractError(
                "source-state transition requires distinct Revisions"
            )

    def _validate_transition_shape(self) -> None:
        if is_agenda_transition(self.kind):
            if (
                self.observation_model is not ObservationModel.PLANNED_AGENDA
                or self.basis is not TransitionBasis.AGENDA_EXPECTATION
            ):
                raise CheckContractError(
                    "Agenda transition requires Planned Agenda evidence"
                )
        elif self.agenda_guard is not None:
            raise CheckContractError(
                "non-Agenda transition cannot carry an Agenda miss guard"
            )

        if self.kind in {
            ObservableTransitionKind.FIRST_OBSERVED,
            ObservableTransitionKind.ACTIVATED,
            ObservableTransitionKind.AGENDA_CREATED,
        }:
            if (
                self.prior_revision_id is not None
                or self.current_revision_id is None
            ):
                raise CheckContractError(
                    "first or activation transition requires only current Revision"
                )
        elif self.kind is ObservableTransitionKind.REOBSERVED:
            self._require_revision_pair(may_be_same=True)
            if self.prior_revision_id != self.current_revision_id:
                raise CheckContractError(
                    "re-observation must retain the same Source Revision"
                )
        elif self.kind is ObservableTransitionKind.AMBIGUOUS_ABSENCE:
            if (
                self.prior_revision_id is None
                or self.current_revision_id is not None
                or self.basis
                is not TransitionBasis.COMPLETE_SNAPSHOT_ABSENCE
                or self.absence_guard is None
                or self.absence_guard.authorizes_ending
            ):
                raise CheckContractError(
                    "ambiguous absence requires incomplete ending evidence"
                )
        elif (
            self.kind is ObservableTransitionKind.AGENDA_MISSED_EXPECTATION
        ):
            if (
                self.prior_revision_id is None
                or self.current_revision_id is not None
                or self.agenda_guard is None
                or not self.agenda_guard.authorizes_miss
            ):
                raise CheckContractError(
                    "missed Agenda expectation requires exact complete guard"
                )
        elif is_ending_transition(self.kind):
            if self.basis is TransitionBasis.COMPLETE_SNAPSHOT_ABSENCE:
                if (
                    self.observation_model
                    is not ObservationModel.COMPLETE_CURRENT_STATE
                    or self.prior_revision_id is None
                    or self.current_revision_id is not None
                    or self.absence_guard is None
                    or not self.absence_guard.authorizes_ending
                ):
                    raise CheckContractError(
                        "absence-based ending lacks complete snapshot guard"
                    )
            else:
                self._require_revision_pair()
                if self.absence_guard is not None:
                    raise CheckContractError(
                        "explicit ending cannot carry an absence guard"
                    )
        else:
            self._require_revision_pair()

        if (
            self.basis is TransitionBasis.COMPLETE_SNAPSHOT_ABSENCE
            and self.absence_guard is None
        ):
            raise CheckContractError(
                "complete-snapshot absence basis requires its guard"
            )
        if (
            self.basis is not TransitionBasis.COMPLETE_SNAPSHOT_ABSENCE
            and self.absence_guard is not None
        ):
            raise CheckContractError(
                "absence guard is valid only for snapshot absence"
            )
        if self.kind is ObservableTransitionKind.REPLACED:
            if (
                self.related_item_id is None
                or self.related_item_id == self.item_id
            ):
                raise CheckContractError(
                    "replacement transition requires a separate related item"
                )
        elif self.related_item_id is not None:
            raise CheckContractError(
                "related item is reserved for replacement transition"
            )
        if self.kind in {
            ObservableTransitionKind.REVISED,
            ObservableTransitionKind.ESCALATED,
            ObservableTransitionKind.DEESCALATED,
            ObservableTransitionKind.REPLACED,
            ObservableTransitionKind.REACTIVATED,
        } and not self.change_facets:
            raise CheckContractError(
                "state-changing transition requires change facets"
            )
        if (
            self.representation_id is None
            and self.current_revision_id is not None
        ):
            raise CheckContractError(
                "current Revision transition requires Representation"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "transition_id": str(self.transition_id),
            "definition_id": str(self.definition_id),
            "definition_version_id": str(self.definition_version_id),
            "check_outcome_id": str(self.check_outcome_id),
            "item_id": str(self.item_id),
            "kind": self.kind.value,
            "basis": self.basis.value,
            "observation_model": self.observation_model.value,
            "prior_revision_id": (
                None
                if self.prior_revision_id is None
                else str(self.prior_revision_id)
            ),
            "current_revision_id": (
                None
                if self.current_revision_id is None
                else str(self.current_revision_id)
            ),
            "representation_id": (
                None
                if self.representation_id is None
                else str(self.representation_id)
            ),
            "related_item_id": (
                None
                if self.related_item_id is None
                else str(self.related_item_id)
            ),
            "change_facets": list(self.change_facets),
            "transition_policy": self.transition_policy.canonical_value(),
            "absence_guard": (
                None
                if self.absence_guard is None
                else self.absence_guard.canonical_value()
            ),
            "agenda_guard": (
                None
                if self.agenda_guard is None
                else self.agenda_guard.canonical_value()
            ),
            "source_asserted_time": (
                self.source_asserted_time.canonical_value()
            ),
            "observed_at": self.observed_at.to_text(),
            "transition_discriminator": self.transition_discriminator,
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
        value.pop("transition_id")
        value.pop("observed_at")
        return digest_canonical(value)


__all__ = ["ObservableTransitionRequest"]
