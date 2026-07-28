from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from newsroom.authority.canonical import validate_sha256_digest
from newsroom.authority.types import require_token
from newsroom.sources import SourceTime

from .baseline_models import AbsenceEndingGuard, AgendaMissGuard
from .types import (
    BaselineDecisionId,
    CheckContractError,
    ObservableTransitionKind,
    is_agenda_transition,
    is_ending_transition,
    sorted_unique_text,
)


class BaselineAction(StrEnum):
    """Caller intent for the source-specific baseline head.

    ``AUTO`` establishes the first baseline when none exists and otherwise
    leaves the retained head untouched. ``RESET`` and ``REBUILD`` are explicit
    later decisions and must name the exact retained predecessor. A manual
    hold remains an explicit decision rather than an implicit failure mode.
    """

    AUTO = "AUTO"
    RESET = "RESET"
    REBUILD = "REBUILD"
    MANUAL_HOLD = "MANUAL_HOLD"


@dataclass(frozen=True, slots=True)
class BaselineControl:
    action: BaselineAction = BaselineAction.AUTO
    previous_decision_id: BaselineDecisionId | None = None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.action, BaselineAction):
            raise CheckContractError("baseline control action must be typed")
        if self.previous_decision_id is not None and not isinstance(
            self.previous_decision_id,
            BaselineDecisionId,
        ):
            raise CheckContractError(
                "baseline control predecessor must be a typed Baseline Decision"
            )
        if self.action in {BaselineAction.RESET, BaselineAction.REBUILD}:
            if self.previous_decision_id is None:
                raise CheckContractError(
                    "baseline reset or rebuild requires exact predecessor identity"
                )
        elif self.action is BaselineAction.AUTO:
            if self.previous_decision_id is not None:
                raise CheckContractError(
                    "automatic baseline control cannot name a predecessor"
                )
        sorted_unique_text(
            self.reason_codes,
            field="baseline_control_reason_codes",
            maximum_items=16,
            maximum_item_bytes=128,
            allow_empty=True,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "previous_decision_id": (
                None
                if self.previous_decision_id is None
                else str(self.previous_decision_id)
            ),
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class TransitionDirective:
    """Version-bound deterministic transition classification input.

    The directive never creates source history by itself. Proposal admission
    resolves its item key to retained Source Item/Revision/Representation
    authority and then validates the directive against the declared source
    observation model and the exact Check Outcome.
    """

    item_key: str
    kind: ObservableTransitionKind
    transition_discriminator: str
    change_facets: tuple[str, ...] = ()
    related_item_key: str | None = None
    absence_guard: AbsenceEndingGuard | None = None
    agenda_guard: AgendaMissGuard | None = None
    source_asserted_time: SourceTime = field(default_factory=SourceTime.unknown)

    def __post_init__(self) -> None:
        validate_sha256_digest(self.item_key, field="transition_directive_item_key")
        if not isinstance(self.kind, ObservableTransitionKind):
            raise CheckContractError("transition directive kind must be typed")
        require_token(
            self.transition_discriminator,
            field="transition_directive_discriminator",
        )
        sorted_unique_text(
            self.change_facets,
            field="transition_directive_change_facets",
            maximum_items=64,
            maximum_item_bytes=128,
            allow_empty=True,
        )
        if self.related_item_key is not None:
            validate_sha256_digest(
                self.related_item_key,
                field="transition_directive_related_item_key",
            )
            if self.related_item_key == self.item_key:
                raise CheckContractError(
                    "transition directive related item must be distinct"
                )
        if self.kind is ObservableTransitionKind.REPLACED:
            if self.related_item_key is None:
                raise CheckContractError(
                    "replacement directive requires related item key"
                )
        elif self.related_item_key is not None:
            raise CheckContractError(
                "related item key is reserved for replacement directive"
            )
        if self.absence_guard is not None and not isinstance(
            self.absence_guard,
            AbsenceEndingGuard,
        ):
            raise CheckContractError("directive absence guard must be typed")
        if self.agenda_guard is not None and not isinstance(
            self.agenda_guard,
            AgendaMissGuard,
        ):
            raise CheckContractError("directive Agenda guard must be typed")
        if self.absence_guard is not None and self.agenda_guard is not None:
            raise CheckContractError(
                "one transition directive cannot carry both absence and Agenda guards"
            )
        if not isinstance(self.source_asserted_time, SourceTime):
            raise CheckContractError(
                "transition directive source-asserted time must be typed"
            )
        if self.kind is ObservableTransitionKind.AMBIGUOUS_ABSENCE:
            if (
                self.absence_guard is None
                or self.absence_guard.authorizes_ending
            ):
                raise CheckContractError(
                    "ambiguous absence directive requires non-authorizing guard"
                )
        elif self.absence_guard is not None and not is_ending_transition(self.kind):
            raise CheckContractError(
                "absence guard is valid only for ending or ambiguous absence"
            )
        if self.kind is ObservableTransitionKind.AGENDA_MISSED_EXPECTATION:
            if self.agenda_guard is None or not self.agenda_guard.authorizes_miss:
                raise CheckContractError(
                    "missed Agenda directive requires authorizing Agenda guard"
                )
        elif self.agenda_guard is not None:
            raise CheckContractError(
                "Agenda guard is reserved for missed-expectation directive"
            )
        if is_agenda_transition(self.kind) and self.absence_guard is not None:
            raise CheckContractError(
                "Agenda transition directive cannot use snapshot absence evidence"
            )
        if self.kind in {
            ObservableTransitionKind.REVISED,
            ObservableTransitionKind.ESCALATED,
            ObservableTransitionKind.DEESCALATED,
            ObservableTransitionKind.REPLACED,
            ObservableTransitionKind.REACTIVATED,
        } and not self.change_facets:
            raise CheckContractError(
                "state-changing transition directive requires change facets"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "item_key": self.item_key,
            "kind": self.kind.value,
            "transition_discriminator": self.transition_discriminator,
            "change_facets": list(self.change_facets),
            "related_item_key": self.related_item_key,
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
            "source_asserted_time": self.source_asserted_time.canonical_value(),
        }


__all__ = [
    "BaselineAction",
    "BaselineControl",
    "TransitionDirective",
]
