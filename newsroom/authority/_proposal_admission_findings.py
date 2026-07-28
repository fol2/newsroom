from __future__ import annotations

from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.types import AggregateId
from newsroom.checks.admission_models import (
    ProposalAdmissionConflict,
    ProposalAdmissionRequest,
    deterministic_uuid4,
)
from newsroom.checks.finding_models import (
    OperationalFindingOccurrenceRequest,
    OperationalFindingRequest,
)
from newsroom.checks.policy import (
    OPERATIONAL_FINDING_OCCURRENCE_RECORD_COMMAND,
    OPERATIONAL_FINDING_OPEN_COMMAND,
)
from newsroom.checks.types import (
    FindingCategory,
    FindingScopeKind,
    FindingSeverity,
    OperationalFindingId,
    OperationalFindingOccurrenceId,
)
from newsroom.discovery_adapters import ObservationProposalOutcome
from newsroom.sources import VersionedPolicyRef

from ._proposal_admission_models import (
    _AuthorizedFindingPlan,
    _FindingPlan,
)


_FINDING_CLASS = {
    ObservationProposalOutcome.BLOCKED: (
        FindingCategory.POLICY,
        FindingSeverity.BLOCKING,
        "Source observation was blocked by retained policy.",
    ),
    ObservationProposalOutcome.SUCCESS_PARTIAL: (
        FindingCategory.PARSER,
        FindingSeverity.DEGRADED,
        "Source parsing produced an incomplete observation.",
    ),
    ObservationProposalOutcome.SUCCESS_TRUNCATED: (
        FindingCategory.PARSER,
        FindingSeverity.DEGRADED,
        "Source parsing reached a retained resource limit.",
    ),
    ObservationProposalOutcome.REDIRECTED: (
        FindingCategory.SOURCE_CONTRACT,
        FindingSeverity.DEGRADED,
        "Source redirection prevented a complete observation.",
    ),
    ObservationProposalOutcome.RATE_LIMITED: (
        FindingCategory.TRANSPORT,
        FindingSeverity.DEGRADED,
        "Source transport was rate limited.",
    ),
    ObservationProposalOutcome.UNAUTHORISED: (
        FindingCategory.RIGHTS,
        FindingSeverity.BLOCKING,
        "Source access did not satisfy retained access conditions.",
    ),
    ObservationProposalOutcome.NOT_FOUND: (
        FindingCategory.SOURCE_CONTRACT,
        FindingSeverity.DEGRADED,
        "The retained source endpoint was not found.",
    ),
    ObservationProposalOutcome.GONE: (
        FindingCategory.SOURCE_CONTRACT,
        FindingSeverity.BLOCKING,
        "The retained source endpoint reported that it is gone.",
    ),
    ObservationProposalOutcome.MALFORMED: (
        FindingCategory.PARSER,
        FindingSeverity.BLOCKING,
        "Source bytes could not be parsed under the retained contract.",
    ),
    ObservationProposalOutcome.SHAPE_DRIFT: (
        FindingCategory.SOURCE_CONTRACT,
        FindingSeverity.INTEGRITY,
        "Source shape differs from the retained source contract.",
    ),
    ObservationProposalOutcome.TRANSPORT_FAILED: (
        FindingCategory.TRANSPORT,
        FindingSeverity.DEGRADED,
        "Source transport failed before a complete observation.",
    ),
}


class _ProposalAdmissionFindingMixin:
    def _plan_finding(
        self,
        admission: ProposalAdmissionRequest,
    ) -> _FindingPlan:
        selected = _FINDING_CLASS.get(admission.proposal.outcome)
        if selected is None:
            return _FindingPlan(None, None, None, None)
        category, severity, summary = selected
        policy = VersionedPolicyRef(
            f"increment-3c-{category.value.lower()}-finding",
            f"{severity.value.lower()}-v1",
        )
        finding_id = deterministic_uuid4(
            OperationalFindingId,
            namespace="increment-3c-operational-finding-v1",
            semantic_value={
                "source_definition_version_id": str(
                    admission.adapter_request.source_definition_version_id
                ),
                "category": category.value,
                "policy": policy.canonical_value(),
            },
        )
        expected_finding = OperationalFindingRequest(
            finding_id=finding_id,
            scope_kind=FindingScopeKind.SOURCE_VERSION,
            scope_id=str(
                admission.adapter_request.source_definition_version_id
            ),
            category=category,
            severity=severity,
            finding_policy=policy,
            summary=summary,
            opened_by_request_id=admission.check_request_id,
            opened_by_attempt_id=admission.check_attempt_id,
            opened_by_outcome_id=admission.outcome_id,
            opened_at=admission.completed_at,
            idempotency_key=f"proposal-finding:{finding_id}",
        )
        existing = self._store.operational_finding(finding_id)
        finding_request = expected_finding if existing is None else None
        if existing is not None and (
            existing.request.semantic_digest
            != expected_finding.semantic_digest
            or existing.request.severity is not severity
            or existing.request.summary != summary
        ):
            raise ProposalAdmissionConflict(
                "retained Operational Finding differs from exact source case"
            )
        occurrence_id = deterministic_uuid4(
            OperationalFindingOccurrenceId,
            namespace="increment-3c-finding-occurrence-v1",
            semantic_value={
                "finding_id": str(finding_id),
                "check_outcome_id": str(admission.outcome_id),
                "proposal_digest": admission.proposal.digest,
            },
        )
        expected_occurrence = OperationalFindingOccurrenceRequest(
            occurrence_id=occurrence_id,
            finding_id=finding_id,
            request_id=admission.check_request_id,
            attempt_id=admission.check_attempt_id,
            outcome_id=admission.outcome_id,
            code=f"PROPOSAL_{admission.proposal.outcome.value}",
            detail_digest=admission.proposal.digest,
            observed_at=admission.completed_at,
            idempotency_key=f"proposal-finding-occurrence:{occurrence_id}",
        )
        occurrence = self._store.finding_occurrence_by_identity(
            occurrence_id
        )
        occurrence_request = (
            expected_occurrence if occurrence is None else None
        )
        if (
            occurrence is not None
            and occurrence.request.digest != expected_occurrence.digest
        ):
            raise ProposalAdmissionConflict(
                "retained Finding occurrence differs from exact proposal"
            )
        return _FindingPlan(
            finding=existing,
            finding_request=finding_request,
            occurrence=occurrence,
            occurrence_request=occurrence_request,
        )

    def _authorize_finding(
        self,
        plan: _FindingPlan,
        proof: AuthenticationProof,
    ) -> _AuthorizedFindingPlan:
        return _AuthorizedFindingPlan(
            plan=plan,
            finding_grant=(
                None
                if plan.finding_request is None
                else self._authorize(
                    plan.finding_request,
                    proof,
                    command_type=OPERATIONAL_FINDING_OPEN_COMMAND,
                    aggregate_id=AggregateId(
                        plan.finding_request.finding_id.value
                    ),
                )
            ),
            occurrence_grant=(
                None
                if plan.occurrence_request is None
                else self._authorize(
                    plan.occurrence_request,
                    proof,
                    command_type=(
                        OPERATIONAL_FINDING_OCCURRENCE_RECORD_COMMAND
                    ),
                    aggregate_id=AggregateId(
                        plan.occurrence_request.occurrence_id.value
                    ),
                )
            ),
        )


__all__ = ["_ProposalAdmissionFindingMixin"]
