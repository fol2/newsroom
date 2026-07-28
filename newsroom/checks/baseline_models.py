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
    ObservationModel,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
    VersionedPolicyRef,
)

from ._model_common import (
    optional_digest,
    optional_uuid,
    require_idempotency_key,
    require_source_identity,
)
from .types import (
    BaselineDecisionId,
    BaselineDecisionKind,
    BaselineDisposition,
    BaselineEntryDisposition,
    CheckContractError,
    CheckRequestId,
    canonical_digest,
    positive_int,
    require_policy,
    sorted_unique_text,
)


@dataclass(frozen=True, slots=True)
class BaselineManifestEntry:
    item_key: str
    disposition: BaselineEntryDisposition
    reason_code: str
    item_id: SourceItemId | None = None
    revision_id: SourceRevisionId | None = None

    def __post_init__(self) -> None:
        canonical_digest(self.item_key, field="baseline_entry_item_key")
        if not isinstance(self.disposition, BaselineEntryDisposition):
            raise CheckContractError(
                "baseline entry disposition must be typed"
            )
        require_token(self.reason_code, field="baseline_entry_reason_code")
        optional_uuid(
            self.item_id,
            SourceItemId,
            field="baseline item identity",
        )
        optional_uuid(
            self.revision_id,
            SourceRevisionId,
            field="baseline revision identity",
        )
        if (self.item_id is None) != (self.revision_id is None):
            raise CheckContractError(
                "baseline item and revision identities move together"
            )
        if (
            self.disposition is BaselineEntryDisposition.INCLUDED
            and self.item_id is None
        ):
            raise CheckContractError(
                "included baseline entry requires retained item and revision"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "item_key": self.item_key,
            "disposition": self.disposition.value,
            "reason_code": self.reason_code,
            "item_id": None if self.item_id is None else str(self.item_id),
            "revision_id": (
                None if self.revision_id is None else str(self.revision_id)
            ),
        }


@dataclass(frozen=True, slots=True)
class ConfirmationOutcomeRef:
    outcome_id: CheckOutcomeId
    request_id: CheckRequestId
    adapter_request_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.outcome_id, CheckOutcomeId):
            raise CheckContractError(
                "confirmation Outcome identity must be typed"
            )
        if not isinstance(self.request_id, CheckRequestId):
            raise CheckContractError(
                "confirmation Request identity must be typed"
            )
        canonical_digest(
            self.adapter_request_digest,
            field="confirmation_adapter_request_digest",
        )

    def canonical_value(self) -> dict[str, str]:
        return {
            "outcome_id": str(self.outcome_id),
            "request_id": str(self.request_id),
            "adapter_request_digest": self.adapter_request_digest,
        }


def _validate_confirmation_outcomes(
    values: tuple[ConfirmationOutcomeRef, ...],
) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(item, ConfirmationOutcomeRef) for item in values
    ):
        raise CheckContractError(
            "confirmation Outcomes must be a typed immutable tuple"
        )
    expected = tuple(
        sorted(values, key=lambda item: str(item.outcome_id))
    )
    if values != expected:
        raise CheckContractError(
            "confirmation Outcomes must be sorted by Outcome identity"
        )
    if len(values) != len({item.outcome_id for item in values}):
        raise CheckContractError(
            "confirmation Outcome identities must be unique"
        )


@dataclass(frozen=True, slots=True)
class AbsenceEndingGuard:
    complete_scope_digest: str
    filter_contract_digest: str
    pagination_contract_digest: str
    successful_complete_outcome: bool
    identity_confirmed: bool
    scope_confirmed: bool
    pagination_complete: bool
    confirmation_outcomes: tuple[ConfirmationOutcomeRef, ...]
    required_confirmations: int
    grace_satisfied: bool
    no_alternative_explanation: bool

    def __post_init__(self) -> None:
        for field, value in (
            ("complete_scope_digest", self.complete_scope_digest),
            ("filter_contract_digest", self.filter_contract_digest),
            ("pagination_contract_digest", self.pagination_contract_digest),
        ):
            canonical_digest(value, field=field)
        for field, value in (
            ("successful_complete_outcome", self.successful_complete_outcome),
            ("identity_confirmed", self.identity_confirmed),
            ("scope_confirmed", self.scope_confirmed),
            ("pagination_complete", self.pagination_complete),
            ("grace_satisfied", self.grace_satisfied),
            (
                "no_alternative_explanation",
                self.no_alternative_explanation,
            ),
        ):
            if not isinstance(value, bool):
                raise CheckContractError(f"{field} must be boolean")
        _validate_confirmation_outcomes(self.confirmation_outcomes)
        positive_int(
            self.required_confirmations,
            field="absence_required_confirmations",
            maximum=1_000_000,
        )

    @property
    def confirmation_count(self) -> int:
        return len(self.confirmation_outcomes)

    @property
    def authorizes_ending(self) -> bool:
        return (
            self.successful_complete_outcome
            and self.identity_confirmed
            and self.scope_confirmed
            and self.pagination_complete
            and self.confirmation_count >= self.required_confirmations
            and self.grace_satisfied
            and self.no_alternative_explanation
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "complete_scope_digest": self.complete_scope_digest,
            "filter_contract_digest": self.filter_contract_digest,
            "pagination_contract_digest": self.pagination_contract_digest,
            "successful_complete_outcome": self.successful_complete_outcome,
            "identity_confirmed": self.identity_confirmed,
            "scope_confirmed": self.scope_confirmed,
            "pagination_complete": self.pagination_complete,
            "confirmation_outcomes": [
                item.canonical_value()
                for item in self.confirmation_outcomes
            ],
            "confirmation_count": self.confirmation_count,
            "required_confirmations": self.required_confirmations,
            "grace_satisfied": self.grace_satisfied,
            "no_alternative_explanation": (
                self.no_alternative_explanation
            ),
            "authorizes_ending": self.authorizes_ending,
        }


