from __future__ import annotations

from dataclasses import replace

from newsroom.authority.types import UtcTimestamp
from newsroom.checks import (
    AbsenceEndingGuard,
    AgendaMissGuard,
    BaselineDecisionId,
    BaselineDecisionKind,
    BaselineDecisionRequest,
    BaselineDisposition,
    BaselineEntryDisposition,
    BaselineManifestEntry,
    CandidateObservationRef,
    CheckAttemptId,
    CheckAttemptKind,
    CheckAttemptRequest,
    CheckOutcomeId,
    CheckOutcomeKind,
    CheckOutcomeRequest,
    CheckRequestId,
    CheckRequestRequest,
    CoverageBasis,
    FindingCategory,
    FindingScopeKind,
    FindingSeverity,
    ObservableTransitionId,
    ObservableTransitionKind,
    ObservableTransitionRequest,
    OperationalFindingId,
    OperationalFindingOccurrenceId,
    OperationalFindingOccurrenceRequest,
    OperationalFindingRequest,
    QuarantineDisposition,
    TransitionBasis,
    TriggerKind,
    TriggerRef,
)
from newsroom.discovery_adapters import AdapterRequestId, ObservationProposalId
from newsroom.sources import (
    CoverageContribution,
    CoverageResponsibility,
    DiscoveryRepresentationId,
    ObservationModel,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
    SourceTime,
    VersionedPolicyRef,
)

NOW = UtcTimestamp.parse("2042-03-12T10:00:00.000000Z")
LATER = UtcTimestamp.parse("2042-03-12T10:00:01.000000Z")
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64
DIGEST_E = "sha256:" + "e" * 64
DIGEST_F = "sha256:" + "f" * 64

REQUEST_ID = CheckRequestId.parse("00000000-0000-4000-8000-000000006001")
ATTEMPT_ID = CheckAttemptId.parse("00000000-0000-4000-8000-000000006002")
OUTCOME_ID = CheckOutcomeId.parse("00000000-0000-4000-8000-000000006003")
DEFINITION_ID = SourceDefinitionId.parse("00000000-0000-4000-8000-000000006004")
VERSION_ID = SourceDefinitionVersionId.parse("00000000-0000-4000-8000-000000006005")
ITEM_ID = SourceItemId.parse("00000000-0000-4000-8000-000000006006")
PRIOR_REVISION_ID = SourceRevisionId.parse("00000000-0000-4000-8000-000000006007")
REVISION_ID = SourceRevisionId.parse("00000000-0000-4000-8000-000000006008")
REPRESENTATION_ID = DiscoveryRepresentationId.parse("00000000-0000-4000-8000-000000006009")
ADAPTER_REQUEST_ID = AdapterRequestId.parse("00000000-0000-4000-8000-000000006010")
PROPOSAL_ID = ObservationProposalId.parse("00000000-0000-4000-8000-000000006011")
BASELINE_ID = BaselineDecisionId.parse("00000000-0000-4000-8000-000000006012")
TRANSITION_ID = ObservableTransitionId.parse("00000000-0000-4000-8000-000000006013")
FINDING_ID = OperationalFindingId.parse("00000000-0000-4000-8000-000000006014")
FINDING_OCCURRENCE_ID = OperationalFindingOccurrenceId.parse(
    "00000000-0000-4000-8000-000000006015"
)


def policy(name: str) -> VersionedPolicyRef:
    return VersionedPolicyRef(name, "v1")


