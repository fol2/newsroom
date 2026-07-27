from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.authority.types import UtcTimestamp, require_token
from newsroom.discovery_adapters import AdapterRequestId, ObservationProposalId
from newsroom.sources import (
    CheckOutcomeId,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    VersionedPolicyRef,
)

from ._model_common import (
    optional_digest,
    optional_uuid,
    require_idempotency_key,
    require_source_identity,
)
from .types import (
    CheckAttemptId,
    CheckAttemptKind,
    CheckContractError,
    CheckOutcomeKind,
    CheckRequestId,
    CoverageBasis,
    QuarantineDisposition,
    TriggerRef,
    bounded_text,
    canonical_digest,
    is_candidate_outcome,
    outcome_requires_incomplete,
    positive_int,
    require_policy,
    require_uuid_text,
    sorted_unique_text,
)


@dataclass(frozen=True, slots=True)
class CandidateObservationRef:
    item_key: str
    item_digest: str

    def __post_init__(self) -> None:
        canonical_digest(self.item_key, field="candidate_item_key")
        canonical_digest(self.item_digest, field="candidate_item_digest")

    def canonical_value(self) -> dict[str, str]:
        return {
            "item_key": self.item_key,
            "item_digest": self.item_digest,
        }


@dataclass(frozen=True, slots=True)
class CheckRequestRequest:
    request_id: CheckRequestId
    definition_id: SourceDefinitionId
    definition_version_id: SourceDefinitionVersionId
    trigger: TriggerRef
    coverage: CoverageBasis
    rights_decision_id: str
    rights_policy_version: str
    adapter_request_digest: str
    producer_slot_digest: str
    baseline_policy: VersionedPolicyRef
    revision_policy: VersionedPolicyRef
    transition_policy: VersionedPolicyRef
    validator_policy: VersionedPolicyRef
    purpose: str
    requested_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, CheckRequestId):
            raise CheckContractError("check request identity must be typed")
        require_source_identity(
            self.definition_id,
            self.definition_version_id,
            identity="check request",
        )
        if not isinstance(self.trigger, TriggerRef):
            raise CheckContractError("check trigger must be typed")
        if not isinstance(self.coverage, CoverageBasis):
            raise CheckContractError("check coverage basis must be typed")
        require_uuid_text(
            self.rights_decision_id,
            field="check_rights_decision_id",
        )
        require_token(
            self.rights_policy_version,
            field="check_rights_policy_version",
        )
        canonical_digest(
            self.adapter_request_digest,
            field="check_adapter_request_digest",
        )
        canonical_digest(
            self.producer_slot_digest,
            field="check_producer_slot_digest",
        )
        for field, value in (
            ("baseline_policy", self.baseline_policy),
            ("revision_policy", self.revision_policy),
            ("transition_policy", self.transition_policy),
            ("validator_policy", self.validator_policy),
        ):
            require_policy(value, field=field)
        bounded_text(
            self.purpose,
            field="check_request_purpose",
            maximum_bytes=2048,
        )
        if not isinstance(self.requested_at, UtcTimestamp):
            raise CheckContractError("check request time must be typed")
        require_idempotency_key(self.idempotency_key)

    def canonical_value(self) -> dict[str, object]:
        return {
            "request_id": str(self.request_id),
            "definition_id": str(self.definition_id),
            "definition_version_id": str(self.definition_version_id),
            "trigger": self.trigger.canonical_value(),
            "coverage": self.coverage.canonical_value(),
            "rights_decision_id": self.rights_decision_id,
            "rights_policy_version": self.rights_policy_version,
            "adapter_request_digest": self.adapter_request_digest,
            "producer_slot_digest": self.producer_slot_digest,
            "baseline_policy": self.baseline_policy.canonical_value(),
            "revision_policy": self.revision_policy.canonical_value(),
            "transition_policy": self.transition_policy.canonical_value(),
            "validator_policy": self.validator_policy.canonical_value(),
            "purpose": self.purpose,
            "requested_at": self.requested_at.to_text(),
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
        value.pop("request_id")
        value.pop("requested_at")
        return digest_canonical(value)


@dataclass(frozen=True, slots=True)
class CheckAttemptRequest:
    attempt_id: CheckAttemptId
    request_id: CheckRequestId
    attempt_number: int
    kind: CheckAttemptKind
    prior_attempt_id: CheckAttemptId | None
    adapter_request_id: AdapterRequestId
    adapter_request_digest: str
    started_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.attempt_id, CheckAttemptId):
            raise CheckContractError("check attempt identity must be typed")
        if not isinstance(self.request_id, CheckRequestId):
            raise CheckContractError("check attempt request must be typed")
        positive_int(
            self.attempt_number,
            field="check_attempt_number",
            maximum=1_000_000,
        )
        if not isinstance(self.kind, CheckAttemptKind):
            raise CheckContractError("check attempt kind must be typed")
        optional_uuid(
            self.prior_attempt_id,
            CheckAttemptId,
            field="prior check attempt identity",
        )
        if self.attempt_number == 1:
            if (
                self.prior_attempt_id is not None
                or self.kind is not CheckAttemptKind.PRIMARY
            ):
                raise CheckContractError(
                    "first check attempt must be primary without predecessor"
                )
        elif self.prior_attempt_id is None:
            raise CheckContractError(
                "later check attempt requires its exact predecessor"
            )
        if self.prior_attempt_id == self.attempt_id:
            raise CheckContractError("check attempt cannot precede itself")
        if not isinstance(self.adapter_request_id, AdapterRequestId):
            raise CheckContractError("adapter request identity must be typed")
        canonical_digest(
            self.adapter_request_digest,
            field="attempt_adapter_request_digest",
        )
        if not isinstance(self.started_at, UtcTimestamp):
            raise CheckContractError("check attempt start time must be typed")
        require_idempotency_key(self.idempotency_key)

    def canonical_value(self) -> dict[str, object]:
        return {
            "attempt_id": str(self.attempt_id),
            "request_id": str(self.request_id),
            "attempt_number": self.attempt_number,
            "kind": self.kind.value,
            "prior_attempt_id": (
                None
                if self.prior_attempt_id is None
                else str(self.prior_attempt_id)
            ),
            "adapter_request_id": str(self.adapter_request_id),
            "adapter_request_digest": self.adapter_request_digest,
            "started_at": self.started_at.to_text(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        return digest_canonical(
            {
                "request_id": str(self.request_id),
                "attempt_number": self.attempt_number,
                "adapter_request_id": str(self.adapter_request_id),
                "adapter_request_digest": self.adapter_request_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class CheckOutcomeRequest:
    outcome_id: CheckOutcomeId
    request_id: CheckRequestId
    attempt_id: CheckAttemptId
    proposal_id: ObservationProposalId
    definition_id: SourceDefinitionId
    definition_version_id: SourceDefinitionVersionId
    kind: CheckOutcomeKind
    reason_codes: tuple[str, ...]
    quarantine: QuarantineDisposition
    incomplete: bool
    receipt_digest: str | None
    capture_digest: str | None
    parser_result_digest: str | None
    source_body_digest: str | None
    producer_slot_digest: str | None
    representation_digest: str | None
    validator_digest: str | None
    candidate_observations: tuple[CandidateObservationRef, ...]
    completed_at: UtcTimestamp
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.outcome_id, CheckOutcomeId):
            raise CheckContractError("check outcome identity must be typed")
        if not isinstance(self.request_id, CheckRequestId):
            raise CheckContractError("check outcome request must be typed")
        if not isinstance(self.attempt_id, CheckAttemptId):
            raise CheckContractError("check outcome attempt must be typed")
        if not isinstance(self.proposal_id, ObservationProposalId):
            raise CheckContractError(
                "observation proposal identity must be typed"
            )
        require_source_identity(
            self.definition_id,
            self.definition_version_id,
            identity="check outcome",
        )
        if not isinstance(self.kind, CheckOutcomeKind):
            raise CheckContractError("check outcome kind must be typed")
        sorted_unique_text(
            self.reason_codes,
            field="check_outcome_reason_codes",
            maximum_items=64,
            maximum_item_bytes=128,
        )
        if not isinstance(self.quarantine, QuarantineDisposition):
            raise CheckContractError(
                "check outcome quarantine disposition must be typed"
            )
        if not isinstance(self.incomplete, bool):
            raise CheckContractError(
                "check outcome incomplete flag must be boolean"
            )
        for field, value in (
            ("outcome_receipt_digest", self.receipt_digest),
            ("outcome_capture_digest", self.capture_digest),
            ("outcome_parser_result_digest", self.parser_result_digest),
            ("outcome_source_body_digest", self.source_body_digest),
            ("outcome_producer_slot_digest", self.producer_slot_digest),
            ("outcome_representation_digest", self.representation_digest),
            ("outcome_validator_digest", self.validator_digest),
        ):
            optional_digest(value, field=field)
        if (
            not isinstance(self.candidate_observations, tuple)
            or any(
                not isinstance(item, CandidateObservationRef)
                for item in self.candidate_observations
            )
        ):
            raise CheckContractError(
                "candidate observations must be a typed immutable tuple"
            )
        if self.candidate_observations != tuple(
            sorted(
                self.candidate_observations,
                key=lambda item: item.item_key,
            )
        ):
            raise CheckContractError(
                "candidate observations must be sorted by item key"
            )
        if len(self.candidate_observations) != len(
            {item.item_key for item in self.candidate_observations}
        ):
            raise CheckContractError("candidate item keys must be unique")
        self._validate_outcome_shape()
        if not isinstance(self.completed_at, UtcTimestamp):
            raise CheckContractError(
                "check outcome completion time must be typed"
            )
        require_idempotency_key(self.idempotency_key)

    def _validate_outcome_shape(self) -> None:
        candidates = bool(self.candidate_observations)
        if is_candidate_outcome(self.kind) != candidates:
            raise CheckContractError(
                "check outcome candidate set differs from outcome kind"
            )
        if outcome_requires_incomplete(self.kind) != self.incomplete:
            raise CheckContractError(
                "check outcome incompleteness differs from outcome kind"
            )
        if self.capture_digest is not None and self.receipt_digest is None:
            raise CheckContractError(
                "outcome Capture requires a transport receipt"
            )
        if (
            self.parser_result_digest is not None
            and self.capture_digest is None
        ):
            raise CheckContractError(
                "outcome Parser Result requires a Capture"
            )
        parser_components = (
            self.source_body_digest,
            self.producer_slot_digest,
            self.representation_digest,
        )
        if any(value is not None for value in parser_components):
            if (
                self.parser_result_digest is None
                or any(value is None for value in parser_components)
            ):
                raise CheckContractError(
                    "parser lineage digests move together"
                )
        if is_candidate_outcome(self.kind) and self.parser_result_digest is None:
            raise CheckContractError(
                "candidate outcome requires exact parser-result evidence"
            )
        if self.kind in {
            CheckOutcomeKind.MALFORMED,
            CheckOutcomeKind.SHAPE_DRIFT,
        } and self.parser_result_digest is None:
            raise CheckContractError(
                "parser failure outcome requires parser-result evidence"
            )
        if self.kind is CheckOutcomeKind.BLOCKED and any(
            value is not None
            for value in (
                self.receipt_digest,
                self.capture_digest,
                self.parser_result_digest,
            )
        ):
            raise CheckContractError(
                "preflight-blocked outcome cannot retain transport evidence"
            )
        if (
            self.quarantine is QuarantineDisposition.NONE
            and self.kind
            in {
                CheckOutcomeKind.SHAPE_DRIFT,
                CheckOutcomeKind.QUARANTINED_DISABLED,
            }
        ):
            raise CheckContractError(
                "integrity or disabled outcome needs quarantine review"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "outcome_id": str(self.outcome_id),
            "request_id": str(self.request_id),
            "attempt_id": str(self.attempt_id),
            "proposal_id": str(self.proposal_id),
            "definition_id": str(self.definition_id),
            "definition_version_id": str(self.definition_version_id),
            "kind": self.kind.value,
            "reason_codes": list(self.reason_codes),
            "quarantine": self.quarantine.value,
            "incomplete": self.incomplete,
            "receipt_digest": self.receipt_digest,
            "capture_digest": self.capture_digest,
            "parser_result_digest": self.parser_result_digest,
            "source_body_digest": self.source_body_digest,
            "producer_slot_digest": self.producer_slot_digest,
            "representation_digest": self.representation_digest,
            "validator_digest": self.validator_digest,
            "candidate_observations": [
                item.canonical_value()
                for item in self.candidate_observations
            ],
            "completed_at": self.completed_at.to_text(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        return digest_canonical(
            {
                "attempt_id": str(self.attempt_id),
                "proposal_id": str(self.proposal_id),
                "kind": self.kind.value,
                "receipt_digest": self.receipt_digest,
                "capture_digest": self.capture_digest,
                "parser_result_digest": self.parser_result_digest,
                "candidate_observations": [
                    item.canonical_value()
                    for item in self.candidate_observations
                ],
            }
        )


__all__ = [
    "CandidateObservationRef",
    "CheckAttemptRequest",
    "CheckOutcomeRequest",
    "CheckRequestRequest",
]