@dataclass(frozen=True, slots=True)
class AgendaMissGuard:
    expected_window_digest: str
    confirmation_paths_digest: str
    window_closed: bool
    grace_satisfied: bool
    confirmation_paths_checked: bool
    no_reschedule_or_cancellation: bool
    confirmation_outcomes: tuple[ConfirmationOutcomeRef, ...]
    required_confirmations: int
    confirmation_outcomes_complete: bool
    source_failure_absent: bool

    def __post_init__(self) -> None:
        canonical_digest(
            self.expected_window_digest,
            field="agenda_expected_window_digest",
        )
        canonical_digest(
            self.confirmation_paths_digest,
            field="agenda_confirmation_paths_digest",
        )
        _validate_confirmation_outcomes(self.confirmation_outcomes)
        positive_int(
            self.required_confirmations,
            field="agenda_required_confirmations",
            maximum=1_000_000,
        )
        for field, value in (
            ("window_closed", self.window_closed),
            ("grace_satisfied", self.grace_satisfied),
            (
                "confirmation_paths_checked",
                self.confirmation_paths_checked,
            ),
            (
                "no_reschedule_or_cancellation",
                self.no_reschedule_or_cancellation,
            ),
            (
                "confirmation_outcomes_complete",
                self.confirmation_outcomes_complete,
            ),
            ("source_failure_absent", self.source_failure_absent),
        ):
            if not isinstance(value, bool):
                raise CheckContractError(f"{field} must be boolean")

    @property
    def confirmation_count(self) -> int:
        return len(self.confirmation_outcomes)

    @property
    def authorizes_miss(self) -> bool:
        return (
            self.window_closed
            and self.grace_satisfied
            and self.confirmation_paths_checked
            and self.no_reschedule_or_cancellation
            and self.confirmation_outcomes_complete
            and self.confirmation_count >= self.required_confirmations
            and self.source_failure_absent
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "expected_window_digest": self.expected_window_digest,
            "confirmation_paths_digest": self.confirmation_paths_digest,
            "window_closed": self.window_closed,
            "grace_satisfied": self.grace_satisfied,
            "confirmation_paths_checked": self.confirmation_paths_checked,
            "no_reschedule_or_cancellation": (
                self.no_reschedule_or_cancellation
            ),
            "confirmation_outcomes": [
                item.canonical_value()
                for item in self.confirmation_outcomes
            ],
            "confirmation_count": self.confirmation_count,
            "required_confirmations": self.required_confirmations,
            "confirmation_outcomes_complete": (
                self.confirmation_outcomes_complete
            ),
            "source_failure_absent": self.source_failure_absent,
            "authorizes_miss": self.authorizes_miss,
        }


