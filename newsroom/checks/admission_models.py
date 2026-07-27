from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
from typing import Any, TypeVar
from uuid import UUID

from newsroom.authority.canonical import canonical_json_bytes, digest_canonical
from newsroom.authority.types import UUIDv4Id, UtcTimestamp
from newsroom.discovery_adapters import (
    AdapterRequest,
    ObservationProposal,
    ObservationProposalOutcome,
    ParsedItem,
    QuarantineRecommendation,
)
from newsroom.sources import (
    CheckOutcomeId,
    DiscoveryOccurrence,
    DiscoveryRepresentation,
    SourceItem,
    SourceRevision,
)

from .check_models import (
    CandidateObservationRef,
    CheckOutcomeRequest,
)
from .record_models import (
    BaselineDecision,
    CheckOutcome,
    ObservableTransition,
    OperationalFinding,
    OperationalFindingOccurrence,
)
from .types import (
    CheckAttemptId,
    CheckAuthorityError,
    CheckContractError,
    CheckOutcomeKind,
    CheckRequestId,
    QuarantineDisposition,
)


_Id = TypeVar("_Id", bound=UUIDv4Id)


class ProposalAdmissionError(CheckAuthorityError):
    """An adapter proposal cannot be admitted into Check/source authority."""


class ProposalAdmissionConflict(ProposalAdmissionError):
    """Concurrent or retained authority conflicts with the proposed lineage."""


class AdmissionRecordState(StrEnum):
    CREATED = "CREATED"
    REUSED = "REUSED"
    REPLAYED = "REPLAYED"


