from __future__ import annotations

from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.types import AggregateId, TimePrecision
from newsroom.checks.admission_models import (
    ProposalAdmissionConflict,
    ProposalAdmissionRequest,
    deterministic_uuid4,
)
from newsroom.checks.baseline_models import (
    BaselineDecisionRequest,
    BaselineManifestEntry,
)
from newsroom.checks.policy import (
    CHECK_BASELINE_DECIDE_COMMAND,
    OBSERVABLE_TRANSITION_RECORD_COMMAND,
)
from newsroom.checks.transition_models import ObservableTransitionRequest
from newsroom.discovery_adapters import ObservationProposalOutcome
from newsroom.checks.types import (
    BaselineDecisionId,
    BaselineDecisionKind,
    BaselineDisposition,
    BaselineEntryDisposition,
    ObservableTransitionId,
    ObservableTransitionKind,
    TransitionBasis,
)
from newsroom.sources import BaselinePolicyKind, ObservationModel

from ._proposal_admission_models import (
    _AuthorizedDecisionPlan,
    _DecisionPlan,
    _ObservationPlan,
)


class _ProposalAdmissionDecisionMixin:
    def _maintained_baseline_request(
        self,
        admission: ProposalAdmissionRequest,
        observation: _ObservationPlan,
        *,
        baseline_policy,
    ) -> BaselineDecisionRequest:
        item_request = (
            observation.item.request
            if observation.item is not None
            else observation.item_request
        )
        revision_request = (
            observation.revision.request
            if observation.revision is not None
            else observation.revision_request
        )
        assert item_request is not None
        assert revision_request is not None
        parser = admission.proposal.parser_result
        if parser is None:
            raise ProposalAdmissionConflict(
                "maintained baseline requires exact parser evidence"
            )
        entry = BaselineManifestEntry(
            item_key=observation.parsed_item.item_key,
            disposition=BaselineEntryDisposition.INCLUDED,
            reason_code="INITIAL_MAINTAINED_STATE",
            item_id=item_request.item_id,
            revision_id=revision_request.revision_id,
        )
        decision_id = deterministic_uuid4(
            BaselineDecisionId,
            namespace="increment-3c-maintained-baseline-v1",
            semantic_value={
                "definition_version_id": str(
                    admission.adapter_request.source_definition_version_id
                ),
                "check_outcome_id": str(admission.outcome_id),
                "entry": entry.canonical_value(),
                "policy": baseline_policy.canonical_value(),
            },
        )
        return BaselineDecisionRequest(
            decision_id=decision_id,
            definition_id=admission.adapter_request.source_definition_id,
            definition_version_id=(
                admission.adapter_request.source_definition_version_id
            ),
            check_request_id=admission.check_request_id,
            check_outcome_id=admission.outcome_id,
            kind=BaselineDecisionKind.ESTABLISH,
            disposition=BaselineDisposition.MAINTAINED_BASELINE_ONLY,
            observation_model=ObservationModel.MUTABLE_ITEM,
            baseline_policy=baseline_policy,
            previous_decision_id=None,
            entries=(entry,),
            source_body_digest=parser.source_body_digest,
            producer_slot_digest=parser.producer_slot_digest,
            representation_digest=parser.representation_digest,
            validator_digest=admission.validator_digest,
            reason_codes=("MAINTAINED_BASELINE_ONLY",),
            decided_at=admission.completed_at,
            idempotency_key=f"proposal-baseline:{decision_id}",
        )

    def _revision_transition_request(
        self,
        admission: ProposalAdmissionRequest,
        observation: _ObservationPlan,
        *,
        transition_policy,
    ) -> ObservableTransitionRequest | None:
        if (
            admission.proposal.outcome
            is not ObservationProposalOutcome.SUCCESS_CHANGED
        ):
            return None
        revision_request = (
            observation.revision.request
            if observation.revision is not None
            else observation.revision_request
        )
        if revision_request is None or revision_request.prior_revision_id is None:
            return None
        representation_request = (
            observation.representation.request
            if observation.representation is not None
            else observation.representation_request
        )
        if representation_request is None:
            raise ProposalAdmissionConflict(
                "changed Revision lacks its exact Representation"
            )
        transition_id = deterministic_uuid4(
            ObservableTransitionId,
            namespace="increment-3c-revision-transition-v1",
            semantic_value={
                "check_outcome_id": str(admission.outcome_id),
                "item_id": str(revision_request.item_id),
                "prior_revision_id": str(
                    revision_request.prior_revision_id
                ),
                "current_revision_id": str(revision_request.revision_id),
                "representation_id": str(
                    representation_request.representation_id
                ),
                "policy": transition_policy.canonical_value(),
            },
        )
        occurrence = observation.occurrence_request
        source_asserted_time = occurrence.source_asserted_time
        if source_asserted_time.precision is TimePrecision.UNKNOWN:
            source_asserted_time = revision_request.source_updated_time
        return ObservableTransitionRequest(
            transition_id=transition_id,
            definition_id=admission.adapter_request.source_definition_id,
            definition_version_id=(
                admission.adapter_request.source_definition_version_id
            ),
            check_outcome_id=admission.outcome_id,
            item_id=revision_request.item_id,
            kind=ObservableTransitionKind.REVISED,
            basis=TransitionBasis.REVISION,
            observation_model=ObservationModel.MUTABLE_ITEM,
            prior_revision_id=revision_request.prior_revision_id,
            current_revision_id=revision_request.revision_id,
            representation_id=representation_request.representation_id,
            related_item_id=None,
            change_facets=("PERMITTED_STATE_DIGEST",),
            transition_policy=transition_policy,
            absence_guard=None,
            agenda_guard=None,
            source_asserted_time=source_asserted_time,
            observed_at=admission.completed_at,
            transition_discriminator="revision-state-change",
            idempotency_key=f"proposal-transition:{transition_id}",
        )

    def _plan_decisions(
        self,
        admission: ProposalAdmissionRequest,
        observations: tuple[_ObservationPlan, ...],
        *,
        version,
        retained_request,
    ) -> _DecisionPlan:
        baseline = None
        baseline_request = None
        transitions = []
        transition_requests = []
        source = version.request
        if (
            source.observation_model is ObservationModel.MUTABLE_ITEM
            and source.baseline_policy.kind
            is BaselinePolicyKind.MAINTAINED_DOCUMENT
        ):
            if len(observations) > 1:
                raise ProposalAdmissionConflict(
                    "maintained-document admission must resolve one logical item"
                )
            current = self._store.current_baseline_decision(
                source.definition_id
            )
            if current is None and observations:
                baseline_request = self._maintained_baseline_request(
                    admission,
                    observations[0],
                    baseline_policy=retained_request.request.baseline_policy,
                )
                baseline = self._store.baseline_decision(
                    baseline_request.decision_id
                )
                if baseline is not None:
                    if baseline.request.digest != baseline_request.digest:
                        raise ProposalAdmissionConflict(
                            "retained maintained baseline differs from exact admission"
                        )
                    baseline_request = None
            elif (
                current is not None
                and current.request.check_outcome_id == admission.outcome_id
            ):
                baseline = current

            if current is not None:
                for observation in observations:
                    transition_request = self._revision_transition_request(
                        admission,
                        observation,
                        transition_policy=(
                            retained_request.request.transition_policy
                        ),
                    )
                    if transition_request is None:
                        continue
                    existing = self._store.observable_transition(
                        transition_request.transition_id
                    )
                    if existing is not None:
                        if existing.request.digest != transition_request.digest:
                            raise ProposalAdmissionConflict(
                                "retained Revision transition differs from admission"
                            )
                        transitions.append(existing)
                    else:
                        transition_requests.append(transition_request)
        return _DecisionPlan(
            baseline=baseline,
            baseline_request=baseline_request,
            transitions=tuple(transitions),
            transition_requests=tuple(transition_requests),
        )

    def _authorize_decisions(
        self,
        plan: _DecisionPlan,
        proof: AuthenticationProof,
    ) -> _AuthorizedDecisionPlan:
        return _AuthorizedDecisionPlan(
            plan=plan,
            baseline_grant=(
                None
                if plan.baseline_request is None
                else self._authorize(
                    plan.baseline_request,
                    proof,
                    command_type=CHECK_BASELINE_DECIDE_COMMAND,
                    aggregate_id=AggregateId(
                        plan.baseline_request.decision_id.value
                    ),
                )
            ),
            transition_grants=tuple(
                self._authorize(
                    request,
                    proof,
                    command_type=OBSERVABLE_TRANSITION_RECORD_COMMAND,
                    aggregate_id=AggregateId(request.transition_id.value),
                )
                for request in plan.transition_requests
            ),
        )


__all__ = ["_ProposalAdmissionDecisionMixin"]