@dataclass(frozen=True, slots=True)
class BaselineDecisionRequest:
    decision_id: BaselineDecisionId
    definition_id: SourceDefinitionId
    definition_version_id: SourceDefinitionVersionId
    check_request_id: CheckRequestId
    check_outcome_id: CheckOutcomeId
    kind: BaselineDecisionKind
    disposition: BaselineDisposition
    observation_model: ObservationModel
    baseline_policy: VersionedPolicyRef
    previous_decision_id: BaselineDecisionId | None
    entries: tuple[BaselineManifestEntry, ...]
    source_body_digest: str | None
    producer_slot_digest: str | None
    representation_digest: str | None
    validator_digest: str | None
    reason_codes: tuple[str, ...]
    decided_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.decision_id, BaselineDecisionId):
            raise CheckContractError("baseline decision identity must be typed")
        require_source_identity(
            self.definition_id,
            self.definition_version_id,
            identity="baseline decision",
        )
        if not isinstance(self.check_request_id, CheckRequestId):
            raise CheckContractError("baseline Check Request must be typed")
        if not isinstance(self.check_outcome_id, CheckOutcomeId):
            raise CheckContractError("baseline Check Outcome must be typed")
        if not isinstance(self.kind, BaselineDecisionKind):
            raise CheckContractError("baseline decision kind must be typed")
        if not isinstance(self.disposition, BaselineDisposition):
            raise CheckContractError("baseline disposition must be typed")
        if not isinstance(self.observation_model, ObservationModel):
            raise CheckContractError("baseline observation model must be typed")
        require_policy(self.baseline_policy, field="baseline_policy")
        optional_uuid(
            self.previous_decision_id,
            BaselineDecisionId,
            field="previous baseline decision",
        )
        if self.previous_decision_id == self.decision_id:
            raise CheckContractError("baseline decision cannot precede itself")
        if self.kind is BaselineDecisionKind.ESTABLISH:
            if self.previous_decision_id is not None:
                raise CheckContractError(
                    "baseline establishment cannot name a predecessor"
                )
        elif self.previous_decision_id is None:
            raise CheckContractError(
                "baseline reset or rebuild requires its predecessor"
            )
        if (
            not isinstance(self.entries, tuple)
            or any(
                not isinstance(item, BaselineManifestEntry)
                for item in self.entries
            )
        ):
            raise CheckContractError(
                "baseline entries must be a typed immutable tuple"
            )
        expected = tuple(
            sorted(
                self.entries,
                key=lambda item: (
                    item.item_key,
                    item.disposition.value,
                ),
            )
        )
        if self.entries != expected:
            raise CheckContractError(
                "baseline entries must be canonically sorted"
            )
        if len(self.entries) != len({item.item_key for item in self.entries}):
            raise CheckContractError(
                "baseline item keys cannot repeat across the manifest"
            )
        for field, value in (
            ("baseline_source_body_digest", self.source_body_digest),
            ("baseline_producer_slot_digest", self.producer_slot_digest),
            (
                "baseline_representation_digest",
                self.representation_digest,
            ),
            ("baseline_validator_digest", self.validator_digest),
        ):
            optional_digest(value, field=field)
        parser_digests = (
            self.source_body_digest,
            self.producer_slot_digest,
            self.representation_digest,
        )
        if any(value is not None for value in parser_digests) and any(
            value is None for value in parser_digests
        ):
            raise CheckContractError(
                "baseline parser lineage digests move together"
            )
        sorted_unique_text(
            self.reason_codes,
            field="baseline_reason_codes",
            maximum_items=32,
            maximum_item_bytes=128,
        )
        self._validate_disposition()
        if not isinstance(self.decided_at, UtcTimestamp):
            raise CheckContractError("baseline decision time must be typed")
        require_idempotency_key(self.idempotency_key)

    def _validate_disposition(self) -> None:
        allowed = {
            ObservationModel.MUTABLE_ITEM: {
                BaselineDisposition.MAINTAINED_BASELINE_ONLY,
                BaselineDisposition.MANUAL_HOLD,
            },
            ObservationModel.APPEND_ONLY: {
                BaselineDisposition.BOUNDED_BACKFILL,
                BaselineDisposition.MANUAL_HOLD,
            },
            ObservationModel.ROLLING_LIST: {
                BaselineDisposition.BOUNDED_BACKFILL,
                BaselineDisposition.MANUAL_HOLD,
            },
            ObservationModel.COMPLETE_CURRENT_STATE: {
                BaselineDisposition.FIRST_OBSERVED_ACTIVE,
                BaselineDisposition.MANUAL_HOLD,
            },
            ObservationModel.PLANNED_AGENDA: {
                BaselineDisposition.FUTURE_EXPECTATIONS_ONLY,
                BaselineDisposition.MANUAL_HOLD,
            },
            ObservationModel.EXPLICIT_DELTA: {
                BaselineDisposition.EXPLICIT_DELTA_SEQUENCE,
                BaselineDisposition.MANUAL_HOLD,
            },
        }
        if self.disposition not in allowed[self.observation_model]:
            raise CheckContractError(
                "baseline disposition is incompatible with observation model"
            )
        if self.disposition is BaselineDisposition.MANUAL_HOLD:
            return
        if self.disposition is BaselineDisposition.MAINTAINED_BASELINE_ONLY:
            if len(self.entries) != 1:
                raise CheckContractError(
                    "maintained baseline requires one logical item"
                )

    @property
    def item_keys_digest(self) -> str:
        return digest_canonical(
            [item.item_key for item in self.entries]
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "decision_id": str(self.decision_id),
            "definition_id": str(self.definition_id),
            "definition_version_id": str(self.definition_version_id),
            "check_request_id": str(self.check_request_id),
            "check_outcome_id": str(self.check_outcome_id),
            "kind": self.kind.value,
            "disposition": self.disposition.value,
            "observation_model": self.observation_model.value,
            "baseline_policy": self.baseline_policy.canonical_value(),
            "previous_decision_id": (
                None
                if self.previous_decision_id is None
                else str(self.previous_decision_id)
            ),
            "entries": [item.canonical_value() for item in self.entries],
            "item_keys_digest": self.item_keys_digest,
            "source_body_digest": self.source_body_digest,
            "producer_slot_digest": self.producer_slot_digest,
            "representation_digest": self.representation_digest,
            "validator_digest": self.validator_digest,
            "reason_codes": list(self.reason_codes),
            "decided_at": self.decided_at.to_text(),
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
        value.pop("decision_id")
        value.pop("decided_at")
        return digest_canonical(value)


__all__ = [
    "AbsenceEndingGuard",
    "AgendaMissGuard",
    "BaselineDecisionRequest",
    "BaselineManifestEntry",
    "ConfirmationOutcomeRef",
]
