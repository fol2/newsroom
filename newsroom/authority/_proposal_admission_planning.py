from __future__ import annotations

from newsroom.authority.auth import AuthenticationProof
from newsroom.authority.types import AggregateId
from newsroom.checks.admission_models import (
    ProposalAdmissionConflict,
    ProposalAdmissionRequest,
)
from newsroom.checks.types import (
    ObservableTransitionKind,
    TriggerKind,
)
from newsroom.discovery_adapters import ParsedItem
from newsroom.sources import SourceDefinitionVersion
from newsroom.sources.policy import (
    DISCOVERY_OCCURRENCE_RECORD_COMMAND,
    DISCOVERY_REPRESENTATION_RECORD_COMMAND,
    SOURCE_ITEM_REGISTER_COMMAND,
    SOURCE_REVISION_RECORD_COMMAND,
)

from ._proposal_admission_models import _AuthorizedPlan, _ObservationPlan


class _ProposalAdmissionPlanningMixin:
    def _plan_observation(
        self,
        admission: ProposalAdmissionRequest,
        version: SourceDefinitionVersion,
        parsed_item: ParsedItem,
        *,
        trigger_kind: TriggerKind,
    ) -> _ObservationPlan:
        self._validate_permitted_fields(parsed_item, version)
        item_request = self._item_request(
            admission,
            version,
            parsed_item,
        )
        item = self._store.source_item_by_identity_digest(
            version.request.definition_id,
            item_request.identity_digest,
        )
        if item is not None:
            if (
                item.request.identity_policy
                != version.request.item_identity_policy
                or item.request.identity_components
                != item_request.identity_components
            ):
                raise ProposalAdmissionConflict(
                    "retained Source Item differs from exact admission identity"
                )
            item_request = None
            source_item_request = item.request
        else:
            source_item_request = item_request

        latest = self._store.latest_source_revision(
            source_item_request.item_id
        )
        prior_observed = self._store.latest_observed_source_revision(
            source_item_request.item_id,
            exclude_outcome_id=admission.outcome_id,
        )
        if (
            latest is not None
            and latest.request.observed_at.to_text()
            > admission.completed_at.to_text()
        ):
            raise ProposalAdmissionConflict(
                "an older proposal cannot advance a later retained Revision head"
            )
        state_digest = self._permitted_state_digest(parsed_item)
        directive = admission.transition_directive_for(parsed_item.item_key)
        if (
            latest is not None
            and latest.request.source_native_revision_token is None
            and latest.request.permitted_state_digest == state_digest
        ):
            revision = latest
            revision_request = None
            source_revision_request = latest.request
        else:
            revision_request = self._revision_request(
                admission,
                version,
                parsed_item,
                source_item=source_item_request,
                prior=latest,
                state_digest=state_digest,
            )
            revision = self._store.source_revision_by_identity_digest(
                source_item_request.item_id,
                revision_request.revision_identity_digest,
            )
            if revision is not None:
                if (
                    directive is None
                    or directive.kind
                    is not ObservableTransitionKind.REACTIVATED
                ):
                    raise ProposalAdmissionConflict(
                        "observed source state matches a non-head Revision; "
                        "explicit reactivation policy is required"
                    )
                revision_request = None
                source_revision_request = revision.request
            else:
                source_revision_request = revision_request

        representation_request = self._representation_request(
            admission,
            version,
            parsed_item,
            revision_id=source_revision_request.revision_id,
        )
        representation = self._store.representation_by_producer_slot(
            source_revision_request.revision_id,
            representation_request.producer_slot_digest,
        )
        if representation is not None:
            if (
                representation.request.representation_digest
                != representation_request.representation_digest
            ):
                raise ProposalAdmissionConflict(
                    "one exact producer slot emitted conflicting representation"
                )
            representation_request = None
            source_representation_request = representation.request
        else:
            source_representation_request = representation_request

        occurrence = self._store.discovery_occurrence_for_outcome_revision_any(
            check_outcome_id=admission.outcome_id,
            revision_id=source_revision_request.revision_id,
        )
        if occurrence is not None:
            if (
                occurrence.request.representation_id
                != source_representation_request.representation_id
                or occurrence.request.definition_version_id
                != admission.adapter_request.source_definition_version_id
            ):
                raise ProposalAdmissionConflict(
                    "retained Occurrence differs from exact proposal lineage"
                )
            occurrence_request = occurrence.request
        else:
            occurrence_request = self._occurrence_request(
                admission,
                parsed_item,
                trigger_kind=trigger_kind,
                revision_id=source_revision_request.revision_id,
                representation_id=(
                    source_representation_request.representation_id
                ),
                first_observation=(
                    self._store.discovery_occurrence_count_for_revision(
                        source_revision_request.revision_id,
                        exclude_outcome_id=admission.outcome_id,
                    )
                    == 0
                ),
            )
        prior_item_occurrence_count = (
            self._store.discovery_occurrence_count_for_item(
                source_item_request.item_id,
                exclude_outcome_id=admission.outcome_id,
            )
        )
        prior_revision_occurrence_count = (
            self._store.discovery_occurrence_count_for_revision(
                source_revision_request.revision_id,
                exclude_outcome_id=admission.outcome_id,
            )
        )
        return _ObservationPlan(
            parsed_item=parsed_item,
            item=item,
            item_request=item_request,
            prior_revision=prior_observed,
            revision=revision,
            revision_request=revision_request,
            representation=representation,
            representation_request=representation_request,
            occurrence=occurrence,
            occurrence_request=occurrence_request,
            prior_item_occurrence_count=prior_item_occurrence_count,
            prior_revision_occurrence_count=prior_revision_occurrence_count,
        )

    def _authorize_plan(
        self,
        plan: _ObservationPlan,
        proof: AuthenticationProof,
    ) -> _AuthorizedPlan:
        return _AuthorizedPlan(
            plan=plan,
            item_grant=(
                None
                if plan.item_request is None
                else self._authorize(
                    plan.item_request,
                    proof,
                    command_type=SOURCE_ITEM_REGISTER_COMMAND,
                    aggregate_id=AggregateId(plan.item_request.item_id.value),
                )
            ),
            revision_grant=(
                None
                if plan.revision_request is None
                else self._authorize(
                    plan.revision_request,
                    proof,
                    command_type=SOURCE_REVISION_RECORD_COMMAND,
                    aggregate_id=AggregateId(
                        plan.revision_request.revision_id.value
                    ),
                )
            ),
            representation_grant=(
                None
                if plan.representation_request is None
                else self._authorize(
                    plan.representation_request,
                    proof,
                    command_type=DISCOVERY_REPRESENTATION_RECORD_COMMAND,
                    aggregate_id=AggregateId(
                        plan.representation_request.representation_id.value
                    ),
                )
            ),
            occurrence_grant=(
                None
                if plan.occurrence is not None
                else self._authorize(
                    plan.occurrence_request,
                    proof,
                    command_type=DISCOVERY_OCCURRENCE_RECORD_COMMAND,
                    aggregate_id=AggregateId(
                        plan.occurrence_request.occurrence_id.value
                    ),
                )
            ),
        )



__all__ = ["_ProposalAdmissionPlanningMixin"]