def deterministic_uuid4(
    identifier_type: type[_Id],
    *,
    namespace: str,
    semantic_value: object,
) -> _Id:
    """Derive an opaque, domain-separated RFC UUIDv4 from retained semantics.

    The UUID remains a lifecycle identifier rather than a digest replacement.
    Digest equality and the authority store's semantic constraints remain the
    collision and idempotency authority.
    """

    if not isinstance(namespace, str) or not namespace:
        raise CheckContractError("deterministic identifier namespace is empty")
    payload = canonical_json_bytes(
        {
            "namespace": namespace,
            "semantic_value": semantic_value,
        }
    )
    raw = bytearray(hashlib.sha256(payload).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return identifier_type(UUID(bytes=bytes(raw)))


_OUTCOME_KIND: dict[ObservationProposalOutcome, CheckOutcomeKind] = {
    ObservationProposalOutcome.BLOCKED: CheckOutcomeKind.BLOCKED,
    ObservationProposalOutcome.SUCCESS_EMPTY: CheckOutcomeKind.SUCCESS_EMPTY,
    ObservationProposalOutcome.SUCCESS_UNCHANGED: (
        CheckOutcomeKind.SUCCESS_UNCHANGED
    ),
    ObservationProposalOutcome.SUCCESS_CHANGED: CheckOutcomeKind.SUCCESS_CHANGED,
    ObservationProposalOutcome.SUCCESS_PARTIAL: CheckOutcomeKind.SUCCESS_PARTIAL,
    ObservationProposalOutcome.SUCCESS_TRUNCATED: (
        CheckOutcomeKind.SUCCESS_TRUNCATED
    ),
    ObservationProposalOutcome.REDIRECTED: CheckOutcomeKind.REDIRECTED,
    ObservationProposalOutcome.RATE_LIMITED: CheckOutcomeKind.RATE_LIMITED,
    ObservationProposalOutcome.UNAUTHORISED: CheckOutcomeKind.UNAUTHORISED,
    ObservationProposalOutcome.NOT_FOUND: CheckOutcomeKind.NOT_FOUND,
    ObservationProposalOutcome.GONE: CheckOutcomeKind.GONE,
    ObservationProposalOutcome.MALFORMED: CheckOutcomeKind.MALFORMED,
    ObservationProposalOutcome.SHAPE_DRIFT: CheckOutcomeKind.SHAPE_DRIFT,
    ObservationProposalOutcome.TRANSPORT_FAILED: (
        CheckOutcomeKind.TRANSPORT_FAILED
    ),
}
_QUARANTINE: dict[QuarantineRecommendation, QuarantineDisposition] = {
    QuarantineRecommendation.NONE: QuarantineDisposition.NONE,
    QuarantineRecommendation.REVIEW: QuarantineDisposition.REVIEW,
    QuarantineRecommendation.QUARANTINE: QuarantineDisposition.QUARANTINE,
}


@dataclass(frozen=True, slots=True)
class ProposalAdmissionRequest:
    check_request_id: CheckRequestId
    check_attempt_id: CheckAttemptId
    adapter_request: AdapterRequest
    proposal: ObservationProposal

    def __post_init__(self) -> None:
        if not isinstance(self.check_request_id, CheckRequestId):
            raise CheckContractError("proposal admission Check Request must be typed")
        if not isinstance(self.check_attempt_id, CheckAttemptId):
            raise CheckContractError("proposal admission Check Attempt must be typed")
        if not isinstance(self.adapter_request, AdapterRequest):
            raise CheckContractError("proposal admission adapter request must be typed")
        if not isinstance(self.proposal, ObservationProposal):
            raise CheckContractError("proposal admission proposal must be typed")
        expected = (
            self.adapter_request.request_id,
            self.adapter_request.source_definition_id,
            self.adapter_request.source_definition_version_id,
        )
        actual = (
            self.proposal.request_id,
            self.proposal.source_definition_id,
            self.proposal.source_definition_version_id,
        )
        if actual != expected:
            raise CheckContractError(
                "proposal admission adapter and proposal lineage differ"
            )
        parser = self.proposal.parser_result
        if parser is not None and (
            parser.adapter != self.adapter_request.adapter
            or parser.shape_contract_digest
            != self.adapter_request.shape_contract.digest
            or parser.producer_slot_digest
            != self.adapter_request.producer_slot_digest
        ):
            raise CheckContractError(
                "proposal parser evidence differs from exact adapter request"
            )

    @property
    def outcome_id(self) -> CheckOutcomeId:
        return deterministic_uuid4(
            CheckOutcomeId,
            namespace="increment-3c-check-outcome-v1",
            semantic_value={
                "check_request_id": str(self.check_request_id),
                "check_attempt_id": str(self.check_attempt_id),
                "proposal_digest": self.proposal.digest,
            },
        )

    @property
    def semantic_digest(self) -> str:
        return digest_canonical(
            {
                "check_request_id": str(self.check_request_id),
                "check_attempt_id": str(self.check_attempt_id),
                "adapter_request_digest": self.adapter_request.digest,
                "proposal_digest": self.proposal.digest,
            }
        )

    @property
    def parsed_items(self) -> tuple[ParsedItem, ...]:
        if self.proposal.outcome in {
            ObservationProposalOutcome.SUCCESS_CHANGED,
            ObservationProposalOutcome.SUCCESS_PARTIAL,
            ObservationProposalOutcome.SUCCESS_TRUNCATED,
        }:
            return self.proposal.candidate_items
        if (
            self.proposal.outcome
            is ObservationProposalOutcome.SUCCESS_UNCHANGED
            and self.proposal.parser_result is not None
        ):
            return self.proposal.parser_result.items
        return ()

    @property
    def completed_at(self) -> UtcTimestamp:
        if self.proposal.parser_result is not None:
            return self.proposal.parser_result.produced_at
        if self.proposal.receipt is not None:
            return self.proposal.receipt.observed_at
        return self.adapter_request.requested_at

    @property
    def validator_digest(self) -> str | None:
        receipt = self.proposal.receipt
        if receipt is None:
            return None
        retained = {
            header.name: header.value
            for header in receipt.headers
            if header.name in {"etag", "last-modified"}
        }
        return None if not retained else digest_canonical(retained)

    def outcome_request(self) -> CheckOutcomeRequest:
        parser = self.proposal.parser_result
        return CheckOutcomeRequest(
            outcome_id=self.outcome_id,
            request_id=self.check_request_id,
            attempt_id=self.check_attempt_id,
            proposal_id=self.proposal.proposal_id,
            definition_id=self.proposal.source_definition_id,
            definition_version_id=self.proposal.source_definition_version_id,
            kind=_OUTCOME_KIND[self.proposal.outcome],
            reason_codes=self.proposal.reason_codes,
            quarantine=_QUARANTINE[self.proposal.quarantine],
            incomplete=self.proposal.incomplete,
            receipt_digest=(
                None
                if self.proposal.receipt is None
                else self.proposal.receipt.digest
            ),
            capture_digest=(
                None
                if self.proposal.capture is None
                else self.proposal.capture.digest
            ),
            parser_result_digest=(
                None if parser is None else parser.digest
            ),
            source_body_digest=(
                None if parser is None else parser.source_body_digest
            ),
            producer_slot_digest=(
                None if parser is None else parser.producer_slot_digest
            ),
            representation_digest=(
                None if parser is None else parser.representation_digest
            ),
            validator_digest=self.validator_digest,
            candidate_observations=tuple(
                CandidateObservationRef(item.item_key, item.digest)
                for item in self.proposal.candidate_items
            ),
            completed_at=self.completed_at,
            idempotency_key=f"proposal-outcome:{self.outcome_id}",
        )


@dataclass(frozen=True, slots=True)
class AdmittedSourceObservation:
    item_key: str
    item: SourceItem
    revision: SourceRevision
    representation: DiscoveryRepresentation | None
    occurrence: DiscoveryOccurrence
    item_state: AdmissionRecordState
    revision_state: AdmissionRecordState
    representation_state: AdmissionRecordState
    occurrence_state: AdmissionRecordState

    def __post_init__(self) -> None:
        if not isinstance(self.item_key, str) or not self.item_key.startswith(
            "sha256:"
        ):
            raise CheckContractError("admitted observation item key is invalid")
        if not isinstance(self.item, SourceItem):
            raise CheckContractError("admitted observation Source Item is invalid")
        if not isinstance(self.revision, SourceRevision):
            raise CheckContractError("admitted observation Source Revision is invalid")
        if self.representation is not None and not isinstance(
            self.representation,
            DiscoveryRepresentation,
        ):
            raise CheckContractError(
                "admitted observation Representation is invalid"
            )
        if not isinstance(self.occurrence, DiscoveryOccurrence):
            raise CheckContractError("admitted observation Occurrence is invalid")
        for state in (
            self.item_state,
            self.revision_state,
            self.representation_state,
            self.occurrence_state,
        ):
            if not isinstance(state, AdmissionRecordState):
                raise CheckContractError("admission record state must be typed")
        if self.revision.request.item_id != self.item.request.item_id:
            raise CheckContractError("admitted Revision belongs to another Item")
        if (
            self.representation is not None
            and self.representation.request.revision_id
            != self.revision.request.revision_id
        ):
            raise CheckContractError(
                "admitted Representation belongs to another Revision"
            )
        if self.occurrence.request.revision_id != self.revision.request.revision_id:
            raise CheckContractError(
                "admitted Occurrence belongs to another Revision"
            )

    def canonical_value(self) -> dict[str, Any]:
        return {
            "item_key": self.item_key,
            "item_id": str(self.item.request.item_id),
            "revision_id": str(self.revision.request.revision_id),
            "representation_id": (
                None
                if self.representation is None
                else str(self.representation.request.representation_id)
            ),
            "occurrence_id": str(self.occurrence.request.occurrence_id),
            "occurrence_kind": self.occurrence.request.kind.value,
            "item_state": self.item_state.value,
            "revision_state": self.revision_state.value,
            "representation_state": self.representation_state.value,
            "occurrence_state": self.occurrence_state.value,
        }


@dataclass(frozen=True, slots=True)
class ProposalAdmissionResult:
    request: ProposalAdmissionRequest
    outcome: CheckOutcome
    observations: tuple[AdmittedSourceObservation, ...]
    baseline: BaselineDecision | None = None
    transitions: tuple[ObservableTransition, ...] = ()
    findings: tuple[OperationalFinding, ...] = ()
    finding_occurrences: tuple[OperationalFindingOccurrence, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.request, ProposalAdmissionRequest):
            raise CheckContractError("proposal admission request is not retained")
        if not isinstance(self.outcome, CheckOutcome):
            raise CheckContractError("proposal admission Outcome is invalid")
        if self.outcome.request.outcome_id != self.request.outcome_id:
            raise CheckContractError("proposal admission Outcome identity differs")
        if not isinstance(self.observations, tuple) or any(
            not isinstance(item, AdmittedSourceObservation)
            for item in self.observations
        ):
            raise CheckContractError(
                "proposal admission observations must be a typed tuple"
            )
        if self.observations != tuple(
            sorted(self.observations, key=lambda item: item.item_key)
        ):
            raise CheckContractError(
                "proposal admission observations must be sorted"
            )
        if len(self.observations) != len(
            {item.item_key for item in self.observations}
        ):
            raise CheckContractError(
                "proposal admission item keys must be unique"
            )
        if any(
            item.occurrence.request.check_outcome_id
            != self.outcome.request.outcome_id
            for item in self.observations
        ):
            raise CheckContractError(
                "proposal admission Occurrence differs from Outcome"
            )
        if self.baseline is not None:
            if (
                not isinstance(self.baseline, BaselineDecision)
                or self.baseline.request.check_outcome_id
                != self.outcome.request.outcome_id
            ):
                raise CheckContractError(
                    "proposal admission baseline differs from Outcome"
                )
        if not isinstance(self.transitions, tuple) or any(
            not isinstance(item, ObservableTransition)
            for item in self.transitions
        ):
            raise CheckContractError(
                "proposal admission transitions must be a typed tuple"
            )
        if self.transitions != tuple(
            sorted(
                self.transitions,
                key=lambda item: str(item.request.transition_id),
            )
        ):
            raise CheckContractError(
                "proposal admission transitions must be sorted"
            )
        if any(
            item.request.check_outcome_id != self.outcome.request.outcome_id
            for item in self.transitions
        ):
            raise CheckContractError(
                "proposal admission transition differs from Outcome"
            )
        if not isinstance(self.findings, tuple) or any(
            not isinstance(item, OperationalFinding)
            for item in self.findings
        ):
            raise CheckContractError(
                "proposal admission Findings must be a typed tuple"
            )
        if not isinstance(self.finding_occurrences, tuple) or any(
            not isinstance(item, OperationalFindingOccurrence)
            for item in self.finding_occurrences
        ):
            raise CheckContractError(
                "proposal admission Finding occurrences must be typed"
            )
        if any(
            item.request.outcome_id != self.outcome.request.outcome_id
            for item in self.finding_occurrences
        ):
            raise CheckContractError(
                "proposal admission Finding occurrence differs from Outcome"
            )

    @property
    def replayed(self) -> bool:
        return self.outcome.replayed and all(
            observation.occurrence_state is not AdmissionRecordState.CREATED
            for observation in self.observations
        )

    def canonical_value(self) -> dict[str, Any]:
        return {
            "admission_semantic_digest": self.request.semantic_digest,
            "outcome_id": str(self.outcome.request.outcome_id),
            "outcome_kind": self.outcome.request.kind.value,
            "outcome_replayed": self.outcome.replayed,
            "observations": [
                item.canonical_value() for item in self.observations
            ],
            "baseline_id": (
                None
                if self.baseline is None
                else str(self.baseline.request.decision_id)
            ),
            "transition_ids": [
                str(item.request.transition_id)
                for item in self.transitions
            ],
            "finding_ids": [
                str(item.request.finding_id)
                for item in self.findings
            ],
            "finding_occurrence_ids": [
                str(item.request.occurrence_id)
                for item in self.finding_occurrences
            ],
        }


__all__ = [
    "AdmissionRecordState",
    "AdmittedSourceObservation",
    "ProposalAdmissionConflict",
    "ProposalAdmissionError",
    "ProposalAdmissionRequest",
    "ProposalAdmissionResult",
    "deterministic_uuid4",
]