def check_request(
    *,
    request_id: CheckRequestId = REQUEST_ID,
    requested_at: UtcTimestamp = NOW,
    trigger: TriggerRef | None = None,
) -> CheckRequestRequest:
    return CheckRequestRequest(
        request_id=request_id,
        definition_id=DEFINITION_ID,
        definition_version_id=VERSION_ID,
        trigger=trigger
        or TriggerRef(TriggerKind.FIXTURE_MANUAL, "fixture-trigger", "v1"),
        coverage=CoverageBasis(
            "COV-021",
            CoverageResponsibility.ACTIVE,
            CoverageContribution.REVISION_VISIBILITY,
            policy("fixture-coverage"),
        ),
        rights_decision_id="00000000-0000-4000-8000-000000006099",
        rights_policy_version="fixture-rights-v1",
        adapter_request_digest=DIGEST_A,
        producer_slot_digest=DIGEST_B,
        baseline_policy=policy("fixture-baseline"),
        revision_policy=policy("fixture-revision"),
        transition_policy=policy("fixture-transition"),
        validator_policy=policy("fixture-validator"),
        purpose="Exercise deterministic Check authority.",
        requested_at=requested_at,
        idempotency_key="fixture-check-request",
    )


def check_attempt(
    *,
    attempt_id: CheckAttemptId = ATTEMPT_ID,
    attempt_number: int = 1,
    kind: CheckAttemptKind = CheckAttemptKind.PRIMARY,
    prior_attempt_id: CheckAttemptId | None = None,
) -> CheckAttemptRequest:
    return CheckAttemptRequest(
        attempt_id=attempt_id,
        request_id=REQUEST_ID,
        attempt_number=attempt_number,
        kind=kind,
        prior_attempt_id=prior_attempt_id,
        adapter_request_id=ADAPTER_REQUEST_ID,
        adapter_request_digest=DIGEST_A,
        started_at=NOW,
        idempotency_key=f"fixture-attempt-{attempt_number}",
    )


def changed_outcome(
    *,
    kind: CheckOutcomeKind = CheckOutcomeKind.SUCCESS_CHANGED,
    incomplete: bool = False,
    candidates: tuple[CandidateObservationRef, ...] | None = None,
) -> CheckOutcomeRequest:
    selected = candidates
    if selected is None:
        selected = (CandidateObservationRef(DIGEST_C, DIGEST_D),)
    return CheckOutcomeRequest(
        outcome_id=OUTCOME_ID,
        request_id=REQUEST_ID,
        attempt_id=ATTEMPT_ID,
        proposal_id=PROPOSAL_ID,
        definition_id=DEFINITION_ID,
        definition_version_id=VERSION_ID,
        kind=kind,
        reason_codes=("OBSERVABLE_CHANGE_CANDIDATES",),
        quarantine=QuarantineDisposition.NONE,
        incomplete=incomplete,
        receipt_digest=DIGEST_E,
        capture_digest=DIGEST_F,
        parser_result_digest=DIGEST_A,
        source_body_digest=DIGEST_B,
        producer_slot_digest=DIGEST_C,
        representation_digest=DIGEST_D,
        validator_digest=None,
        candidate_observations=selected,
        completed_at=LATER,
        idempotency_key="fixture-check-outcome",
    )


def baseline_entry(
    *,
    disposition: BaselineEntryDisposition = BaselineEntryDisposition.INCLUDED,
) -> BaselineManifestEntry:
    return BaselineManifestEntry(
        item_key=DIGEST_C,
        disposition=disposition,
        reason_code=(
            "INITIAL_INCLUDED"
            if disposition is BaselineEntryDisposition.INCLUDED
            else "OUTSIDE_WINDOW"
        ),
        item_id=ITEM_ID if disposition is BaselineEntryDisposition.INCLUDED else None,
        revision_id=(
            REVISION_ID
            if disposition is BaselineEntryDisposition.INCLUDED
            else None
        ),
    )


def baseline_decision(
    *,
    observation_model: ObservationModel = ObservationModel.MUTABLE_ITEM,
    disposition: BaselineDisposition = BaselineDisposition.MAINTAINED_BASELINE_ONLY,
    entries: tuple[BaselineManifestEntry, ...] | None = None,
) -> BaselineDecisionRequest:
    selected = entries if entries is not None else (baseline_entry(),)
    return BaselineDecisionRequest(
        decision_id=BASELINE_ID,
        definition_id=DEFINITION_ID,
        definition_version_id=VERSION_ID,
        check_request_id=REQUEST_ID,
        check_outcome_id=OUTCOME_ID,
        kind=BaselineDecisionKind.ESTABLISH,
        disposition=disposition,
        observation_model=observation_model,
        baseline_policy=policy("fixture-baseline"),
        previous_decision_id=None,
        entries=selected,
        source_body_digest=DIGEST_B,
        producer_slot_digest=DIGEST_C,
        representation_digest=DIGEST_D,
        validator_digest=None,
        reason_codes=("BASELINE_DECIDED",),
        decided_at=LATER,
        idempotency_key="fixture-baseline-decision",
    )


def absence_guard(*, authorizing: bool = True) -> AbsenceEndingGuard:
    return AbsenceEndingGuard(
        complete_scope_digest=DIGEST_A,
        filter_contract_digest=DIGEST_B,
        pagination_contract_digest=DIGEST_C,
        successful_complete_outcome=authorizing,
        identity_confirmed=True,
        scope_confirmed=True,
        pagination_complete=True,
        confirmation_count=2 if authorizing else 0,
        required_confirmations=2,
        grace_satisfied=True,
        no_alternative_explanation=True,
    )


def agenda_guard(*, authorizing: bool = True) -> AgendaMissGuard:
    return AgendaMissGuard(
        expected_window_digest=DIGEST_A,
        confirmation_paths_digest=DIGEST_B,
        window_closed=authorizing,
        grace_satisfied=True,
        confirmation_paths_checked=True,
        no_reschedule_or_cancellation=True,
        confirmation_outcomes_complete=True,
        source_failure_absent=True,
    )


def first_transition() -> ObservableTransitionRequest:
    return ObservableTransitionRequest(
        transition_id=TRANSITION_ID,
        definition_id=DEFINITION_ID,
        definition_version_id=VERSION_ID,
        check_outcome_id=OUTCOME_ID,
        item_id=ITEM_ID,
        kind=ObservableTransitionKind.FIRST_OBSERVED,
        basis=TransitionBasis.REVISION,
        observation_model=ObservationModel.MUTABLE_ITEM,
        prior_revision_id=None,
        current_revision_id=REVISION_ID,
        representation_id=REPRESENTATION_ID,
        related_item_id=None,
        change_facets=(),
        transition_policy=policy("fixture-transition"),
        absence_guard=None,
        agenda_guard=None,
        source_asserted_time=SourceTime.unknown(),
        observed_at=LATER,
        transition_discriminator="first-observed",
        idempotency_key="fixture-transition",
    )


def operational_finding() -> OperationalFindingRequest:
    return OperationalFindingRequest(
        finding_id=FINDING_ID,
        scope_kind=FindingScopeKind.CHECK_OUTCOME,
        scope_id=str(OUTCOME_ID),
        category=FindingCategory.PARSER,
        severity=FindingSeverity.BLOCKING,
        finding_policy=policy("fixture-finding"),
        summary="Fixture parser condition requires review.",
        opened_by_request_id=REQUEST_ID,
        opened_by_attempt_id=ATTEMPT_ID,
        opened_by_outcome_id=OUTCOME_ID,
        opened_at=LATER,
        idempotency_key="fixture-finding",
    )


def finding_occurrence() -> OperationalFindingOccurrenceRequest:
    return OperationalFindingOccurrenceRequest(
        occurrence_id=FINDING_OCCURRENCE_ID,
        finding_id=FINDING_ID,
        request_id=REQUEST_ID,
        attempt_id=ATTEMPT_ID,
        outcome_id=OUTCOME_ID,
        code="PARSER_REJECTED_INPUT",
        detail_digest=DIGEST_E,
        observed_at=LATER,
        idempotency_key="fixture-finding-occurrence",
    )


def replace_request_time(value: CheckRequestRequest) -> CheckRequestRequest:
    return replace(
        value,
        request_id=CheckRequestId.parse(
            "00000000-0000-4000-8000-000000006101"
        ),
        requested_at=LATER,
        idempotency_key="fixture-check-request-replayed",
    )
